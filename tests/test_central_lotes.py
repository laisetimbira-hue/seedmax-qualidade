"""Testes da consolidação da Central de Lotes (sem rede, sem Firebase).
Rodar: python -m pytest tests/test_central_lotes.py -q"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import central_lotes as cl  # noqa: E402

CV = {"55I57RSF IPRO": {"nome": "Zeus"}, "68K66RSF CE": {"nome": "Batalha"}}
AP = cl.montar_apelidos(CV)


def lote(code, ranking="A", bags=20, peso=900.0, cultivar="55I57RSF IPRO", cat="S1", pen="P1"):
    return {"lote": code, "ranking": ranking, "status": "x", "bags": bags, "kg": bags * peso,
            "peso_bag": peso, "cultivar": cultivar, "categoria": cat, "peneira": pen, "pms_etq": 190.0}


def ordem(num, code, status="fechada", qtd=20, destino=None, pms=190.0):
    return {"id": num, "numeroLote": num, "status": status, "cultivar": "55I57RSF IPRO (ZEUS)",
            "receitaNome": "TSI A", "data": "2026-10-29",
            "lotesDetalhe": [{"origem": code, "destino": destino or code, "qtdOrigem": qtd, "qtdDestino": qtd,
                              "unidade": "5,0M", "kg": qtd * 900, "pesoBag": 900, "pms": pms}]}


def bags(code, n, tags=None, cultivar="Zeus", peso=900):
    tags = n if tags is None else tags
    return [{"lote": code, "epc": "E%d" % i if i < tags else "", "cultivar_nome": cultivar,
             "categoria": "S1", "peneira": "P1", "peso_kg": peso, "tratamento": "TSI A",
             "status": "em_estoque"} for i in range(n)]


def montar(lots, ordens=(), bs=(), tsi=True, rastrel=True):
    q = cl.resumir_qualidade({"LOTS": lots})
    t, _ = cl.resumir_tsi(list(ordens))
    r = cl.resumir_rastrel(list(bs))
    return cl.consolidar(q, t, r, AP, "agora", tsi_conectado=tsi, rastrel_conectado=rastrel)


def sit(docs, code):
    return docs["SOJA2526_" + code]["situacao"]


def test_lot_id_e_codigo():
    assert cl.codigo_lote(" 26s35b. ") == "26S35B"
    assert cl.montar_lot_id("SOJA2526", "26S133C") == "SOJA2526_26S133C"


def test_qualidade_pendente():
    d = montar([lote("1A", ranking="C"), lote("1B", ranking="D"), lote("1C", ranking="X")])
    assert {sit(d, c) for c in ("1A", "1B", "1C")} == {"QUALIDADE PENDENTE"}


def test_liberado_para_tsi():
    assert sit(montar([lote("2A")]), "2A") == "LIBERADO PARA TSI"


def test_em_tsi():
    assert sit(montar([lote("3A")], [ordem("1", "3A", status="aberta")]), "3A") == "EM TSI"


def test_aguardando_rastreando_pronto():
    d = montar([lote("4A"), lote("4B"), lote("4C")],
               [ordem("1", "4A"), ordem("2", "4B"), ordem("3", "4C")],
               bags("4B", 20, tags=5) + bags("4C", 20))
    assert sit(d, "4A") == "AGUARDANDO RASTREL"
    assert sit(d, "4B") == "RASTREANDO"
    assert sit(d, "4C") == "PRONTO"
    assert d["SOJA2526_4C"]["sourceLotId"] == d["SOJA2526_4C"]["treatedLotId"] == "SOJA2526_4C"


def test_indeterminado_sem_dados_suficientes():
    d = montar([lote("5A")], [], bags("5A", 20))
    assert sit(d, "5A") == "INDETERMINADO"            # bags no RASTREL, sem ordem com lote no TSI
    d = montar([lote("5B")], tsi=False, rastrel=False)
    assert sit(d, "5B") == "INDETERMINADO"            # módulos não conectados
    d = montar([], [], bags("5C", 3))
    assert d["SEMSAFRA_5C"]["situacao"] == "INDETERMINADO"  # não está na Qualidade


def test_reprovado_movimentado_vira_indeterminado_com_divergencia():
    d = montar([lote("6A", ranking="D")], [ordem("1", "6A")])
    doc = d["SOJA2526_6A"]
    assert doc["situacao"] == "INDETERMINADO"
    assert any(x["campo"] == "qualidade" for x in doc["divergencias"])


def test_apelido_de_cultivar_nao_gera_divergencia():
    d = montar([lote("7A", cultivar="68K66RSF CE")], [], bags("7A", 20, cultivar="Batalha"))
    assert not [x for x in d["SOJA2526_7A"]["divergencias"] if x["campo"] == "cultivar"]


def test_divergencias_detectadas():
    lots = [lote("8A", cat="S2")]
    bs = bags("8A ", 25, tags=24, peso=700)  # código com espaço, mais bags, 1 sem tag, peso diferente
    d = montar(lots, [ordem("1", "8A", pms=200.0)], bs)
    campos = {x["campo"] for x in d["SOJA2526_8A"]["divergencias"]}
    assert {"categoria", "bags", "tags", "kg", "pms"} <= campos


def test_lote_tratado_com_codigo_novo():
    d = montar([lote("9A")], [ordem("1", "9A", destino="9A-T")])
    assert d["SOJA2526_9A"]["treatedLotId"] == "SOJA2526_9A-T"


def test_ordem_antiga_sem_status_conta_como_concluida():
    d = montar([lote("11A")], [ordem("1", "11A", status=None)])
    assert sit(d, "11A") == "AGUARDANDO RASTREL"


def test_hash_estavel():
    a = montar([lote("10A")])["SOJA2526_10A"]["hash"]
    b = montar([lote("10A")])["SOJA2526_10A"]["hash"]
    assert a == b
