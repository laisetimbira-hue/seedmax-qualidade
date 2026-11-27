import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import benef_inverno as bi


def linha(aba, lote, numero=3):
    return {
        "aba": aba,
        "linha": numero,
        "cultivar": "IMPACTA",
        "cultura_planilha": "Aveia Branca",
        "safra": "26/26",
        "categoria": "S2",
        "lote": lote,
        "peneira": "S/P",
        "embalagem": "BB600",
        "bags": 20,
        "peso_bag": 600,
        "total_kg": 12000,
        "localizacao": "UBS",
        "observacoes": None,
    }


def detalhes(linhas):
    dados, conflitos, _ = bi.consolidar(linhas)
    assert not conflitos, conflitos
    return {d["lote"]: d for c in dados for d in c["detail"]}


def test_tres_origens_separadas():
    lotes = detalhes([
        linha("INVERNO 2026", "PROP001"),
        linha("PGW", "PGW001"),
        linha("AMBEV", "AMB001"),
    ])

    assert len(lotes) == 3
    assert "empresa" not in lotes["PROP001"]
    assert lotes["PGW001"]["empresa"] == "PGW"
    assert lotes["AMB001"]["empresa"] == "AMBEV"


def test_codigo_igual_entre_empresas_bloqueado():
    dados, conflitos, _ = bi.consolidar([
        linha("PGW", "IGUAL001"),
        linha("AMBEV", "IGUAL001"),
    ])

    assert dados == []
    assert any(c["tipo"] == "empresa_divergente" for c in conflitos)


def test_totais_preservados():
    dados, conflitos, _ = bi.consolidar([
        linha("INVERNO 2026", "PROP001"),
        linha("PGW", "PGW001"),
        linha("AMBEV", "AMB001"),
    ])

    assert not conflitos
    assert bi.totais(dados)["kg"] == 36000
    assert bi.totais(dados)["bags"] == 60


# ------------------------------------------------------------ leitura das abas PGW e AMBEV no Excel

CAB = ["DATA", "CULTIVAR", "SAFRA", "CAT.", "LOTE", "PEN.", "EMBALAGEM", "N° BB", "PESO",
       "Total", "Localização", "Observações "]


def _aba(wb, titulo, cultivar_titulo, linhas, visivel=True):
    ws = wb.create_sheet(titulo)
    ws.append([cultivar_titulo]); ws.merge_cells("A1:L1")
    ws.append(CAB)
    for cv, lote, bags in linhas:
        ws.append([None, cv, "26/26", "S2", lote, "S/P", "BB600", bags, 600, bags * 600, "UBS", None])
    ws.append([None, None, None, None, None, None, "N° BAGS ", sum(b for *_, b in linhas), "FINALIZADO", None, None, None])
    if not visivel:
        ws.sheet_state = "hidden"


def test_leitura_das_abas_pgw_e_ambev(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    _aba(wb, "INVERNO 2026", "AVEIA BRANCA - CVPROP", [("CVPROP", "PR01", 20), ("CVPROP", "PR02", 10)])
    _aba(wb, "PGW", "AVEIA BRANCA - CVPGW", [("CVPGW", "PG01", 15)])
    _aba(wb, "AMBEV", "CEVADA - CVAMB", [("CVAMB", "AM01", 8), ("CVAMB", "AM02", 4)])
    _aba(wb, "AMBEV ANTIGA", "CEVADA - CVAMB", [("CVAMB", "OCULTO1", 99)], visivel=False)
    arq = tmp_path / "benef.xlsx"
    wb.save(arq)

    linhas, avisos = bi.ler_planilha(arq)
    assert avisos == []
    assert sorted({l["aba"] for l in linhas}) == ["AMBEV", "INVERNO 2026", "PGW"]   # aba oculta ignorada

    dados, conflitos, _ = bi.consolidar(linhas)
    assert not conflitos, conflitos
    por_empresa = {}
    for c in dados:
        for d in c["detail"]:
            e = d.get("empresa", "PROPRIA")
            t = por_empresa.setdefault(e, {"lotes": 0, "bags": 0, "kg": 0})
            t["lotes"] += 1; t["bags"] += d["bags"]; t["kg"] += d["kg"]
    assert por_empresa == {
        "PROPRIA": {"lotes": 2, "bags": 30, "kg": 18000},
        "PGW": {"lotes": 1, "bags": 15, "kg": 9000},
        "AMBEV": {"lotes": 2, "bags": 12, "kg": 7200},
    }
    # o total geral continua sendo a soma das três origens (nada some, nada duplica)
    assert bi.totais(dados)["kg"] == 18000 + 9000 + 7200
