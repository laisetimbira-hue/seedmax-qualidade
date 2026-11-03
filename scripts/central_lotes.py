"""
SEEDMAX — Central de Lotes (fase 1: SOMENTE LEITURA dos módulos)

Monta um índice-resumo por lote em lots/{lotId} no Firebase "seedmax",
consolidando:

  Qualidade  (seedmax-4c755 / qualidade/*)        — cultivar, categoria, peneira,
                                                    PMS, bags, classe/aprovação
  TSI        (estoquetsi / lotesTratamento)        — ordens com lote de semente
  RASTREL    (rastreabilidade-a511a / bags)        — bags, tags, expedição

Regras desta fase:
  * TSI e RASTREL são SÓ LIDOS (credencial sem permissão de escrita).
  * Nada é gravado de volta em nenhum módulo; só lots/{lotId} no seedmax.
  * Nenhum documento de lots/ é apagado: lote que sumiu da origem fica com
    presente=false.
  * Não copia as coleções inteiras: só o resumo necessário para integrar.

Uso:
  python scripts/central_lotes.py sincronizar            # robô (GitHub Actions)
  python scripts/central_lotes.py sincronizar --simular  # só calcula, não grava
  python scripts/central_lotes.py provar-somente-leitura # TSI/RASTREL recusam escrita?

Variáveis de ambiente:
  FIREBASE_SERVICE_ACCOUNT  chave do robô do seedmax (já existe — grava lots/)
  CENTRAL_TSI=sim           liga a leitura do TSI     (credencial via WIF)
  CENTRAL_RASTREL=sim       liga a leitura do RASTREL (credencial via WIF)
  TSI_CREDENCIAIS / RASTREL_CREDENCIAIS
                            arquivo de credencial gerado pelo
                            google-github-actions/auth (Workload Identity
                            Federation — sem chave JSON permanente)
"""

import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PROJETO_TSI = "estoquetsi"
PROJETO_RASTREL = "rastreabilidade-a511a"
SAFRA_PADRAO = "SOJA2526"
SEM_SAFRA = "SEMSAFRA"
ESQUEMA = 1

# ---------------------------------------------------------------- situação
# Ordem do fluxo: Qualidade → TSI → RASTREL → Expedição
SITUACOES = [
    "QUALIDADE PENDENTE",
    "LIBERADO PARA TSI",
    "EM TSI",
    "AGUARDANDO RASTREL",
    "RASTREANDO",
    "PRONTO",
    "INDETERMINADO",
]

# Classe da Qualidade → aprovação (mesma regra do dashboard da Qualidade:
# aprovados = A + B; condicionais = C e BV; reprovado = D; X = pendente).
APROVACAO_POR_CLASSE = {
    "A": "APROVADO", "B": "APROVADO",
    "C": "CONDICIONAL", "BV": "CONDICIONAL",
    "D": "REPROVADO", "X": "PENDENTE",
}


# ---------------------------------------------------------------- normalização

def codigo_lote(bruto):
    """Código do lote como chave de comparação: maiúsculas, sem espaços,
    sem ponto/traço sobrando no fim. Ex.: ' 26s35b. ' → '26S35B'."""
    s = str(bruto or "").strip().upper()
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^A-Z0-9/_-]+$", "", s)   # pontuação no fim (digitação)
    s = re.sub(r"^[^A-Z0-9]+", "", s)
    return s


def montar_lot_id(safra, lot_code):
    seguro = re.sub(r"[^A-Za-z0-9_-]+", "-", lot_code).strip("-")
    return f"{safra}_{seguro}" if seguro else None


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def cultivar_canonica(nome, apelidos):
    """Nome da cultivar comparável entre módulos.
    'Zeus', '55I57RSF IPRO — Zeus', '56IX58RSF I2X (TITANIUM)' → código."""
    if not nome:
        return ""
    s = str(nome).strip()
    s = s.split("—")[0].split(" - ")[0]
    s = re.sub(r"\(.*?\)", "", s)
    s = _sem_acento(re.sub(r"\s+", " ", s).strip().upper())
    if s in apelidos:
        return apelidos[s]
    return s.replace(" ", "")


def montar_apelidos(cv_meta):
    """{'ZEUS': '55I57RSFIPRO', '55I57RSF IPRO': '55I57RSFIPRO', ...}"""
    ap = {}
    for codigo, info in (cv_meta or {}).items():
        canon = _sem_acento(codigo.upper()).replace(" ", "")
        ap[_sem_acento(codigo.upper().strip())] = canon
        nome = (info or {}).get("nome")
        if nome:
            ap[_sem_acento(nome.upper().strip())] = canon
    return ap


def montar_nomes(cv_meta):
    """{'55I57RSFIPRO': 'Zeus', ...} — nome comercial para a busca."""
    return {_sem_acento(c.upper()).replace(" ", ""): (i or {}).get("nome")
            for c, i in (cv_meta or {}).items() if (i or {}).get("nome")}


def _num(v):
    try:
        if v is None or v == "":
            return None
        f = float(str(v).replace(",", "."))
        return None if f != f else f
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- resumos por módulo

def resumir_qualidade(dados):
    """{lotCode: resumo} a partir dos conjuntos da Qualidade (LOTS e
    LOTES_COMPRADOS da safra de Verão)."""
    out = {}
    for fonte, lista in (("producao", dados.get("LOTS")), ("comprado", dados.get("LOTES_COMPRADOS"))):
        for x in lista or []:
            code = codigo_lote(x.get("lote"))
            if not code:
                continue
            if fonte == "producao":
                classe = (x.get("ranking") or "").strip().upper() or None
                aprov = APROVACAO_POR_CLASSE.get(classe, "PENDENTE")
                rotulo = x.get("status")
                categoria = x.get("categoria")
            else:
                st = (x.get("status") or "").strip().upper()
                classe = None
                aprov = "APROVADO" if st == "APROVADO" else "PENDENTE"
                rotulo = x.get("status") or "sem status"
                categoria = x.get("categoria_reembalado") or x.get("categoria_origem")
            out[code] = {
                "fonte": fonte,
                "codigoOriginal": x.get("lote"),
                "cultivar": x.get("cultivar"),
                "categoria": categoria,
                "peneira": x.get("peneira"),
                "pms": _num(x.get("pms_etq")),
                "bags": _num(x.get("bags")),
                "kg": _num(x.get("kg")),
                "pesoBag": _num(x.get("peso_bag")),
                "classe": classe,
                "rotulo": rotulo,
                "status": aprov,
                "germ": _num(x.get("germ") if fonte == "producao" else x.get("germ_oficial")),
                "vigor": _num(x.get("vigor") if fonte == "producao" else x.get("vigor_oficial")),
            }
    return out


def resumir_tsi(ordens):
    """ordens = lista de documentos de lotesTratamento (dicts, com 'id').
    Só ordens que informam o lote de semente (lotesDetalhe) entram no
    vínculo. Devolve ({lotCode: resumo}, estatísticas)."""
    out = {}
    est = {"ordens": 0, "ordensComLote": 0, "ordensSemLote": 0, "linhasDeLote": 0}
    for o in ordens or []:
        est["ordens"] += 1
        linhas = o.get("lotesDetalhe") or []
        if not linhas:
            est["ordensSemLote"] += 1
            continue
        est["ordensComLote"] += 1
        # No TSI, ordem "aberta" = importada/em tratamento; "fechada" ou sem
        # status (ordens antigas) = concluída e já baixou o estoque.
        concluida = (o.get("status") != "aberta")
        for l in linhas:
            est["linhasDeLote"] += 1
            src = codigo_lote(l.get("origem"))
            dst = codigo_lote(l.get("destino")) or src
            if not src:
                continue
            r = out.setdefault(src, {"ordens": [], "codigosOriginais": set(), "destinos": set(),
                                     "cultivares": set(), "pms": set(), "pesosBag": set(), "qtdOrigem": 0.0,
                                     "qtdDestino": 0.0, "kg": 0.0, "concluidas": 0, "abertas": 0})
            r["codigosOriginais"].add(str(l.get("origem")))
            r["destinos"].add(dst)
            r["cultivares"].add((o.get("cultivar") or "").strip())
            if _num(l.get("pms")) is not None:
                r["pms"].add(_num(l.get("pms")))
            if _num(l.get("pesoBag")) and _num(l.get("qtdOrigem")) == _num(l.get("qtdDestino")):
                r["pesosBag"].add(_num(l.get("pesoBag")))  # só bags não reembalados
            r["qtdOrigem"] += _num(l.get("qtdOrigem")) or 0
            r["qtdDestino"] += _num(l.get("qtdDestino")) or 0
            r["kg"] += _num(l.get("kg")) or 0
            r["ordens"].append({
                "ordem": str(o.get("numeroLote") or o.get("id") or ""),
                "status": "CONCLUÍDA" if concluida else "EM ANDAMENTO",
                "data": o.get("data"),
                "receita": o.get("receitaNome"),
                "sourceLotCode": src, "treatedLotCode": dst,
                "qtdOrigem": _num(l.get("qtdOrigem")), "qtdDestino": _num(l.get("qtdDestino")),
                "unidade": l.get("unidade"), "kg": _num(l.get("kg")), "pms": _num(l.get("pms")),
            })
            if concluida:
                r["concluidas"] += 1
            else:
                r["abertas"] += 1
    return out, est


def resumir_rastrel(bags):
    """bags = lista de documentos da coleção bags. Devolve {lotCode: resumo}."""
    out = {}
    for b in bags or []:
        code = codigo_lote(b.get("lote"))
        if not code:
            continue
        r = out.setdefault(code, {"bags": 0, "tags": 0, "kg": 0.0, "expedidos": 0, "emEstoque": 0,
                                  "codigosOriginais": set(), "cultivares": {}, "categorias": {},
                                  "peneiras": {}, "tratamentos": {}, "status": {}})
        r["bags"] += 1
        if b.get("epc"):
            r["tags"] += 1
        r["kg"] += _num(b.get("peso_kg")) or 0
        st = (b.get("status") or "").strip()
        if st == "expedido":
            r["expedidos"] += 1
        elif st == "em_estoque":
            r["emEstoque"] += 1
        r["codigosOriginais"].add(str(b.get("lote")))
        for campo, valor in (("cultivares", b.get("cultivar_nome")), ("categorias", b.get("categoria")),
                             ("peneiras", b.get("peneira")), ("tratamentos", b.get("tratamento")),
                             ("status", st)):
            v = (str(valor).strip() if valor is not None else "") or "—"
            r[campo][v] = r[campo].get(v, 0) + 1
    return out


# ---------------------------------------------------------------- consolidação

def _unico(d):
    """valor quando há um só; None se vazio; lista se vários."""
    chaves = [k for k in d if k and k != "—"]
    return chaves[0] if len(chaves) == 1 else (None if not chaves else sorted(chaves))


def _situacao(q, t, r, tsi_conectado, rastrel_conectado):
    """(situação, motivo). Só afirma o que os dados permitem."""
    if not q:
        return "INDETERMINADO", "Lote não encontrado na Gestão de Qualidade."
    if q["status"] != "APROVADO":
        if t or r:
            return "INDETERMINADO", ("Qualidade não aprovada (" + q["status"].lower() +
                                     "), mas o lote já aparece no " + ("TSI" if t else "RASTREL") + ".")
        return "QUALIDADE PENDENTE", "Qualidade " + q["status"].lower() + "."
    # aprovado na Qualidade
    if not tsi_conectado:
        return "INDETERMINADO", "TSI ainda não conectado à Central."
    if t and t["abertas"]:
        return "EM TSI", "Ordem de tratamento em andamento."
    if not t:
        if not rastrel_conectado:
            return "INDETERMINADO", "TSI sem ordem com este lote; RASTREL ainda não conectado à Central."
        if r:
            return "INDETERMINADO", ("Bags no RASTREL, mas nenhuma ordem do TSI informa este lote "
                                     "(as ordens antigas do TSI não registram o lote de semente).")
        return "LIBERADO PARA TSI", ("Aprovado na Qualidade; nenhuma ordem do TSI registra este lote. "
                                     "Atenção: ordens antigas do TSI não informam o lote.")
    # TSI concluído
    if not rastrel_conectado:
        return "INDETERMINADO", "TSI concluído; RASTREL ainda não conectado à Central."
    previstos = q.get("bags")
    tags = r["tags"] if r else 0
    if tags == 0:
        return "AGUARDANDO RASTREL", "TSI concluído; nenhum bag com tag no RASTREL."
    if not previstos:
        return "INDETERMINADO", "TSI concluído e bags no RASTREL, mas a Qualidade não informa quantos bags são previstos."
    if tags < previstos:
        return "RASTREANDO", f"{tags} de {int(previstos)} bags previstos com tag."
    return "PRONTO", f"TSI concluído e {tags} de {int(previstos)} bags com tag."


def _diverg(lista, campo, texto, tipo="divergencia", **valores):
    """tipo: 'divergencia' (dado diferente entre módulos) ou 'aviso'
    (falta informação, não necessariamente erro)."""
    lista.append(dict({"campo": campo, "tipo": tipo, "texto": texto},
                      **{k: v for k, v in valores.items() if v is not None}))


def consolidar(qualidade, tsi, rastrel, apelidos, carimbo,
               tsi_conectado=True, rastrel_conectado=True, safra=SAFRA_PADRAO, nomes=None):
    """Junta os três resumos por código de lote → {lotId: documento}."""
    codigos = set(qualidade) | set(tsi or {}) | set(rastrel or {})
    docs = {}
    for code in sorted(codigos):
        q = qualidade.get(code)
        t = (tsi or {}).get(code)
        r = (rastrel or {}).get(code)
        crop = safra if q else SEM_SAFRA
        lot_id = montar_lot_id(crop, code)
        div = []

        # ---- lote: código digitado diferente da forma padrão
        originais = set()
        if q:
            originais.add(str(q["codigoOriginal"]))
        if t:
            originais |= t["codigosOriginais"]
        if r:
            originais |= r["codigosOriginais"]
        estranhos = sorted(o for o in originais if o != code)
        if estranhos:
            _diverg(div, "lote", "Código escrito de forma diferente: " + ", ".join(repr(e) for e in estranhos))

        # ---- cultivar
        cq = cultivar_canonica(q["cultivar"], apelidos) if q else None
        if r:
            cr = {cultivar_canonica(c, apelidos) for c in r["cultivares"] if c != "—"}
            if len(cr) > 1:
                _diverg(div, "cultivar", "RASTREL tem mais de uma cultivar no mesmo lote",
                        rastrel=sorted(r["cultivares"]))
            elif cq and cr and cq not in cr:
                _diverg(div, "cultivar", "Cultivar diferente entre Qualidade e RASTREL",
                        qualidade=q["cultivar"], rastrel=sorted(r["cultivares"]))
        if t:
            ct = {cultivar_canonica(c, apelidos) for c in t["cultivares"] if c}
            if cq and ct and cq not in ct:
                _diverg(div, "cultivar", "Cultivar diferente entre Qualidade e TSI",
                        qualidade=q["cultivar"], tsi=sorted(t["cultivares"]))

        # ---- categoria / peneira (RASTREL guarda por bag)
        if q and r:
            for campo, chave in (("categoria", "categorias"), ("peneira", "peneiras")):
                vr = _unico(r[chave])
                vq = q.get(campo)
                if isinstance(vr, list):
                    _diverg(div, campo, f"RASTREL tem mais de uma {campo} no mesmo lote", rastrel=vr)
                elif vr and vq and str(vr).upper() != str(vq).upper():
                    _diverg(div, campo, f"{campo.capitalize()} diferente entre Qualidade e RASTREL",
                            qualidade=vq, rastrel=vr)

        # ---- PMS (Qualidade × TSI)
        if q and t and q.get("pms") and t["pms"]:
            fora = sorted(p for p in t["pms"] if abs(p - q["pms"]) > 0.5)
            if fora:
                _diverg(div, "pms", "PMS do TSI diferente do PMS de etiqueta da Qualidade",
                        qualidade=q["pms"], tsi=fora)

        # ---- bags
        if q and t and q.get("bags") and t["qtdOrigem"] and t["qtdOrigem"] > q["bags"] + 0.01:
            _diverg(div, "bags", "TSI tratou mais bags do que a Qualidade registra",
                    qualidade=q["bags"], tsi=round(t["qtdOrigem"], 2))
        if q and r and q.get("bags"):
            if r["bags"] > q["bags"]:
                _diverg(div, "bags", "RASTREL tem mais bags do que a Qualidade registra",
                        qualidade=q["bags"], rastrel=r["bags"])
        if r and r["tags"] < r["bags"]:
            _diverg(div, "tags", "Bags sem tag NFC no RASTREL", rastrel=f"{r['tags']} de {r['bags']}")
        if r and r["kg"] == 0 and r["bags"]:
            _diverg(div, "kg", "Bags do RASTREL sem peso", tipo="aviso", rastrel=r["bags"])
        elif q and r and q.get("pesoBag") and r["bags"]:
            medio = r["kg"] / r["bags"]
            if abs(medio - q["pesoBag"]) > 0.03 * q["pesoBag"]:
                _diverg(div, "kg", "Peso médio por bag do RASTREL diferente do peso por bag da Qualidade",
                        qualidade=q["pesoBag"], rastrel=round(medio, 1))
        if q and t and q.get("pesoBag") and t["pesosBag"]:
            fora = sorted(p for p in t["pesosBag"] if abs(p - q["pesoBag"]) > 0.03 * q["pesoBag"])
            if fora:
                _diverg(div, "kg", "Peso por bag do TSI diferente do peso por bag da Qualidade",
                        qualidade=q["pesoBag"], tsi=fora)
        if q and q["status"] != "APROVADO" and (t or r):
            _diverg(div, "qualidade", "Lote movimentado sem aprovação na Qualidade",
                    qualidade=q["status"], tsi=("tratado" if t else None), rastrel=(f"{r['bags']} bags" if r else None))

        # ---- tratamento
        if r:
            trat = _unico(r["tratamentos"])
            if isinstance(trat, list):
                _diverg(div, "tratamento", "RASTREL tem mais de um tratamento no mesmo lote", rastrel=trat)
            if not t and tsi_conectado and any(k != "—" for k in r["tratamentos"]):
                _diverg(div, "tratamento", "RASTREL indica tratamento, mas nenhuma ordem do TSI informa este lote",
                        tipo="aviso", rastrel=sorted(k for k in r["tratamentos"] if k != "—"))

        # ---- TSI: origem/destino
        if t:
            dests = sorted(t["destinos"])
            treated = dests[0] if len(dests) == 1 else None
            if len(dests) > 1:
                _diverg(div, "tsi", "Um lote de origem gerou mais de um lote tratado", tsi=dests)
        else:
            treated = None

        situacao, motivo = _situacao(q, t, r, tsi_conectado, rastrel_conectado)

        if not tsi_conectado:
            tsi_status = "NÃO CONECTADO"
        elif not t:
            tsi_status = "SEM ORDEM COM LOTE"
        elif t["abertas"]:
            tsi_status = "EM ANDAMENTO"
        else:
            tsi_status = "CONCLUÍDO"

        if not rastrel_conectado:
            rastrel_status = "NÃO CONECTADO"
        elif not r:
            rastrel_status = "SEM BAGS"
        elif q and q.get("bags") and r["tags"] >= q["bags"]:
            rastrel_status = "COMPLETO"
        elif q and q.get("bags"):
            rastrel_status = "PARCIAL"
        else:
            rastrel_status = "COM BAGS"

        base = q or {}
        doc = {
            "esquema": ESQUEMA,
            "lotId": lot_id,
            "lotCode": code,
            "crop": crop,
            "safra": crop,
            "cultivar": base.get("cultivar") or (sorted(t["cultivares"])[0] if t and t["cultivares"] else None)
                        or (_unico(r["cultivares"]) if r and not isinstance(_unico(r["cultivares"]), list) else None),
            "categoria": base.get("categoria") or (_unico(r["categorias"]) if r and not isinstance(_unico(r["categorias"]), list) else None),
            "peneira": base.get("peneira") or (_unico(r["peneiras"]) if r and not isinstance(_unico(r["peneiras"]), list) else None),
            "pms": base.get("pms"),
            # Qualidade (fonte oficial: cultivar, categoria, peneira, resultados, aprovação, classe)
            "qualidadeStatus": q["status"] if q else "NÃO ENCONTRADO",
            "qualidadeClasse": q["classe"] if q else None,
            "qualidade": None if not q else {
                "fonte": q["fonte"], "rotulo": q["rotulo"], "bags": q["bags"], "kg": q["kg"],
                "germ": q["germ"], "vigor": q["vigor"], "pms": q["pms"],
            },
            # TSI (fonte oficial: ordens, receita, origem/destino)
            "tsiStatus": tsi_status,
            "sourceLotId": lot_id if t else None,
            "treatedLotId": (montar_lot_id(crop, treated) if treated else None),
            "tsi": None if not t else {
                "ordens": sorted(t["ordens"], key=lambda o: (o.get("data") or "", o["ordem"])),
                "bagsOrigem": round(t["qtdOrigem"], 2), "embalagensDestino": round(t["qtdDestino"], 2),
                "kg": round(t["kg"], 1), "pms": sorted(t["pms"]),
            },
            "parentLotIds": [],
            # RASTREL (fonte oficial: bag, tag, localização, movimentação, carga, expedição)
            "rastrelStatus": rastrel_status,
            "totalBags": int(base["bags"]) if base.get("bags") else None,
            "taggedBags": r["tags"] if r else 0,
            "rastrel": None if not r else {
                "bags": r["bags"], "tags": r["tags"], "kg": round(r["kg"], 1),
                "expedidos": r["expedidos"], "emEstoque": r["emEstoque"],
                "tratamentos": r["tratamentos"], "cultivares": r["cultivares"],
            },
            "modulos": [m for m, v in (("QUALIDADE", q), ("TSI", t), ("RASTREL", r)) if v],
            "situacao": situacao,
            "motivo": motivo,
            "divergencias": div,
            "presente": True,
        }
        doc["cultivarNome"] = (nomes or {}).get(cultivar_canonica(doc["cultivar"], apelidos)) if doc["cultivar"] else None
        doc["hash"] = hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False, default=list)
                                     .encode()).hexdigest()[:16]
        doc["lastUpdate"] = carimbo
        docs[lot_id] = doc
    return docs


# ---------------------------------------------------------------- leitura (somente leitura)

def _cliente_leitura(projeto, var_credencial):
    """Cliente Firestore com a credencial federada (WIF) do projeto.
    O arquivo vem do google-github-actions/auth; não há chave JSON."""
    import google.auth
    from google.cloud import firestore
    caminho = os.environ.get(var_credencial, "").strip()
    if not caminho or not os.path.exists(caminho):
        raise SystemExit(f"ERRO: credencial {var_credencial} não encontrada (WIF não configurado?).")
    cred, _ = google.auth.load_credentials_from_file(
        caminho, scopes=["https://www.googleapis.com/auth/datastore"])
    return firestore.Client(project=projeto, credentials=cred)


def _ler_colecao(cliente, nome, campos=None):
    q = cliente.collection(nome)
    if campos:
        q = q.select(campos)  # só os campos necessários
    docs = []
    for d in q.stream():
        x = d.to_dict() or {}
        x["id"] = d.id
        docs.append(x)
    return docs


def ler_tsi():
    c = _cliente_leitura(PROJETO_TSI, "TSI_CREDENCIAIS")
    return _ler_colecao(c, "lotesTratamento",
                        ["numeroLote", "status", "data", "cultivar", "receitaNome", "lotesDetalhe"])


def ler_rastrel():
    c = _cliente_leitura(PROJETO_RASTREL, "RASTREL_CREDENCIAIS")
    return _ler_colecao(c, "bags",
                        ["lote", "epc", "cultivar_nome", "categoria", "peneira", "peso_kg", "tratamento", "status"])


def provar_somente_leitura():
    """Tenta UMA escrita impossível em cada módulo: atualizar um documento que
    não existe, numa coleção que não existe, com pré-condição de data de 2000.
    Mesmo que a permissão existisse, nada seria gravado. Esperado: 403."""
    from google.api_core import exceptions as gex
    ok = True
    for nome, projeto, var in (("TSI", PROJETO_TSI, "TSI_CREDENCIAIS"),
                               ("RASTREL", PROJETO_RASTREL, "RASTREL_CREDENCIAIS")):
        if os.environ.get(f"CENTRAL_{nome}", "").lower() != "sim":
            print(f"{nome}: não conectado (pulado)")
            continue
        c = _cliente_leitura(projeto, var)
        ref = c.collection("__central_lotes_prova_somente_leitura").document("nao-existe")
        try:
            ref.update({"x": 1}, option=c.write_option(
                last_update_time=datetime(2000, 1, 1, tzinfo=timezone.utc)))
            print(f"{nome}: ATENÇÃO — escrita não foi recusada por permissão")
            ok = False
        except gex.PermissionDenied:
            print(f"{nome}: escrita RECUSADA (somente leitura confirmado)")
        except (gex.NotFound, gex.FailedPrecondition) as e:
            print(f"{nome}: ATENÇÃO — a credencial tem permissão de escrita ({type(e).__name__}); nada foi gravado")
            ok = False
        # leitura deve funcionar
        list(c.collection("bags" if nome == "RASTREL" else "lotesTratamento").limit(1).stream())
        print(f"{nome}: leitura OK")
    if not ok:
        raise SystemExit(1)


# ---------------------------------------------------------------- gravação (só lots/ no seedmax)

def gravar_lots(docs, simular=False):
    import seedmax_dados as store
    destino = store.conectar()
    col = destino.db.collection("lots")
    atuais = {d.id: (d.to_dict() or {}) for d in col.select(["hash", "presente"]).stream()}
    novos, iguais, ausentes = 0, 0, 0
    batch, n = destino.db.batch(), 0

    def enviar():
        nonlocal batch, n
        if n and not simular:
            batch.commit()
        batch, n = destino.db.batch(), 0

    for lot_id, doc in docs.items():
        if atuais.get(lot_id, {}).get("hash") == doc["hash"] and atuais[lot_id].get("presente", True):
            iguais += 1
            continue
        batch.set(col.document(lot_id), doc)
        n += 1
        novos += 1
        if n >= 400:
            enviar()
    for lot_id, a in atuais.items():
        if lot_id not in docs and a.get("presente", True):
            batch.set(col.document(lot_id), {"presente": False}, merge=True)  # nunca apaga
            n += 1
            ausentes += 1
            if n >= 400:
                enviar()
    enviar()
    return novos, iguais, ausentes


def sincronizar(simular=False):
    import seedmax_dados as store
    carimbo = datetime.now(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M")
    _, dados = store.ler_conjuntos(store.conectar())
    apelidos = montar_apelidos(dados.get("CV_META"))
    q = resumir_qualidade(dados)
    print(f"Qualidade: {len(q)} lotes")

    tsi_on = os.environ.get("CENTRAL_TSI", "").lower() == "sim"
    rastrel_on = os.environ.get("CENTRAL_RASTREL", "").lower() == "sim"
    t, est = ({}, {})
    if tsi_on:
        t, est = resumir_tsi(ler_tsi())
        print(f"TSI: {est['ordens']} ordens, {est['ordensComLote']} com lote → {len(t)} lotes")
    else:
        print("TSI: não conectado")
    r = {}
    if rastrel_on:
        r = resumir_rastrel(ler_rastrel())
        print(f"RASTREL: {sum(x['bags'] for x in r.values())} bags → {len(r)} lotes")
    else:
        print("RASTREL: não conectado")

    docs = consolidar(q, t, r, apelidos, carimbo, tsi_conectado=tsi_on, rastrel_conectado=rastrel_on,
                      nomes=montar_nomes(dados.get("CV_META")))
    cont = {}
    for d in docs.values():
        cont[d["situacao"]] = cont.get(d["situacao"], 0) + 1
    print("Situação:", json.dumps(cont, ensure_ascii=False))
    print("Com correspondência entre módulos:", sum(1 for d in docs.values() if len(d["modulos"]) > 1))
    print("Lotes com divergência:", sum(1 for d in docs.values() if d["divergencias"]))
    novos, iguais, ausentes = gravar_lots(docs, simular=simular)
    print(f"lots/: {novos} gravados, {iguais} sem mudança, {ausentes} marcados presente=false"
          + (" (SIMULAÇÃO — nada gravado)" if simular else ""))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "sincronizar":
        sincronizar(simular="--simular" in sys.argv)
    elif cmd == "provar-somente-leitura":
        provar_somente_leitura()
    else:
        print(__doc__)
        sys.exit(2)
