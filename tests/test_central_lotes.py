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
    assert d["SOJA2526_5C"]["situacao"] == "INDETERMINADO"  # não está na Qualidade


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
    # Cadastro Mestre: lote fora da Qualidade usa a mesma chave que o TSI grava
    # (SAFRA_ATIVA) → sem aviso; só avisa quando o TSI gravou OUTRA safra
    d = montar([lote("26S133C")], [ordem_nova("7779", "99X999")])
    assert not [x for x in d["SOJA2526_99X999"]["divergencias"] if x["campo"] == "lotId"]
    d = montar([], [ordem_nova("7782", "99X998", safra="SOJA2425")])
    av = [x for x in d["SOJA2526_99X998"]["divergencias"] if x["campo"] == "lotId"]
    assert av and av[0]["tipo"] == "aviso" and av[0]["tsi"] == ["SOJA2425_99X998"]


def test_sourcelotcode_tem_prioridade_sobre_origem():
    o = ordem_nova("7780", "26S300C")
    o["lotesDetalhe"][0]["origem"] = " 26s300c. "   # texto livre antigo; o código padrão manda
    _, est = cl.resumir_tsi([o])
    t, _ = cl.resumir_tsi([o])
    assert list(t) == ["SOJA2526_26S300C"] and est["linhasComLotId"] == 1


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
    assert list(t) == ["SOJA2526_26S1"]   # safra desconhecida (SOJA2627) é lida como SOJA2526, como antes


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
    a, b = d["SOJA2526_27A"], d["SOJA2526_27B"]
    assert etapa(a, "qualidade") == "INDETERMINADO" and etapa(a, "tsi") == "CONCLUIDO"
    assert niveis(a, "fora_da_qualidade") == {"PENDENCIA"}
    assert etapa(b, "qualidade") == "INDETERMINADO" and etapa(b, "tsi") == "INDETERMINADO"
    assert etapa(b, "rastrel") == "INDETERMINADO"        # sem bags previstos
    assert niveis(b, "sem_bags_previstos") == set()      # sem Qualidade: não cobra bags previstos


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
    assert d["SOJA2526_31A"]["cultivar"] == "55I57RSF IPRO" and d["SOJA2526_31A"]["cultivarNome"] == "Zeus"


# ---- Cadastro Mestre de Lotes (nov/2026): lots/ = Qualidade ∪ TSI ∪ RASTREL, chave única

def lab(doc):
    return doc["qualidade"]


def test_A_lote_so_na_qualidade():
    d = montar([lote("26S100", ranking="B")])
    assert list(d) == ["SOJA2526_26S100"]
    doc = d["SOJA2526_26S100"]
    assert doc["origens"] == {"qualidade": True, "tsi": False, "rastrel": False}
    assert doc["qualidadeStatus"] == "APROVADO" and doc["tsi"] is None and doc["rastrel"] is None
    assert doc["tsiStatus"] == "SEM ORDEM COM LOTE" and doc["rastrelStatus"] == "SEM BAGS"
    assert doc["etapas"]["tsi"]["estado"] == "PENDENTE" and doc["etapas"]["rastrel"]["estado"] == "PENDENTE"
    assert not doc["safraPresumida"]
    # etapa anterior do fluxo: nunca é DIVERGENCIA nem AVISO
    assert doc["alertasPorNivel"]["DIVERGENCIA"] == 0 and doc["alertasPorNivel"]["AVISO"] == 0


def test_B_lote_so_no_rastrel():
    d = montar([], [], bags("26S101", 5))
    assert list(d) == ["SOJA2526_26S101"]
    doc = d["SOJA2526_26S101"]
    assert doc["origens"] == {"qualidade": False, "tsi": False, "rastrel": True}
    assert doc["qualidade"] is None and doc["qualidadeStatus"] == "NÃO ENCONTRADO"
    assert doc["qualidadeClasse"] is None and doc["pms"] is None      # nada laboratorial inventado
    assert doc["rastrel"]["bags"] == 5 and doc["tsiStatus"] == "SEM ORDEM COM LOTE"
    assert doc["safraPresumida"] is True
    assert niveis(doc, "rastrel_sem_qualidade") == {"AVISO"}
    assert not niveis(doc, "tsi_sem_qualidade")


def test_C_lote_so_no_tsi():
    d = montar([], [ordem("50", "26S102")])
    assert list(d) == ["SOJA2526_26S102"]
    doc = d["SOJA2526_26S102"]
    assert doc["origens"] == {"qualidade": False, "tsi": True, "rastrel": False}
    assert doc["qualidade"] is None and doc["qualidadeStatus"] == "NÃO ENCONTRADO"
    assert doc["rastrel"] is None and doc["rastrelStatus"] == "SEM BAGS"
    assert doc["tsi"]["ordens"][0]["ordem"] == "50"
    assert doc["pms"] is None                                          # PMS do TSI não vira PMS oficial
    assert niveis(doc, "tsi_sem_qualidade") == {"AVISO"}


def test_D_lote_nas_tres_fontes():
    d = montar([lote("26S103")], [ordem("51", "26S103")], bags("26S103", 20))
    assert list(d) == ["SOJA2526_26S103"]
    doc = d["SOJA2526_26S103"]
    assert doc["origens"] == {"qualidade": True, "tsi": True, "rastrel": True}
    assert doc["modulos"] == ["QUALIDADE", "TSI", "RASTREL"]
    assert doc["situacao"] == "PRONTO"
    assert not niveis(doc, "rastrel_sem_qualidade") and not niveis(doc, "tsi_sem_qualidade")


def test_E_nasce_no_rastrel_e_depois_aparece_na_qualidade():
    antes = montar([], [], bags("26S104", 20))
    depois = montar([lote("26S104")], [], bags("26S104", 20))
    assert list(antes) == list(depois) == ["SOJA2526_26S104"]        # MESMO documento
    a, b = antes["SOJA2526_26S104"], depois["SOJA2526_26S104"]
    assert a["qualidade"] is None and b["qualidade"]["bags"] == 20   # resultados acrescentados
    assert b["rastrel"] == a["rastrel"]                               # parte RASTREL intacta
    assert a["hash"] != b["hash"]
    # gravação: atualiza o mesmo id, não cria outro nem marca ausente
    atuais = {"SOJA2526_26S104": {"hash": a["hash"], "presente": True, "lotCode": "26S104"}}
    p = cl.planejar_gravacao(depois, atuais, "agora")
    assert list(p["gravar"]) == ["SOJA2526_26S104"] and not p["marcar"]


def test_E2_documento_antigo_semsafra_e_substituido_sem_apagar():
    novos = montar([lote("26S105")])
    atuais = {"SEMSAFRA_26S105": {"hash": "x", "presente": True, "lotCode": "26S105", "crop": "SEMSAFRA"},
              "SOJA2526_ANTIGO": {"hash": "y", "presente": True, "lotCode": "ANTIGO"},
              "SEMSAFRA_JA_OFF": {"hash": "z", "presente": False, "lotCode": "JA_OFF"}}
    p = cl.planejar_gravacao(novos, atuais, "agora")
    assert p["marcar"]["SEMSAFRA_26S105"] == {"presente": False, "substituidoPor": "SOJA2526_26S105",
                                              "mescladoEm": "agora"}
    assert p["marcar"]["SOJA2526_ANTIGO"] == {"presente": False} and p["perdidos"] == ["SOJA2526_ANTIGO"]
    assert "SEMSAFRA_JA_OFF" not in p["marcar"]                       # já estava fora: não mexe
    assert p["substituidos"] == 1 and p["ausentes"] == 1


def test_F_grafias_equivalentes_nao_duplicam():
    lots = [lote(" 26s106. ")]
    ordens = [ordem("52", "26S106")]
    bs = bags("26 S106", 2) + bags("26s106", 2)
    d = montar(lots, ordens, bs)
    assert list(d) == ["SOJA2526_26S106"]
    doc = d["SOJA2526_26S106"]
    assert doc["rastrel"]["bags"] == 4 and doc["lotCode"] == "26S106"
    assert niveis(doc, "codigo_lote") == {"AVISO"}                   # grafia diferente só gera aviso
    q = cl.resumir_qualidade({"LOTS": lots})
    t, _ = cl.resumir_tsi(ordens)
    r = cl.resumir_rastrel(bs)
    e = cl.estatisticas_uniao(q, t, r)
    assert e["uniao"] == 1 and e["mesclasEntreFontes"] == 2 and e["grafiasUnificadas"] >= 1


def test_uniao_contagens_e_qualidade_nunca_some():
    lots = [lote("A1"), lote("A2"), lote("A3", ranking="D")]
    d = montar(lots, [ordem("1", "A2"), ordem("2", "T9")], bags("A2", 3) + bags("R9", 2))
    assert set(d) == {"SOJA2526_" + c for c in ("A1", "A2", "A3", "T9", "R9")}
    q = cl.resumir_qualidade({"LOTS": lots})
    t, _ = cl.resumir_tsi([ordem("1", "A2"), ordem("2", "T9")])
    r = cl.resumir_rastrel(bags("A2", 3) + bags("R9", 2))
    e = cl.estatisticas_uniao(q, t, r)
    assert (e["qualidade"], e["tsi"], e["rastrel"], e["uniao"]) == (3, 2, 2, 5)
    assert (e["soQualidade"], e["soTsi"], e["soRastrel"], e["tresFontes"]) == (2, 1, 1, 1)


def test_tsi_e_rastrel_nunca_escrevem_dados_laboratoriais():
    o = ordem("53", "26S107", pms=210.0)
    b = [dict(x, germ=99, vigor=99, pms=999, classe="A") for x in bags("26S107", 2)]
    doc = montar([], [o], b)["SOJA2526_26S107"]
    assert doc["qualidade"] is None and doc["qualidadeClasse"] is None and doc["pms"] is None
    assert doc["qualidadeStatus"] == "NÃO ENCONTRADO"


# ---- safra-inverno: Verão + Inverno juntos, identidade SAFRA + CULTURA + LOTE

def lote_inv(code, cultura="Trigo", status="Aprovado", cultivar="TBIO CALIBRE"):
    return {"cultura": cultura, "cultivar": cultivar, "categoria": "S1", "lote": code,
            "kg": 28000, "embalagem": "BIG BAG", "germinacao": 95, "status": status}


def ordem_inv(num, code, cultura="Trigo", status="fechada"):
    o = ordem(num, code, status=status)
    o.update({"safra": "INV2626", "cultura": cultura, "cultivar": "TBIO CALIBRE"})
    for l in o["lotesDetalhe"]:
        l.update({"sourceLotCode": code, "treatedLotCode": code,
                  "sourceLotId": cl.montar_id_lote("INV2626", cultura, code),
                  "treatedLotId": cl.montar_id_lote("INV2626", cultura, code)})
    return o


def bags_inv(code, n, cultura="Trigo"):
    bs = bags(code, n, cultivar="TBIO CALIBRE")
    for b in bs:
        b.update({"safra": "INV2626", "cultura": cultura})
    return bs


def montar_inv(dados, ordens=(), bs=()):
    q = cl.resumir_qualidade(dados)
    t, _ = cl.resumir_tsi(list(ordens))
    r = cl.resumir_rastrel(list(bs))
    return cl.consolidar(q, t, r, AP, "agora")


def test_regra_id_lote():
    assert cl.montar_id_lote("SOJA2526", "Soja", " 26s133c. ") == "SOJA2526_26S133C"   # Verão: ID histórico
    assert cl.montar_id_lote(None, None, "26S133C") == "SOJA2526_26S133C"            # registro antigo
    assert cl.montar_id_lote("INV2626", "Trigo", "27ab001") == "INV2626_TRIGO_27AB001"
    assert cl.montar_id_lote("INV2626", "Aveia Branca", "X1") == "INV2626_AVEIA_BRANCA_X1"
    assert cl.montar_id_lote("inv2626", "  trigo mourisco ", "X1") == "INV2626_TRIGO_MOURISCO_X1"
    assert cl.montar_id_lote("INV2626", "", "X1") == "INV2626_SEMCULTURA_X1"
    assert cl.montar_id_lote("INV2626", "Trigo", "  ") is None
    assert cl.normalizar_cultura("Ervilhaca") == "ERVILHACA"
    assert cl.cultura_de_leitura(None, None) == "Soja"
    assert cl.cultura_de_leitura("aveia preta", "INV2626") == "Aveia Preta"


def test_1_e_2_registros_antigos_sem_safra_continuam_soja2526():
    d = montar([lote("40A")], [ordem("1", "40A")], bags("40A", 20))   # ordem e bags SEM safra/cultura
    doc = d["SOJA2526_40A"]
    assert set(d) == {"SOJA2526_40A"}
    assert doc["safra"] == "SOJA2526" and doc["cultura"] == "Soja" and doc["situacao"] == "PRONTO"
    assert doc["origens"] == {"qualidade": True, "tsi": True, "rastrel": True}


def test_4_5_6_mesmo_lote_de_inverno_nas_tres_fontes_vira_um_registro():
    d = montar_inv({"LOTS_INVERNO": [lote_inv("27AB001")]}, [ordem_inv("10", "27AB001")], bags_inv("27AB001", 20))
    assert list(d) == ["INV2626_TRIGO_27AB001"]
    doc = d["INV2626_TRIGO_27AB001"]
    assert doc["safra"] == "INV2626" and doc["cultura"] == "Trigo" and doc["lotCode"] == "27AB001"
    assert doc["modulos"] == ["QUALIDADE", "TSI", "RASTREL"]
    assert doc["qualidadeStatus"] == "APROVADO"
    assert doc["sourceLotId"] == doc["treatedLotId"] == "INV2626_TRIGO_27AB001"
    assert not [x for x in doc["divergencias"] if x["codigo"] == "lotid_diferente"]
    assert doc["safraPresumida"] is False


def test_7_mesmo_numero_em_culturas_e_safras_diferentes_nao_une():
    dados = {"LOTS": [lote("27AB001")],
             "LOTS_INVERNO": [lote_inv("27AB001", "Trigo"), lote_inv("27AB001", "Cevada", cultivar="ANA 01")]}
    d = montar_inv(dados, [ordem_inv("10", "27AB001", "Cevada")], bags_inv("27AB001", 5, "Trigo"))
    assert set(d) == {"SOJA2526_27AB001", "INV2626_TRIGO_27AB001", "INV2626_CEVADA_27AB001"}
    assert d["INV2626_CEVADA_27AB001"]["origens"] == {"qualidade": True, "tsi": True, "rastrel": False}
    assert d["INV2626_TRIGO_27AB001"]["origens"] == {"qualidade": True, "tsi": False, "rastrel": True}
    assert d["SOJA2526_27AB001"]["origens"] == {"qualidade": True, "tsi": False, "rastrel": False}


def test_8_verao_e_inverno_consolidados_juntos_e_verao_inalterado():
    so_verao = montar([lote("41A")], [ordem("1", "41A")], bags("41A", 20))
    juntos = montar_inv({"LOTS": [lote("41A")], "LOTS_INVERNO": [lote_inv("27AB009")]},
                        [ordem("1", "41A")], bags("41A", 20))
    assert set(juntos) == {"SOJA2526_41A", "INV2626_TRIGO_27AB009"}
    a, b = so_verao["SOJA2526_41A"], juntos["SOJA2526_41A"]
    assert {k: v for k, v in a.items() if k != "hash"} == {k: v for k, v in b.items() if k != "hash"}


def test_inverno_comprados_e_reprovado():
    dados = {"LOTS_INVERNO": [lote_inv("27AB002", status="Reprovado")],
             "LOTES_COMPRADOS_INVERNO": [{"cultura": "Aveia Preta", "cultivar": "EMBRAPA 139", "lote_origem": "ap-55",
                                          "kg": 1000, "germinacao": 88, "situacao": "APROVADO"}]}
    d = montar_inv(dados)
    assert d["INV2626_TRIGO_27AB002"]["qualidadeStatus"] == "REPROVADO"
    assert d["INV2626_AVEIA_PRETA_AP-55"]["qualidadeStatus"] == "APROVADO"
    assert d["INV2626_AVEIA_PRETA_AP-55"]["cultura"] == "Aveia Preta"


def test_planejar_gravacao_compara_identidade_e_nao_por_codigo():
    docs = montar([lote("50A")])
    # documento de Inverno com o MESMO número de lote, que sumiu da origem: fica ausente,
    # NUNCA "substituído" pelo lote de Verão 50A.
    atuais = {"INV2626_TRIGO_50A": {"hash": "x", "presente": True, "lotCode": "50A", "crop": "INV2626", "cultura": "Trigo"},
              "SEMSAFRA_50A": {"hash": "y", "presente": True, "lotCode": "50A", "crop": "SEMSAFRA"}}
    p = cl.planejar_gravacao(docs, atuais, "agora")
    assert p["marcar"]["INV2626_TRIGO_50A"] == {"presente": False}
    assert p["marcar"]["SEMSAFRA_50A"]["substituidoPor"] == "SOJA2526_50A"   # comportamento antigo preservado
    assert p["perdidos"] == ["INV2626_TRIGO_50A"]
    # e o inverso: lote de Inverno novo não marca o de Verão como ausente/substituído
    docs2 = montar_inv({"LOTS_INVERNO": [lote_inv("50A")]})
    p2 = cl.planejar_gravacao(docs2, {"SOJA2526_50A": {"hash": "z", "presente": True, "lotCode": "50A", "crop": "SOJA2526"}})
    assert p2["marcar"]["SOJA2526_50A"] == {"presente": False} and p2["substituidos"] == 0


def test_documento_lots_tem_cultura():
    d = montar_inv({"LOTS": [lote("60A")], "LOTS_INVERNO": [lote_inv("60B", "Nabo", cultivar="CATI AL 1000")]})
    assert d["SOJA2526_60A"]["cultura"] == "Soja"
    assert d["INV2626_NABO_60B"]["cultura"] == "Nabo"
