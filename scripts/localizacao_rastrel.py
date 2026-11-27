"""
SEEDMAX — localização atual (RASTREL) dos lotes do Beneficiamento de Inverno.

Função pura, sem rede e sem gravação: recebe o que o robô da Central de Lotes
JÁ LÊ do RASTREL (credencial federada, somente leitura) e devolve o conjunto
LOCAL_RASTREL_INVERNO, que a tela Inverno › Beneficiamento usa no lugar da
localização digitada na planilha.

Duas fontes do RASTREL (projeto rastreabilidade-a511a):

  1. coleção bags — localizacao_atual de cada bag em estoque:
       status em_estoque (com tag NFC) e aguardando_tag (lote criado sem tag).
       Bag expedido não é posição atual (só conta em "expedidos").
       Identidade: safra + cultura + lote gravados no próprio bag (mesma regra
       montar_id_lote da Central). Bag antigo sem safra é lido como Verão/Soja
       e, portanto, NUNCA casa com um lote do Inverno.

  2. documento mapa/fisico — mapa do Excel + lotes cadastrados direto no mapa
       (sem tag): armazens[armazem][bloco].pilhas[] e fora_do_bloco[armazem][].
       A pilha não tem lotId: casa pelo código do lote e, quando houver, por
       safra, cultura/espécie e cultivar. Se mais de um lote do Inverno
       continuar possível (lote homônimo), a pilha NÃO é usada (aviso).
       Mesma regra do mapa do RASTREL: lote com bag COM TAG em estoque e
       posição no RASTREL → a posição da tag manda e a pilha do Excel desse
       lote é ignorada (evita contar o mesmo bag duas vezes); lote com tag e
       todos os bags com tag já expedidos → a pilha do Excel também é ignorada.

Lote sem nenhuma posição confiável não entra no conjunto → a tela usa a
localização manual da planilha.
"""

import re
import unicodedata

import central_lotes as cl

CONJUNTO = "LOCAL_RASTREL_INVERNO"
STATUS_ATUAL = ("em_estoque", "aguardando_tag")

# espécie lida do Excel pelo mapa (parsePilha → ESP) → culturas do Inverno compatíveis
ESPECIES = {
    "TRIGO": ["Trigo"], "TRIGO MOURISCO": ["Trigo Mourisco"], "CEVADA": ["Cevada"],
    "AVEIA": ["Aveia Branca", "Aveia Preta"], "AVEIA BRANCA": ["Aveia Branca"],
    "AVEIA PRETA": ["Aveia Preta"], "NABO": ["Nabo"], "ERVILHA": ["Ervilha"],
    "ERVILHACA": ["Ervilhaca"],
    # espécies que não são do Inverno: a pilha nunca casa com lote do Inverno
    "SOJA": [], "FEIJAO": [], "MISTURA": [],
}


def _norm(v):
    t = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", " ", t.upper()).strip()


def _posicao(v):
    """Código de posição como o RASTREL compara: maiúsculas, sem espaços."""
    return re.sub(r"\s+", "", str(v or "")).upper()


def _qtd_bags(qtd):
    """'9BB' → 9; '4,5BB' → 4.5; '12/3BB' → 15; sacas ('SC') ou vazio → None."""
    s = str(qtd or "")
    if not s or re.search(r"SC", s, re.I):
        return None
    nums = [float(n.replace(",", ".")) for n in re.findall(r"\d+(?:,\d+)?", s)]
    if not nums:
        return None
    t = sum(nums)
    return int(t) if t == int(t) else round(t, 2)


def _rotulo(armazem, bloco):
    """'A3B12' já diz o armazém; outros blocos (Armazém 2, Garagem) levam o nome."""
    b = str(bloco or "").strip()
    if re.match(r"^A\d+B\d+$", _posicao(b)):
        return _posicao(b)
    return f"{armazem} · {b}" if armazem and b else (b or armazem or "")


def _cultivar_bate(a, b):
    """Mesmo cultivar com grafia diferente: igual, ou um contém o outro como palavras."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return None                      # sem informação: não decide
    if na == nb:
        return True
    return f" {na} " in f" {nb} " or f" {nb} " in f" {na} "


def _culturas_da_pilha(p):
    """Culturas do Inverno compatíveis com a pilha; None = não informada."""
    if p.get("safra") and str(p["safra"]).strip().upper() != cl.SAFRA_INVERNO:
        return []                         # pilha de outra safra
    if p.get("cultura"):
        c = cl.cultura_de_leitura(p["cultura"], cl.SAFRA_INVERNO)
        return [c] if c in cl.CULTURAS_INVERNO else []
    esp = _norm(p.get("especie"))
    if esp:
        return ESPECIES.get(esp, [])
    return None


def indexar_benef(benef_inverno):
    """{lotId: {lote, cultura, cultivar}} dos lotes do BENEF_INVERNO."""
    out = {}
    for c in benef_inverno or []:
        for d in c.get("detail") or []:
            code = cl.codigo_lote(d.get("lote"))
            if not code:
                continue
            cultura = cl.cultura_de_leitura(d.get("cultura") or c.get("cultura"), cl.SAFRA_INVERNO)
            lid = d.get("lotId") or cl.montar_id_lote(cl.SAFRA_INVERNO, cultura, code)
            out[lid] = {"lote": code, "cultura": cultura, "cultivar": d.get("cultivar") or c.get("cultivar")}
    return out


def _pilhas_do_mapa(fisico):
    """Gera (armazem, rotulo_posicao, pilha) de mapa/fisico (blocos e fora do bloco)."""
    f = fisico or {}
    for wh, blocos in sorted((f.get("armazens") or {}).items()):
        for bl in blocos or []:
            for p in (bl or {}).get("pilhas") or []:
                if isinstance(p, dict):
                    yield wh, _rotulo(wh, bl.get("id")), p
    for wh, pilhas in sorted((f.get("fora_do_bloco") or {}).items()):
        for p in pilhas or []:
            if isinstance(p, dict):
                yield wh, _rotulo(wh, p.get("posicao") or "fora do bloco"), p


def resumir(bags, fisico, benef_inverno, codigos_fora_do_inverno=()):
    """Devolve {lotId: {"posicoes": [...], "semPosicao": n, "expedidos": n, "avisos": [...]}}
    só para lotes do BENEF_INVERNO com alguma informação do RASTREL.

    posicoes = [{"posicao", "bags", "fonte"}], fonte ∈ tag · sem_tag · mapa
    (mapa com "qtd" quando a quantidade não é em bags, e "misto" quando a célula
    do Excel tem mais de um lote).
    codigos_fora_do_inverno = códigos de lote que existem em outra safra (Soja):
    pilha sem safra/cultura/cultivar com um desses códigos é ambígua."""
    alvo = indexar_benef(benef_inverno)
    if not alvo:
        return {}
    por_codigo = {}
    for lid, x in alvo.items():
        por_codigo.setdefault(x["lote"], []).append(lid)
    fora = {cl.codigo_lote(c) for c in codigos_fora_do_inverno or ()}

    res = {}

    def item(lid):
        return res.setdefault(lid, {"posicoes": {}, "semPosicao": 0, "expedidos": 0, "avisos": []})

    def somar(lid, posicao, fonte, bags=None, qtd=None, misto=False):
        k = (posicao, fonte)
        p = item(lid)["posicoes"].setdefault(k, {"posicao": posicao, "bags": 0, "fonte": fonte})
        if bags is not None:
            p["bags"] = round(p["bags"] + bags, 2)
        if qtd:
            p["qtd"] = " + ".join(x for x in (p.get("qtd"), qtd) if x)
        if misto:
            p["misto"] = True

    # 1) bags do RASTREL (identidade gravada no bag)
    tag_posicionada, tag_total, tag_estoque = set(), set(), set()
    for b in bags or []:
        code = cl.codigo_lote(b.get("lote"))
        if not code:
            continue
        safra = cl.safra_de_leitura(b.get("safra"))
        lid = cl.montar_id_lote(safra, cl.cultura_de_leitura(b.get("cultura"), safra), code)
        if lid not in alvo:
            continue
        st = str(b.get("status") or "").strip()
        if b.get("epc"):
            tag_total.add(lid)
            if st == "em_estoque":
                tag_estoque.add(lid)
        if st == "expedido":
            item(lid)["expedidos"] += 1
            continue
        if st not in STATUS_ATUAL:
            continue                                  # perdido, transformado etc.: não é posição atual
        pos = _posicao(b.get("localizacao_atual"))
        if not pos or pos in ("ARMAZÉM", "ARMAZEM"):
            item(lid)["semPosicao"] += 1
            continue
        com_tag = bool(b.get("epc")) and st == "em_estoque"
        somar(lid, pos, "tag" if com_tag else "sem_tag", bags=1)
        if com_tag:
            tag_posicionada.add(lid)

    # 2) mapa/fisico (pilhas sem lotId)
    for wh, pos, p in _pilhas_do_mapa(fisico):
        lotes = [cl.codigo_lote(x) for x in (p.get("lotes") or [p.get("lote")])]
        lotes = [x for x in dict.fromkeys(lotes) if x]
        culturas = _culturas_da_pilha(p)
        for code in lotes:
            cands = list(por_codigo.get(code, []))
            if not cands:
                continue
            if culturas is not None:
                cands = [l for l in cands if alvo[l]["cultura"] in culturas]
            if len(cands) > 1 or (culturas is None and len(cands) == 1):
                bate = [l for l in cands if _cultivar_bate(p.get("cultivar"), alvo[l]["cultivar"])]
                nada = all(_cultivar_bate(p.get("cultivar"), alvo[l]["cultivar"]) is None for l in cands)
                if not nada:
                    cands = bate
            if not cands:
                continue
            onde = f"{pos} ({p.get('qtd') or 's/ qtd'})"
            if len(cands) > 1:
                for l in cands:
                    item(l)["avisos"].append(f"Mapa: lote {code} em {onde} sem cultura/cultivar que "
                                             "identifique o lote (homônimo) — não vinculado")
                continue
            lid = cands[0]
            sem_ident = culturas is None and _cultivar_bate(p.get("cultivar"), alvo[lid]["cultivar"]) is None
            if sem_ident and code in fora:
                item(lid)["avisos"].append(f"Mapa: lote {code} em {onde} sem safra/cultura/cultivar e o "
                                           "mesmo código existe em outra safra — não vinculado")
                continue
            if lid in tag_posicionada:
                continue                              # posição da tag manda (regra do mapa do RASTREL)
            if lid in tag_total and lid not in tag_estoque:
                continue                              # bags com tag já expedidos: a pilha do Excel é antiga
            n = _qtd_bags(p.get("qtd")) if len(lotes) == 1 else None
            somar(lid, pos, "mapa", bags=n, qtd=None if n is not None else (p.get("qtd") or None),
                  misto=len(lotes) > 1)

    out = {}
    for lid in sorted(res):
        r = res[lid]
        posicoes = sorted(r["posicoes"].values(), key=lambda x: (-(x["bags"] or 0), x["posicao"], x["fonte"]))
        for x in posicoes:
            if not x["bags"] and (x.get("qtd") or x.get("misto")):
                x.pop("bags")
        if not posicoes and not r["expedidos"] and not r["semPosicao"] and not r["avisos"]:
            continue
        e = {"posicoes": posicoes}
        for k in ("semPosicao", "expedidos"):
            if r[k]:
                e[k] = r[k]
        if r["avisos"]:
            e["avisos"] = sorted(set(r["avisos"]))
        out[lid] = e
    return out


def codigos_de_outras_safras(dados, bags=()):
    """Códigos de lote do Verão (Qualidade e bags do RASTREL lidos como Soja)."""
    cods = set()
    for nome in ("LOTS", "LOTES_COMPRADOS", "NOSSO_PLANTIO", "BENEF"):
        for x in dados.get(nome) or []:
            if isinstance(x, dict):
                for k in ("lote", "lote_origem"):
                    if x.get(k):
                        cods.add(cl.codigo_lote(x[k]))
    for b in bags or []:
        if cl.safra_de_leitura(b.get("safra")) != cl.SAFRA_INVERNO and b.get("lote"):
            cods.add(cl.codigo_lote(b["lote"]))
    cods.discard("")
    return cods
