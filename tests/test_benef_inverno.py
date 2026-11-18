"""Beneficiamento de Inverno: leitura da planilha + sincronizador.

A planilha usada aqui é FICTÍCIA (montada no próprio teste, com a mesma
estrutura da real). A planilha da empresa nunca entra no repositório.

Rodar: python -m pytest tests/test_benef_inverno.py -q
"""
import json
import os
import pathlib
import sys

import openpyxl
import pytest

AQUI = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "scripts"))

import benef_inverno as bi  # noqa: E402

CAB = ["DATA", "CULTIVAR", "SAFRA", "CAT.", "LOTE", "PEN.", "EMBALAGEM", "N° BB", "PESO",
       "Total", "Localização", "Observações "]


def planilha(caminho):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "INVERNO 2026"
    ws.append(["CVTESTE1"]); ws.merge_cells("A1:L1")
    ws.append(CAB)
    for i in range(1, 4):
        ws.append([None, "CVTESTE1", "26/26", "S2", f"99XX0{i}", "S/P", "BB600", 20, 600, 12000, "UBS TESTE", None])
    ws.append([None, None, None, None, None, None, "N° BAGS ", 60, "FINALIZADO", 36000, None, None])
    ws2 = wb.create_sheet("PGW")
    ws2.append(["AVEIA BRANCA - CVTESTE2 "]); ws2.merge_cells("A1:L1")
    ws2.append(CAB)
    ws2.append([None, "CVTESTE2", "26/26", "S2", "TST001", "S/P", "BB600", 25, 600, 15000, "UBS TESTE", None])
    ws2.append([None, "CVTESTE2", "26/26", "S2", "TST001A", "S/P", "BB600", 17, 600, 10200, "UBS TESTE", "REPASSE"])
    ws2.append([None, None, None, None, None, None, "N° BAGS ", 42, "FINALIZADO ", 25200, None, None])
    wb.save(caminho)
    return caminho


def test_leitura_e_totais(tmp_path):
    benef, avisos = bi.ler(planilha(tmp_path / "p.xlsx"), {"CVTESTE1": {"cultura": "Trigo"}})
    assert avisos == []
    assert bi.totais(benef) == {"cultivares": 2, "lotes": 5, "bags": 102, "kg": 61200}
    c1, c2 = benef
    assert (c1["cultivar"], c1["cultura"], c1["lotes"], c1["bags_total"]) == ("CVTESTE1", "Trigo", 3, 60)
    # sem cadastro: cultura vem do título da aba ("AVEIA BRANCA - ...")
    assert (c2["cultivar"], c2["cultura"]) == ("CVTESTE2", "Aveia Branca")
    assert c2["detail"][1]["observacoes"] == "REPASSE"
    assert c2["detail"][1]["peneira"] == "S/P"            # não vira P1/P2
    assert c2["detail"][0]["lotId"] == "INV2626_AVEIA_BRANCA_TST001"
    assert c1["localizacoes"] == ["UBS TESTE"]
    # linha "N° BAGS / FINALIZADO" não é lote
    assert all(d["lote"] for c in benef for d in c["detail"])


def test_cadastro_tem_prioridade_sobre_planilha(tmp_path):
    benef, _ = bi.ler(planilha(tmp_path / "p.xlsx"), {"CVTESTE2": {"cultura": "Aveia Preta"}})
    assert benef[1]["cultura"] == "Aveia Preta"


def _semear(pasta):
    os.environ["SEEDMAX_DESTINO"] = f"pasta:{pasta}"
    import seedmax_dados as s
    s.publicar(s.conectar(), {
        "LOTS_INVERNO": [{"lote": "A1"}], "LOTS": [1, 2], "TZ_DATA": {"x": 1},
        "CV_META_INVERNO": {"CVTESTE1": {"cultura": "Trigo"}}, "BENEF_INVERNO": [],
    }, "inicial", meta_atual={})
    return s


def test_sincronizador_so_grava_benef_inverno(tmp_path, monkeypatch):
    banco = tmp_path / "banco"
    _semear(banco)
    antes = {p.name: p.read_text() for p in banco.iterdir()}
    monkeypatch.setenv("BENEF_INVERNO_LOGS", str(tmp_path / "logs"))
    import sincronizar_benef_inverno as sync
    plan = planilha(tmp_path / "p.xlsx")
    assert sync.main(["--planilha", str(plan), "--pasta-teste", str(banco)]) == 0
    depois = {p.name: p.read_text() for p in banco.iterdir()}
    mudou = sorted(n for n in depois if antes.get(n) != depois[n])
    assert mudou == ["BENEF_INVERNO__0.json", "_meta.json"]
    meta = json.loads(depois["_meta.json"])
    assert meta["mudaramNaUltima"] == ["BENEF_INVERNO"]
    # segunda execução: nada mudou → nada é gravado (nem a data)
    assert sync.main(["--planilha", str(plan), "--pasta-teste", str(banco)]) == 0
    assert {p.name: p.read_text() for p in banco.iterdir()} == depois


def test_recusa_planilha_vazia(tmp_path, monkeypatch):
    banco = tmp_path / "banco"
    _semear(banco)
    monkeypatch.setenv("BENEF_INVERNO_LOGS", str(tmp_path / "logs"))
    import sincronizar_benef_inverno as sync
    assert sync.main(["--planilha", str(planilha(tmp_path / "p.xlsx")), "--pasta-teste", str(banco)]) == 0
    vazia = tmp_path / "vazia.xlsx"
    wb = openpyxl.Workbook(); wb.active.append(CAB); wb.save(vazia)
    gravado = (banco / "BENEF_INVERNO__0.json").read_text()
    assert sync.main(["--planilha", str(vazia), "--pasta-teste", str(banco)]) == 2
    assert (banco / "BENEF_INVERNO__0.json").read_text() == gravado


def test_dois_processos_ao_mesmo_tempo_nao_se_apagam(tmp_path):
    """Robô do GitHub leu o _meta, o sincronizador gravou BENEF_INVERNO no
    meio do caminho, e só então o robô publicou. Antes, o robô regravava o
    _meta antigo e o dashboard quebrava (parte-inconsistente)."""
    s = _semear(tmp_path / "banco")
    d = s.conectar()
    meta_robo, _ = s.ler_conjuntos(d)                                  # robô lê
    s.publicar(d, {"BENEF_INVERNO": [{"cultivar": "X"}]}, "sync", renovar_verificacao=False)  # sync grava
    s.publicar(d, {"LOTS": [1, 2, 3]}, "robo", meta_atual=meta_robo)   # robô grava com _meta velho
    _, dados = s.ler_conjuntos(d)                                      # não pode dar inconsistente
    assert dados["BENEF_INVERNO"] == [{"cultivar": "X"}]
    assert dados["LOTS"] == [1, 2, 3]
    # e o "nada mudou" do robô também não pode derrubar o índice
    s.publicar(d, {"LOTS": [1, 2, 3]}, "robo2", meta_atual=meta_robo)
    _, dados = s.ler_conjuntos(d)
    assert dados["BENEF_INVERNO"] == [{"cultivar": "X"}]
