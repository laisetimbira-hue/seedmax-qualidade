"""
SEEDMAX — Beneficiamento de Inverno: leitura da planilha e consolidação.

Duas etapas, ambas sem gravar nada:

  1. ler_planilha(arquivo) -> linhas brutas (uma por linha de lote do Excel)
  2. consolidar(linhas, culturas) -> (BENEF_INVERNO, conflitos, avisos)

A MESMA consolidação existe em JavaScript na função segura da ponte
(ponte/benef-inverno.js), que é quem decide de verdade antes de gravar. Os
dois lados são conferidos pelos mesmos casos em tests/casos_benef_inverno.json.

IDENTIDADE DO LOTE (regra única do SEEDMAX): Safra + Cultura + Lote,
INV2626_<CULTURA>_<LOTE> — central_lotes.montar_id_lote. O beneficiamento é
informação VINCULADA a esse lote; nunca cria identidade nova.

  * mesma cultura + mesmo lote = o mesmo lote (uma entrada só);
  * mesmo número de lote em culturas diferentes = lotes diferentes;
  * linha 100% idêntica repetida = possível lançamento em dobro: CONFLITO
    (a sincronização para e aponta o lote e as linhas);
  * linhas do mesmo lote com cultivar, categoria, peneira, embalagem e peso
    por bag iguais, mas quantidades diferentes = continuação do lote: soma
    bags e kg, na ordem aba/linha (determinístico);
  * cultivar, categoria, peneira, embalagem ou peso por bag diferentes entre
    linhas do mesmo lote, Total ≠ N° BB × PESO, ou cultura desconhecida =
    CONFLITO: a sincronização para e nada é publicado.

Planilha: todas as abas visíveis; colunas achadas pelo texto do cabeçalho
(DATA, CULTIVAR, SAFRA, CAT., LOTE, PEN., EMBALAGEM, N° BB, PESO, Total,
Localização, Observações). Linhas de totalização ("N° BAGS / FINALIZADO")
não são lotes: só conta a linha com LOTE e N° BB > 0.
"""

import re
import unicodedata
from collections import OrderedDict
from datetime import date, datetime

import central_lotes  # só biblioteca padrão; aqui só para a regra do lotId

SAFRA_INVERNO = central_lotes.SAFRA_INVERNO      # "INV2626"
FORMATO = 1
TOLERANCIA_KG = 0.5

CABECALHOS = {
    "data": ["DATA"],
    "cultivar": ["CULTIVAR"],
    "safra": ["SAFRA"],
    "categoria": ["CAT", "CATEGORIA"],
    "lote": ["LOTE"],
    "peneira": ["PEN", "PENEIRA"],
    "embalagem": ["EMBALAGEM", "EMB"],
    "bags": ["N BB", "NO BB", "N BAGS", "QUANT BB", "QUANTIDADE", "BB"],
    "peso": ["PESO", "PESO BB", "PESO BAG"],
    "total": ["TOTAL", "TOTAL KG", "PESO TOTAL"],
    "localizacao": ["LOCALIZACAO", "LOCAL", "UBS"],
    "observacoes": ["OBSERVACOES", "OBSERVACAO", "OBS"],
}
OBRIGATORIOS = ("cultivar", "lote", "bags")

# culturas do Inverno (mesmos nomes do CV_META_INVERNO), para reconhecer a
# cultura escrita junto do cultivar, ex.: "AVEIA BRANCA - CULTIVAR X"
CULTURAS = ["Trigo Mourisco", "Trigo", "Aveia Branca", "Aveia Preta", "Cevada",
            "Nabo", "Ervilhaca", "Ervilha", "Centeio", "Azevém", "Triticale"]

# campos que precisam ser iguais em todas as linhas do mesmo lote
CAMPOS_DO_LOTE = ("cultivar", "categoria", "peneira", "embalagem", "peso_bag")
# campos que, todos iguais, indicam linha repetida (conflito: possível lançamento em dobro)
CAMPOS_DA_LINHA = ("cultivar", "categoria", "peneira", "embalagem", "bags", "peso_bag",
                   "kg", "localizacao", "observacoes", "data", "safra")


# ---------------------------------------------------------------- utilitários

def _norm(txt):
    t = unicodedata.normalize("NFKD", str(txt or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", " ", t).strip().upper()


def _cmp(v):
    """Valor para comparar: texto normalizado (sem acento/caixa/espaço extra)."""
    return _norm(v) if isinstance(v, str) else v


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s or s.startswith("="):
        return None
    s = re.sub(r"[^0-9,.\-]", "", s)
    if s.count(",") == 1 and s.count(".") >= 1:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(",") == 1:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _txt(v):
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def _data(v):
    if isinstance(v, (datetime, date)):
        return v.strftime("%d/%m/%Y")
    return _txt(v)


def _n(x):
    """Número limpo: inteiro quando for inteiro."""
    if x is None:
        return None
    return int(round(x)) if abs(x - round(x)) < 1e-6 else round(x, 2)


def separar_cultura(texto):
    """'AVEIA BRANCA - CULTIVAR X' -> ("Aveia Branca", "CULTIVAR X")."""
    s = _txt(texto) or ""
    n = _norm(s)
    for cult in CULTURAS:
        cn = _norm(cult)
        if n == cn:
            return cult, s
        if n.startswith(cn + " "):
            partes = re.split(r"\s*[/\-–|:]\s*", s, maxsplit=1)
            cv = partes[1].strip() if len(partes) == 2 and partes[1].strip() else s[len(cult):].strip(" /-–|:")
            return cult, (cv or s)
    return None, s


def montar_lot_id(cultura, lote):
    return central_lotes.montar_id_lote(SAFRA_INVERNO, cultura or "", lote)


# ---------------------------------------------------------------- 1. planilha

def _achar_cabecalho(ws, max_linhas=15):
    for r in range(1, min(ws.max_row, max_linhas) + 1):
        valores = {}
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str) and v.strip():
                valores.setdefault(_norm(v), c)
        if "CULTIVAR" not in valores or "LOTE" not in valores:
            continue
        cols = {}
        for campo, rotulos in CABECALHOS.items():
            for rot in rotulos:
                if rot in valores:
                    cols[campo] = valores[rot]
                    break
        if all(k in cols for k in OBRIGATORIOS):
            return r, cols
    return None


def ler_planilha(arquivo):
    """Devolve (linhas, avisos). Cada linha = uma linha de lote do Excel,
    sem consolidar nada (é isto que vai para a função segura)."""
    import openpyxl
    wb = openpyxl.load_workbook(arquivo, data_only=True)
    linhas, avisos = [], []
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        achado = _achar_cabecalho(ws)
        if achado is None:
            avisos.append(f"aba '{ws.title}': cabeçalho (CULTIVAR / LOTE / N° BB) não encontrado — ignorada")
            continue
        r_cab, cols = achado
        titulo = " ".join(_txt(ws.cell(r, c).value) or "" for r in range(1, r_cab)
                          for c in range(1, ws.max_column + 1)).strip()
        cultura_titulo, cv_titulo = separar_cultura(titulo) if titulo else (None, None)
        ultimo_cv = None
        for r in range(r_cab + 1, ws.max_row + 1):
            g = lambda campo: ws.cell(r, cols[campo]).value if campo in cols else None
            lote, bags = _txt(g("lote")), _num(g("bags"))
            if not lote or not bags or bags <= 0:
                continue                                  # vazio, totalização, rodapé
            if _norm(lote) in ("LOTE", "TOTAL", "FINALIZADO") or "BAGS" in _norm(lote):
                continue
            cv_raw = _txt(g("cultivar")) or ultimo_cv     # célula mesclada/repetida
            if not cv_raw:
                avisos.append(f"aba '{ws.title}' linha {r}: lote {lote} sem cultivar — ignorado")
                continue
            ultimo_cv = cv_raw
            cultura_planilha, cultivar = separar_cultura(cv_raw)
            if not cultura_planilha and cultura_titulo and _norm(cultivar) in _norm(cv_titulo or ""):
                cultura_planilha = cultura_titulo
            linhas.append({
                "aba": ws.title, "linha": r,
                "cultivar": cultivar, "cultura_planilha": cultura_planilha,
                "data": _data(g("data")), "safra": _txt(g("safra")),
                "categoria": _txt(g("categoria")), "lote": lote,
                "peneira": _txt(g("peneira")), "embalagem": _txt(g("embalagem")),
                "bags": _n(bags), "peso_bag": _n(_num(g("peso"))), "total_kg": _n(_num(g("total"))),
                "localizacao": _txt(g("localizacao")), "observacoes": _txt(g("observacoes")),
            })
    return linhas, avisos


# ---------------------------------------------------------------- 2. consolidação

def cultura_do_cultivar(cultivar, culturas):
    """Cultura pelo cadastro CV_META_INVERNO ({cultivar: {cultura}} ou {cultivar: cultura})."""
    if not culturas:
        return None
    alvo = _norm(cultivar)
    for k in sorted(culturas):
        if _norm(k) == alvo:
            v = culturas[k]
            return (v.get("cultura") if isinstance(v, dict) else v) or None
    return None


def _kg_da_linha(l):
    """(kg, problema). Total da planilha; se vazio, N° BB × PESO."""
    bags, peso, total = l.get("bags"), l.get("peso_bag"), l.get("total_kg")
    if total is not None and peso is not None and abs(total - bags * peso) > TOLERANCIA_KG:
        return None, f"Total {_n(total)} kg diferente de N° BB × PESO ({_n(bags)} × {_n(peso)} = {_n(bags * peso)} kg)"
    if total is not None:
        return total, None
    if peso is not None:
        return bags * peso, None
    return None, "sem PESO e sem Total"


def _onde(l):
    return f"aba '{l.get('aba')}' linha {l.get('linha')}"


def consolidar(linhas, culturas=None):
    """Linhas brutas -> (BENEF_INVERNO, conflitos, avisos).
    Com qualquer conflito, BENEF_INVERNO volta vazio e NÃO deve ser publicado."""
    conflitos, avisos = [], []
    pos_aba = {}
    for l in linhas:
        pos_aba.setdefault(l.get("aba"), len(pos_aba))
    ordem = sorted(range(len(linhas)),
                   key=lambda i: (pos_aba[linhas[i].get("aba")], int(linhas[i].get("linha") or 0), i))

    grupos = OrderedDict()                                  # lotId -> [linhas]
    for i in ordem:
        l = dict(linhas[i])
        codigo = central_lotes.codigo_lote(l.get("lote"))
        if not codigo:
            conflitos.append({"tipo": "lote_invalido", "lote": l.get("lote"), "onde": [_onde(l)],
                              "texto": "código de lote vazio ou inválido"})
            continue
        cultura = cultura_do_cultivar(l.get("cultivar"), culturas) or l.get("cultura_planilha")
        if not cultura:
            conflitos.append({"tipo": "sem_cultura", "lote": codigo, "onde": [_onde(l)],
                              "texto": f"cultivar {l.get('cultivar')} sem cultura no CV_META_INVERNO nem na "
                                       "planilha — não dá para montar a identidade do lote"})
            continue
        kg, problema = _kg_da_linha(l)
        if problema:
            conflitos.append({"tipo": "quantidade_incompativel", "lote": codigo, "onde": [_onde(l)],
                              "texto": problema})
            continue
        l.update(cultura=cultura, kg=_n(kg), codigo=codigo, lotId=montar_lot_id(cultura, codigo))
        grupos.setdefault(l["lotId"], []).append(l)

    lotes = []
    for lot_id, ls in grupos.items():

        # A empresa vem da aba de origem, sem modificar o Excel.
        def empresa_da_linha(l):
            aba = str(l.get("aba") or "").strip().upper()
            if aba in ("PGW", "AMBEV"):
                return aba
            return "PROPRIA"

        empresas = {empresa_da_linha(l) for l in ls}
        if len(empresas) > 1:
            conflitos.append({
                "tipo": "empresa_divergente",
                "lote": ls[0]["codigo"],
                "lotId": lot_id,
                "onde": [_onde(l) for l in ls],
                "texto": "Mesmo lote em empresas diferentes: "
                         + ", ".join(sorted(empresas))
            })
            continue
        empresa = next(iter(empresas))
        # (1) linha 100% idêntica repetida = possível duplicação: CONFLITO
        #     (não soma nem ignora — pede conferência da planilha)
        unicas, vistas = [], {}
        duplicada = False
        for l in ls:
            chave = tuple(_cmp(l.get(c)) for c in CAMPOS_DA_LINHA)
            if chave in vistas:
                duplicada = True
                conflitos.append({
                    "tipo": "linha_duplicada", "lote": l["codigo"], "lotId": lot_id,
                    "onde": [_onde(vistas[chave]), _onde(l)],
                    "texto": "linha completamente idêntica repetida (possível lançamento em dobro) — "
                             "confira a planilha: apague a repetida ou, se for outro carregamento, "
                             "diferencie a linha"})
                continue
            vistas[chave] = l
            unicas.append(l)
        if duplicada:
            continue
        # (2) dados do lote precisam ser os mesmos em todas as linhas
        conflito = False
        for campo in CAMPOS_DO_LOTE:
            vals = OrderedDict()
            for l in unicas:
                vals.setdefault(_cmp(l.get(campo)), (l.get(campo), []))[1].append(_onde(l))
            if len(vals) > 1:
                conflito = True
                conflitos.append({
                    "tipo": f"{campo}_divergente", "lote": unicas[0]["codigo"], "lotId": lot_id,
                    "onde": [o for _, os_ in vals.values() for o in os_],
                    "texto": f"{campo} diferente entre linhas do mesmo lote: "
                             + " × ".join(str(v) for v, _ in vals.values())})
        if conflito:
            continue
        # (3) continuação do mesmo lote: soma, na ordem aba/linha
        b = unicas[0]
        if len(unicas) > 1:
            avisos.append(f"lote {b['codigo']}: {len(unicas)} linhas do mesmo lote somadas "
                          f"({', '.join(_onde(l) for l in unicas)})")

        def juntar(campo):
            return " · ".join(OrderedDict.fromkeys(l[campo] for l in unicas if l.get(campo))) or None

        lotes.append({
            "lotId": lot_id, "lote": b["codigo"], "cultivar": b["cultivar"], "cultura": b["cultura"],
            "data": juntar("data"), "safra": juntar("safra"), "categoria": b.get("categoria"),
            "peneira": b.get("peneira"), "embalagem": b.get("embalagem"),
            "bags": _n(sum(l["bags"] for l in unicas)), "peso_bag": b.get("peso_bag"),
            "kg": _n(sum(l["kg"] for l in unicas)),
            "localizacao": juntar("localizacao"), "observacoes": juntar("observacoes"),
            "linhas": [{"aba": l.get("aba"), "linha": l.get("linha")} for l in unicas],
        })
        if empresa != "PROPRIA":
            lotes[-1]["empresa"] = empresa

    if conflitos:
        return [], conflitos, avisos

    # (4) agrupa por cultivar, na ordem em que aparecem
    por_cv = OrderedDict()
    for d in lotes:
        por_cv.setdefault((d["cultivar"], d["cultura"]), []).append(d)
    benef = []
    for (cv, cultura), ds in por_cv.items():
        benef.append({
            "cultivar": cv,
            "cultura": cultura,
            "bags_total": _n(sum(d["bags"] for d in ds)),
            "kg_total": _n(sum(d["kg"] for d in ds)),
            "lotes": len(ds),
            "localizacoes": list(OrderedDict.fromkeys(d["localizacao"] for d in ds if d["localizacao"])),
            "abas": list(OrderedDict.fromkeys(x["aba"] for d in ds for x in d["linhas"])),
            "detail": ds,
        })
    return benef, [], avisos


def totais(benef):
    return {
        "cultivares": len(benef),
        "lotes": sum(c["lotes"] for c in benef),
        "bags": _n(sum(c["bags_total"] for c in benef)),
        "kg": _n(sum(c["kg_total"] for c in benef)),
    }


def ler(arquivo, culturas=None):
    """Atalho: planilha -> (BENEF_INVERNO, conflitos, avisos)."""
    linhas, avisos = ler_planilha(arquivo)
    benef, conflitos, av2 = consolidar(linhas, culturas)
    return benef, conflitos, avisos + av2
