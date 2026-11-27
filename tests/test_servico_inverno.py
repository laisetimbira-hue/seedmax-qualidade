"""Prestação de Serviço do Inverno (planilha de análises): PGW obrigatória,
AMBEV opcional. Os resultados de qualidade da PGW nunca podem sumir."""
import io
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import atualizar as a  # noqa: E402

CAB = ["DATA", "CULTURA", "CULTIVAR", "CATEGORIA", "LOTE", "EMBALAGEM", "QUANT.", "kg do lote",
       "OFICIAL GERMINAÇÃO", "OFICIAL VIGOR", "PMS", "PH", "PUREZA %", "STATUS INTERNO", "OBSERVAÇÃO"]


def _buf(abas):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nome, linhas, cab in abas:
        ws = wb.create_sheet(nome)
        ws.append(cab or CAB)
        for l in linhas:
            ws.append(l)
    b = io.BytesIO(); wb.save(b); b.seek(0)
    return b


PGW = [["01/11/2026", "Aveia Branca", "CV PGW", "S2", "PG01", "BB600", 20, 12000, 92, 85, 31.4, 52.1, 98.5, "x", "ok"],
       ["02/11/2026", "Trigo", "CV PGW2", "C2", "PG02", "BB600", 10, 6000, 81, None, None, None, None, None, None],
       ["03/11/2026", "Trigo", "CV PGW2", "C2", "PG03", "BB600", 5, 3000, None, None, None, None, None, None, None]]
AMBEV = [["04/11/2026", "Cevada", "CV CEV", "S1", "AM01", "BB1000", 15, 15000, 95, 90, 45.0, 65.3, None, None, "malte"]]


def test_pgw_preserva_todos_os_resultados_de_qualidade():
    out = a.juntar_servico_inverno(_buf([("PGW", PGW, None)]), [])
    assert [l["lote"] for l in out] == ["PG01", "PG02", "PG03"]
    pg = out[0]
    assert pg["empresa"] == "PGW"
    assert (pg["germinacao"], pg["vigor"], pg["status"], pg["categoria"], pg["observacao"]) == (92, 85, "Aprovado", "S2", "ok")
    assert pg["analises"]["PMS"] == 31.4 and pg["analises"]["PH"] == 52.1 and pg["analises"]["PUREZA %"] == 98.5
    assert out[1]["status"] == "Reprovado" and out[2]["status"] is None          # pendente continua pendente
    assert (pg["bags"], pg["kg"], pg["data"], pg["embalagem"]) == (20, 12000, "01/11/2026", "BB600")


def test_ambev_entra_separada_quando_existe():
    out = a.juntar_servico_inverno(_buf([("PGW", PGW, None), (" AMBEV ", AMBEV, None)]), [])
    assert [(l["empresa"], l["lote"]) for l in out] == [("PGW", "PG01"), ("PGW", "PG02"), ("PGW", "PG03"), ("AMBEV", "AM01")]
    am = out[-1]
    assert (am["germinacao"], am["vigor"], am["status"]) == (95, 90, "Aprovado")
    assert am["analises"]["PMS"] == 45.0 and am["analises"]["PH"] == 65.3


def test_sem_aba_pgw_preserva_o_conjunto_publicado():
    # mesmo com AMBEV presente: sem PGW nada é publicado (os registros da PGW não podem sumir)
    assert a.juntar_servico_inverno(_buf([("AMBEV", AMBEV, None)]), []) is None


def test_aba_ambev_fora_do_padrao_nao_derruba_a_pgw():
    out = a.juntar_servico_inverno(_buf([("PGW", PGW, None), ("AMBEV", [["x", "y"]], ["COLUNA A", "COLUNA B"])]), [])
    assert [l["lote"] for l in out] == ["PG01", "PG02", "PG03"]


def test_parse_inverno_pgw_continua_igual_mais_o_campo_empresa():
    out = a.parse_inverno_pgw(_buf([("PGW", PGW, None)]), [])
    assert len(out) == 3 and all(l["empresa"] == "PGW" for l in out)
