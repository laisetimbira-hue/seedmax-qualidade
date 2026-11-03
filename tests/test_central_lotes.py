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


# ---- TSI com lote obrigatório (sourceLotId / treatedLotId gravados pelo TSI)

def ordem_nova(num, origem, destino=None, status="fechada", safra=cl.SAFRA_ATIVA, kg=2000):
    src = cl.codigo_lote(origem)
    dst = cl.codigo_lote(destino) or src
    return {"id": num, "numeroLote": num, "status": status, "cultivar": "Zeus", "receitaNome": "TSI B",
            "data": "2026-11-03", "safra": safra,
            "sourceLotIds": [cl.montar_lot_id(safra, src)], "treatedLotIds": [cl.montar_lot_id(safra, dst)],
            "lotesDetalhe": [{"origem": src, "destino": dst, "kg": kg, "fonteLote": "manual",
                              "sourceLotCode": src, "sourceLotId": cl.montar_lot_id(safra, src),
                              "treatedLotCode": dst, "treatedLotId": cl.montar_lot_id(safra, dst)}]}


def test_ordem_manual_com_lot_id_vincula_sem_aviso():
    d = montar([lote("26S200A")], [ordem_nova("7777", "26S200A")], bags("26S200A", 20))
    doc = d["SOJA2526_26S200A"]
    assert doc["tsiStatus"] == "CONCLUÍDO"
    assert doc["sourceLotId"] == "SOJA2526_26S200A" and doc["treatedLotId"] == "SOJA2526_26S200A"
    assert doc["tsi"]["ordens"][0]["sourceLotId"] == "SOJA2526_26S200A"
    assert not any(x["campo"] in ("lotId", "lote") for x in doc["divergencias"])
    assert doc["situacao"] == "PRONTO"


def test_ordem_manual_lote_tratado_com_codigo_novo():
    d = montar([lote("26S201B")], [ordem_nova("7778", "26S201B", "26S201BT")])
    assert d["SOJA2526_26S201B"]["treatedLotId"] == "SOJA2526_26S201BT"


def test_lot_id_do_tsi_diferente_da_central_gera_aviso():
    # lote fora da Qualidade: a Central usa SEMSAFRA_, o TSI gravou SOJA2526_
    d = montar([lote("26S133C")], [ordem_nova("7779", "99X999")])
    doc = d["SEMSAFRA_99X999"]
    av = [x for x in doc["divergencias"] if x["campo"] == "lotId"]
    assert av and av[0]["tipo"] == "aviso" and av[0]["tsi"] == ["SOJA2526_99X999"]
    assert "SEMSAFRA_99X999" in av[0]["texto"]


def test_sourcelotcode_tem_prioridade_sobre_origem():
    o = ordem_nova("7780", "26S300C")
    o["lotesDetalhe"][0]["origem"] = " 26s300c. "   # texto livre antigo; o código padrão manda
    _, est = cl.resumir_tsi([o])
    t, _ = cl.resumir_tsi([o])
    assert list(t) == ["26S300C"] and est["linhasComLotId"] == 1


def test_codigo_lote_igual_ao_do_tsi():
    # mesmas regras do codigoLote()/montarLotId() do index.html do TSI
    assert cl.codigo_lote(" 26s35b. ") == "26S35B"
    assert cl.codigo_lote("-a1") == "A1"
    assert cl.montar_lot_id("SOJA2526", "26S/1") == "SOJA2526_26S-1"


def test_safra_ativa_unica():
    assert cl.SAFRA_PADRAO == cl.SAFRA_ATIVA
    d = montar([lote("26S200A")], [ordem_nova("7781", "26S200A")])
    assert (cl.SAFRA_ATIVA + "_26S200A") in d


def test_ordem_aberta_sem_lote_conta_como_pendente_e_nao_vincula():
    pend = {"id": "9002", "numeroLote": "9002", "status": "aberta", "cultivar": "Zeus",
            "safra": cl.SAFRA_ATIVA, "lotePendente": True, "lotesDetalhe": []}
    t, est = cl.resumir_tsi([pend, ordem_nova("9003", "26S1", safra="SOJA2627")])
    assert est["lotePendente"] == 1 and est["ordensSemLote"] == 1
    assert est["safras"] == {cl.SAFRA_ATIVA: 1, "SOJA2627": 1}
    assert list(t) == ["26S1"]


# ---- Central V2: níveis de alerta e linha do tempo (só com evidência)

def niveis(doc, codigo=None):
    return {d["nivel"] for d in doc["divergencias"] if codigo is None or d["codigo"] == codigo}


def etapa(doc, nome):
    return doc["etapas"][nome]["estado"]


def test_aprovado_sem_tsi_e_pendencia_nao_divergencia():
    doc = montar([lote("20A")])["SOJA2526_20A"]
    assert niveis(doc, "aprovado_sem_tsi") == {"PENDENCIA"}
    assert doc["alertasPorNivel"] == {"DIVERGENCIA": 0, "AVISO": 0, "PENDENCIA": 1}
    assert all(d["tipo"] == "aviso" for d in doc["divergencias"])   # tela antiga não pinta de vermelho
    assert [etapa(doc, e) for e in ("qualidade", "tsi", "rastrel", "expedicao")] == \
        ["CONCLUIDO", "PENDENTE", "PENDENTE", "PENDENTE"]


def test_divergencias_reais_e_avisos_classificados():
    lots = [lote("21A", cat="S2")]
    bs = bags("21A ", 25, tags=24, peso=700)
    doc = montar(lots, [ordem("1", "21A", pms=200.0)], bs)["SOJA2526_21A"]
    assert niveis(doc, "categoria") == {"DIVERGENCIA"}
    assert niveis(doc, "bags") == {"DIVERGENCIA"}
    assert niveis(doc, "pms") == {"DIVERGENCIA"}
    assert niveis(doc, "codigo_lote") == {"AVISO"}
    assert niveis(doc, "peso_bag") == {"AVISO"}
    assert niveis(doc, "bags_sem_tag") == {"PENDENCIA"}


def test_cultivar_e_peneira_divergentes():
    doc = montar([lote("22A", pen="P1")], [], [dict(b, peneira="P2") for b in bags("22A", 3, cultivar="Batalha")])["SOJA2526_22A"]
    assert niveis(doc, "cultivar") == {"DIVERGENCIA"} and niveis(doc, "peneira") == {"DIVERGENCIA"}


def test_reprovado_movimentado_e_divergencia_condicional_e_aviso():
    d = montar([lote("23A", ranking="D"), lote("23B", ranking="C")], [ordem("1", "23A"), ordem("2", "23B")])
    assert niveis(d["SOJA2526_23A"], "movimentado_reprovado") == {"DIVERGENCIA"}
    assert niveis(d["SOJA2526_23B"], "movimentado_sem_aprovacao") == {"AVISO"}
    assert etapa(d["SOJA2526_23A"], "qualidade") == "PENDENTE"     # reprovado nunca é "concluído"
    assert d["SOJA2526_23A"]["etapas"]["qualidade"]["texto"].startswith("Reprovado")


def test_rastrel_sem_tsi_nao_inventa_tsi_concluido():
    doc = montar([lote("24A")], [], bags("24A", 20))["SOJA2526_24A"]
    assert etapa(doc, "tsi") == "INDETERMINADO"          # RASTREL existir não prova TSI concluído
    assert etapa(doc, "rastrel") == "CONCLUIDO"
    assert niveis(doc, "rastrel_sem_tsi") == {"PENDENCIA"}
    assert niveis(doc, "tratamento_sem_ordem") == {"AVISO"}


def test_tsi_concluido_sem_rastrel_e_em_andamento():
    d = montar([lote("25A"), lote("25B")], [ordem("1", "25A"), ordem("2", "25B", status="aberta")])
    a, b = d["SOJA2526_25A"], d["SOJA2526_25B"]
    assert etapa(a, "tsi") == "CONCLUIDO" and etapa(a, "rastrel") == "PENDENTE"
    assert niveis(a, "tsi_sem_rastrel") == {"PENDENCIA"}
    assert etapa(b, "tsi") == "EM_ANDAMENTO" and not niveis(b, "tsi_sem_rastrel")


def test_expedicao_so_com_evidencia():
    exp = lambda bs: [dict(x, status="expedido") for x in bs]
    d = montar([lote("26A"), lote("26B"), lote("26C"), lote("26D", bags=30)],
               [ordem(str(i), c) for i, c in enumerate(("26A", "26B", "26C", "26D"))],
               bags("26A", 20) + exp(bags("26B", 20)) + exp(bags("26C", 5)) + bags("26C", 15) + exp(bags("26D", 20)))
    assert etapa(d["SOJA2526_26A"], "expedicao") == "PENDENTE"
    assert etapa(d["SOJA2526_26B"], "expedicao") == "CONCLUIDO"
    assert etapa(d["SOJA2526_26C"], "expedicao") == "EM_ANDAMENTO"
    assert etapa(d["SOJA2526_26D"], "expedicao") == "EM_ANDAMENTO"   # 20 expedidos de 30 previstos
    assert etapa(d["SOJA2526_26D"], "rastrel") == "EM_ANDAMENTO"


def test_lote_so_no_tsi_e_so_no_rastrel():
    d = montar([], [ordem("1", "27A")], bags("27B", 4))
    a, b = d["SEMSAFRA_27A"], d["SEMSAFRA_27B"]
    assert etapa(a, "qualidade") == "INDETERMINADO" and etapa(a, "tsi") == "CONCLUIDO"
    assert niveis(a, "fora_da_qualidade") == {"PENDENCIA"}
    assert etapa(b, "qualidade") == "INDETERMINADO" and etapa(b, "tsi") == "INDETERMINADO"
    assert etapa(b, "rastrel") == "INDETERMINADO"        # sem bags previstos
    assert niveis(b, "sem_bags_previstos") == set()      # sem Qualidade: só "fora_da_qualidade"


def test_nao_conectados_ficam_indeterminados():
    doc = montar([lote("28A")], tsi=False, rastrel=False)["SOJA2526_28A"]
    assert [etapa(doc, e) for e in ("tsi", "rastrel", "expedicao")] == ["INDETERMINADO"] * 3
    assert not niveis(doc, "aprovado_sem_tsi")


def test_multiplas_ordens_no_historico():
    doc = montar([lote("29A")], [ordem("1", "29A"), ordem("2", "29A", status="aberta")])["SOJA2526_29A"]
    assert [o["ordem"] for o in doc["tsi"]["ordens"]] == ["1", "2"]
    assert etapa(doc, "tsi") == "EM_ANDAMENTO"


def test_nenhuma_etapa_concluida_sem_dado():
    # varre combinações: etapa concluída exige o dado da PRÓPRIA etapa
    d = montar([lote("30A"), lote("30B", ranking="X")], [ordem("1", "30B")], bags("30A", 20) + bags("30C", 2))
    for doc in d.values():
        if etapa(doc, "qualidade") == "CONCLUIDO":
            assert doc["qualidadeStatus"] == "APROVADO"
        if etapa(doc, "tsi") == "CONCLUIDO":
            assert doc["tsi"] and all(o["status"] == "CONCLUÍDA" for o in doc["tsi"]["ordens"])
        if etapa(doc, "rastrel") == "CONCLUIDO":
            assert doc["rastrel"] and doc["totalBags"] and doc["rastrel"]["tags"] >= doc["totalBags"]
        if etapa(doc, "expedicao") == "CONCLUIDO":
            assert doc["rastrel"] and doc["rastrel"]["expedidos"] > 0


def test_cultivar_de_outro_modulo_vira_codigo_da_qualidade():
    q = cl.resumir_qualidade({"LOTS": []})
    t, _ = cl.resumir_tsi([ordem("1", "31A")])
    d = cl.consolidar(q, t, {}, AP, "agora", nomes=cl.montar_nomes(CV), codigos_cv=cl.montar_codigos(CV))
    assert d["SEMSAFRA_31A"]["cultivar"] == "55I57RSF IPRO" and d["SEMSAFRA_31A"]["cultivarNome"] == "Zeus"
