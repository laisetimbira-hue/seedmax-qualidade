"""
SEEDMAX — leitura da planilha "LOTES BENEFICIADOS INVERNO 26-26.xlsx".

Só interpreta a planilha e devolve o conjunto BENEF_INVERNO (lista de
cultivares, cada um com os seus lotes). Não grava nada: quem grava é o
sincronizador (scripts/sincronizar_benef_inverno.py).

Estrutura esperada (a mesma em todas as abas, ex.: "INVERNO 2026", "PGW"):

  DATA | CULTIVAR | SAFRA | CAT. | LOTE | PEN. | EMBALAGEM | N° BB | PESO |
  Total | Localização | Observações

As colunas são achadas pelo texto do cabeçalho (não pela posição), porque
na planilha de verão as colunas já mudaram de lugar várias vezes sem aviso.
Linhas de totalização ("N° BAGS / FINALIZADO" etc.) não são lotes e são
ignoradas: uma linha só vira lote se tiver CULTIVAR, LOTE e N° BB > 0.

Formato de cada item de BENEF_INVERNO:

  {"cultivar": "PGA0155", "cultura": "Trigo" | None,
   "bags_total": 188, "kg_total": 112800, "lotes": 10,
   "localizacoes": ["UBS SCV"], "abas": ["INVERNO 2026"],
   "detail": [{"lote", "lotId", "data", "safra", "categoria", "peneira",
               "embalagem", "bags", "peso_bag", "kg", "localizacao",
               "observacoes", "aba", "linha"}]}

"cultura" vem do cadastro CV_META_INVERNO (pelo cultivar). Se o cultivar
não estiver cadastrado, usa a cultura escrita na própria planilha, quando
houver (ex.: "AVEIA BRANCA / IMPACTA"); senão fica None.
"""

import re
import unicodedata
from collections import OrderedDict
from datetime import date, datetime

import openpyxl

SAFRA_INVERNO = "INV2626"

# rótulo normalizado do cabeçalho -> campo
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

# Culturas conhecidas do Inverno (mesmos nomes do CV_META_INVERNO). Servem
# só para reconhecer a cultura quando ela vem escrita junto do cultivar,
# como em "AVEIA BRANCA / IMPACTA".
CULTURAS = ["Trigo Mourisco", "Trigo", "Aveia Branca", "Aveia Preta", "Cevada",
            "Nabo", "Ervilhaca", "Ervilha", "Centeio", "Azevém", "Triticale"]


def _norm(txt):
    """Maiúsculas, sem acento, sem pontuação, espaços simples."""
    t = unicodedata.normalize("NFKD", str(txt or "")).encode("ascii", "ignore").decode()
    t = re.sub(r"[^A-Za-z0-9]+", " ", t).strip().upper()
    return t


def _num(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s or s.startswith("="):
        return None
    s = re.sub(r"[^0-9,.\-]", "", s)
    if s.count(",") == 1 and s.count(".") >= 1:      # 1.234,5
        s = s.replace(".", "").replace(",", ".")
    elif s.count(",") == 1:                           # 600,5
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


def _int_ou_float(x):
    if x is None:
        return None
    return int(round(x)) if abs(x - round(x)) < 1e-6 else round(x, 2)


def montar_lot_id(cultura, lote):
    """Mesma regra única da Central de Lotes / TSI / RASTREL:
    INV2626_<CULTURA>_<LOTE> (sem cultura → INV2626_SEMCULTURA_<LOTE>)."""
    import central_lotes  # só biblioteca padrão; não conecta em nada
    return central_lotes.montar_id_lote(SAFRA_INVERNO, cultura or "", lote)


def separar_cultura(cultivar_txt):
    """'AVEIA BRANCA / IMPACTA' -> ('Aveia Branca', 'IMPACTA').
    Sem cultura reconhecida, devolve (None, texto original)."""
    s = _txt(cultivar_txt) or ""
    n = _norm(s)
    for cult in CULTURAS:
        cn = _norm(cult)
        if n == cn:
            return cult, s
        if n.startswith(cn + " "):
            resto = re.split(r"\s*[/\-–|:]\s*", s, maxsplit=1)
            cv = resto[1].strip() if len(resto) == 2 and resto[1].strip() else s[len(cult):].strip(" /-–|:")
            return cult, (cv or s)
    return None, s


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


def ler_planilha(caminho_ou_buf):
    """Lê todas as abas e devolve (linhas, avisos). Cada linha é um lote."""
    wb = openpyxl.load_workbook(caminho_ou_buf, data_only=True, read_only=False)
    linhas, avisos = [], []
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        achado = _achar_cabecalho(ws)
        if achado is None:
            avisos.append(f"aba '{ws.title}': cabeçalho (CULTIVAR / LOTE / N° BB) não encontrado — ignorada")
            continue
        r_cab, cols = achado
        # título da aba (linhas acima do cabeçalho), ex.: "AVEIA BRANCA - IMPACTA"
        titulo = " ".join(_txt(ws.cell(r, c).value) or "" for r in range(1, r_cab)
                          for c in range(1, ws.max_column + 1)).strip()
        cultura_titulo, cv_titulo = separar_cultura(titulo) if titulo else (None, None)
        ultimo_cultivar = None
        for r in range(r_cab + 1, ws.max_row + 1):
            g = lambda campo: ws.cell(r, cols[campo]).value if campo in cols else None
            cv_raw, lote, bags = _txt(g("cultivar")), _txt(g("lote")), _num(g("bags"))
            if not lote or not bags or bags <= 0:
                continue                      # vazio, totalização, rodapé
            if _norm(lote) in ("LOTE", "TOTAL", "FINALIZADO") or "BAGS" in _norm(lote):
                continue
            if not cv_raw:
                # célula de cultivar mesclada/repetida só na primeira linha
                cv_raw = ultimo_cultivar
                if not cv_raw:
                    avisos.append(f"aba '{ws.title}' linha {r}: lote {lote} sem cultivar — ignorado")
                    continue
            ultimo_cultivar = cv_raw
            if _norm(cv_raw) in ("CULTIVAR", "TOTAL") or "FINALIZADO" in _norm(cv_raw):
                continue

            cultura_planilha, cultivar = separar_cultura(cv_raw)
            if not cultura_planilha and cultura_titulo and _norm(cultivar) in _norm(cv_titulo or ""):
                cultura_planilha = cultura_titulo
            peso = _num(g("peso"))
            total = _num(g("total"))
            kg = total if total and total > 0 else (bags * peso if peso else None)
            if total and peso and abs(total - bags * peso) > 0.5:
                avisos.append(f"aba '{ws.title}' linha {r}: lote {lote} — Total ({total:g}) "
                              f"diferente de N° BB × PESO ({bags:g} × {peso:g}); usado o Total da planilha")
            if kg is None:
                avisos.append(f"aba '{ws.title}' linha {r}: lote {lote} sem PESO/Total — volume 0")
            linhas.append({
                "aba": ws.title, "linha": r,
                "cultivar": cultivar, "cultura_planilha": cultura_planilha,
                "data": _data(g("data")), "safra": _txt(g("safra")),
                "categoria": _txt(g("categoria")), "lote": lote,
                "peneira": _txt(g("peneira")), "embalagem": _txt(g("embalagem")),
                "bags": _int_ou_float(bags), "peso_bag": _int_ou_float(peso),
                "kg": _int_ou_float(kg or 0),
                "localizacao": _txt(g("localizacao")), "observacoes": _txt(g("observacoes")),
            })
    return linhas, avisos


def _cultura_cadastrada(cultivar, cv_meta):
    if not cv_meta:
        return None
    m = cv_meta.get(cultivar)
    if m is None:
        alvo = _norm(cultivar)
        m = next((v for k, v in cv_meta.items() if _norm(k) == alvo), None)
    return (m or {}).get("cultura") or None


def montar_benef_inverno(linhas, cv_meta_inverno=None):
    """Agrupa os lotes por cultivar no formato BENEF_INVERNO."""
    grupos = OrderedDict()
    for l in linhas:
        g = grupos.setdefault(l["cultivar"], {"cultivar": l["cultivar"], "culturas_planilha": [], "detail": []})
        if l["cultura_planilha"] and l["cultura_planilha"] not in g["culturas_planilha"]:
            g["culturas_planilha"].append(l["cultura_planilha"])
        g["detail"].append(l)

    saida = []
    for cv, g in grupos.items():
        cultura = _cultura_cadastrada(cv, cv_meta_inverno) or (g["culturas_planilha"][0] if g["culturas_planilha"] else None)
        detail = []
        for l in g["detail"]:
            d = {k: l[k] for k in ("lote", "data", "safra", "categoria", "peneira", "embalagem",
                                   "bags", "peso_bag", "kg", "localizacao", "observacoes", "aba", "linha")}
            d["lotId"] = montar_lot_id(cultura, l["lote"])
            detail.append(d)
        locs = list(OrderedDict.fromkeys(d["localizacao"] for d in detail if d["localizacao"]))
        abas = list(OrderedDict.fromkeys(d["aba"] for d in detail))
        saida.append({
            "cultivar": cv,
            "cultura": cultura,
            "bags_total": _int_ou_float(sum(d["bags"] for d in detail)),
            "kg_total": _int_ou_float(sum(d["kg"] or 0 for d in detail)),
            "lotes": len({d["lote"] for d in detail}),
            "localizacoes": locs,
            "abas": abas,
            "detail": detail,
        })
    return saida


def totais(benef):
    return {
        "cultivares": len(benef),
        "lotes": sum(c["lotes"] for c in benef),
        "bags": _int_ou_float(sum(c["bags_total"] for c in benef)),
        "kg": _int_ou_float(sum(c["kg_total"] for c in benef)),
    }


def ler(caminho_ou_buf, cv_meta_inverno=None):
    """Atalho: planilha -> (BENEF_INVERNO, avisos)."""
    linhas, avisos = ler_planilha(caminho_ou_buf)
    return montar_benef_inverno(linhas, cv_meta_inverno), avisos
