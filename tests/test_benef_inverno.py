"""Beneficiamento de Inverno — planilha, identidade do lote, função segura e ponta a ponta.

Planilhas usadas aqui são FICTÍCIAS (montadas no teste, com a estrutura da
real). A planilha da empresa nunca entra no repositório.

Rodar: python -m pytest tests/test_benef_inverno.py -q
(as partes em JavaScript precisam do Node; sem Node elas são puladas)
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

import openpyxl
import pytest

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parent
sys.path.insert(0, str(RAIZ / "scripts"))

import benef_inverno as bi  # noqa: E402
import central_lotes as cl  # noqa: E402

CASOS = json.loads((AQUI / "casos_benef_inverno.json").read_text(encoding="utf-8"))
NODE = shutil.which("node")
CAB = ["DATA", "CULTIVAR", "SAFRA", "CAT.", "LOTE", "PEN.", "EMBALAGEM", "N° BB", "PESO",
       "Total", "Localização", "Observações "]


def linha(lote, cv="CVA", bags=20, peso=600, total=None, cat="S2", **extra):
    d = {"aba": "A", "linha": 3, "cultivar": cv, "cultura_planilha": None, "data": None, "safra": "26/26",
         "categoria": cat, "lote": lote, "peneira": "S/P", "embalagem": "BB600", "bags": bags,
         "peso_bag": peso, "total_kg": bags * peso if total is None else total,
         "localizacao": "UBS X", "observacoes": None}
    d.update(extra)
    return d


CULTURAS = {"CVA": {"cultura": "Aveia Branca"}, "CVB": {"cultura": "Aveia Branca"}, "CVT": {"cultura": "Trigo"}}


def planilha(caminho, repetir=False, conflito=False):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "INVERNO 2026"
    ws.append(["CVTESTE1"]); ws.merge_cells("A1:L1")
    ws.append(CAB)
    for i in range(1, 4):
        ws.append([None, "CVTESTE1", "26/26", "S2", f"99XX0{i}", "S/P", "BB600", 20, 600, 12000, "UBS TESTE", None])
    if repetir:
        ws.append([None, "CVTESTE1", "26/26", "S2", "99XX01", "S/P", "BB600", 20, 600, 12000, "UBS TESTE", None])
    if conflito:
        ws.append([None, "CVTESTE1", "26/26", "C2", "99XX01", "S/P", "BB600", 20, 600, 12000, "UBS TESTE", None])
    ws.append([None, None, None, None, None, None, "N° BAGS ", 60, "FINALIZADO", 36000, None, None])
    ws2 = wb.create_sheet("PGW")
    ws2.append(["AVEIA BRANCA - CVTESTE2 "]); ws2.merge_cells("A1:L1")
    ws2.append(CAB)
    ws2.append([None, "CVTESTE2", "26/26", "S2", "TST001", "S/P", "BB600", 25, 600, 15000, "UBS TESTE", None])
    ws2.append([None, "CVTESTE2", "26/26", "S2", "TST001A", "S/P", "BB600", 17, 600, 10200, "UBS TESTE", "REPASSE"])
    ws2.append([None, None, None, None, None, None, "N° BAGS ", 42, "FINALIZADO ", 25200, None, None])
    wb.save(caminho)
    return caminho


# ------------------------------------------------------------ leitura da planilha

def test_leitura_da_planilha_e_totais(tmp_path):
    benef, conflitos, avisos = bi.ler(planilha(tmp_path / "p.xlsx"), {"CVTESTE1": {"cultura": "Trigo"}})
    assert conflitos == [] and avisos == []
    assert bi.totais(benef) == {"cultivares": 2, "lotes": 5, "bags": 102, "kg": 61200}
    c1, c2 = benef
    assert (c1["cultivar"], c1["cultura"], c1["lotes"], c1["bags_total"]) == ("CVTESTE1", "Trigo", 3, 60)
    assert (c2["cultivar"], c2["cultura"]) == ("CVTESTE2", "Aveia Branca")   # título da aba
    assert c2["detail"][1]["observacoes"] == "REPASSE"
    assert c2["detail"][1]["peneira"] == "S/P"                                # sem P1/P2
    assert c2["detail"][0]["lotId"] == "INV2626_AVEIA_BRANCA_TST001"
    assert c1["localizacoes"] == ["UBS TESTE"]


# ------------------------------------------------------------ casos compartilhados com a função (JS)

@pytest.mark.parametrize("caso", CASOS, ids=[c["nome"] for c in CASOS])
def test_consolidacao_casos(caso):
    benef, conflitos, avisos = bi.consolidar(caso["linhas"], caso["culturas"])
    lot_ids = sorted(d["lotId"] for c in benef for d in c["detail"])
    esp = caso["espera"]
    assert lot_ids == sorted(esp["lotIds"])
    assert [c["tipo"] for c in conflitos] == esp["conflitos"]
    if "bags" in esp:
        assert bi.totais(benef)["bags"] == esp["bags"]
        assert bi.totais(benef)["kg"] == esp["kg"]
    if "avisos" in esp:
        assert len(avisos) == esp["avisos"]
    if "localizacao" in esp:
        assert benef[0]["detail"][0]["localizacao"] == esp["localizacao"]
    assert len(set(lot_ids)) == len(lot_ids)          # nunca dois registros com o mesmo lotId


@pytest.mark.skipif(not NODE, reason="Node não instalado")
def test_python_e_funcao_geram_exatamente_o_mesmo_conjunto(tmp_path):
    """O computador da empresa compara o hash local com o publicado: Python e a
    função (JS) precisam gerar byte a byte o mesmo BENEF_INVERNO."""
    linhas, _ = bi.ler_planilha(planilha(tmp_path / "p.xlsx", repetir=True))
    entradas = [{"linhas": c["linhas"], "culturas": c["culturas"]} for c in CASOS]
    entradas.append({"linhas": linhas, "culturas": {"CVTESTE1": "Trigo"}})
    script = ("const bi=require(%r);const e=JSON.parse(require('fs').readFileSync(0,'utf8'));"
              "process.stdout.write(JSON.stringify(e.map(x=>{const r=bi.consolidar(x.linhas,x.culturas);"
              "return {texto:bi.js(r.benef),hash:bi.hash(bi.js(r.benef)),conflitos:r.conflitos.map(c=>c.tipo),avisos:r.avisos}})))"
              % str(RAIZ / "ponte" / "benef-inverno.js"))
    saida = json.loads(subprocess.run([NODE, "-e", script], input=json.dumps(entradas), capture_output=True,
                                      text=True, check=True, encoding="utf-8").stdout)
    import sincronizar_benef_inverno as sync
    for e, js in zip(entradas, saida):
        benef, conflitos, avisos = bi.consolidar(e["linhas"], e["culturas"])
        assert json.dumps(benef, ensure_ascii=False, separators=(",", ":")) == js["texto"]
        assert sync.hash_conjunto(benef) == js["hash"]
        assert [c["tipo"] for c in conflitos] == js["conflitos"]
        assert avisos == js["avisos"]


# ------------------------------------------------------------ REGRA: não duplicar lotes (testes pedidos)

def _dados_central(benef):
    return {"LOTS_INVERNO": [{"lote": "99QQ01", "cultura": "Aveia Branca", "cultivar": "CVA", "bags": 20,
                              "kg": 12000, "status": "Aprovado", "germinacao": 95}],
            "BENEF_INVERNO": benef}


def test_1_lote_em_LOTS_INVERNO_e_em_BENEF_INVERNO_continua_uma_identidade_na_central():
    benef, conflitos, _ = bi.consolidar([linha("99QQ01")], CULTURAS)
    assert not conflitos
    dados = _dados_central(benef)
    q = cl.resumir_qualidade(dados)
    vinculados, sem_lote = cl.vincular_beneficiamento_inverno(q, dados["BENEF_INVERNO"])
    docs = cl.consolidar(q, {}, {}, {}, "agora", tsi_conectado=False, rastrel_conectado=False)
    ids = [k for k in docs if k.endswith("99QQ01")]
    assert ids == ["INV2626_AVEIA_BRANCA_99QQ01"]                 # uma única identidade
    assert vinculados == ["INV2626_AVEIA_BRANCA_99QQ01"] and sem_lote == []
    assert docs[ids[0]]["beneficiamento"]["bags"] == 20          # beneficiamento VINCULADO ao lote
    assert docs[ids[0]]["qualidade"]["germ"] == 95               # dados do lote preservados
    # e um lote só do beneficiamento NÃO cria documento novo na Central
    benef2, _, _ = bi.consolidar([linha("99QQ01"), linha("99QQ77", linha=4)], CULTURAS)
    q2 = cl.resumir_qualidade(_dados_central(benef2))
    _, sem2 = cl.vincular_beneficiamento_inverno(q2, benef2)
    docs2 = cl.consolidar(q2, {}, {}, {}, "agora", tsi_conectado=False, rastrel_conectado=False)
    assert sem2 == ["INV2626_AVEIA_BRANCA_99QQ77"]
    assert "INV2626_AVEIA_BRANCA_99QQ77" not in docs2
    assert len(docs2) == 1


def test_2_mesma_linha_repetida_duas_vezes_no_excel_nao_duplica_lote(tmp_path):
    benef, conflitos, avisos = bi.ler(planilha(tmp_path / "p.xlsx", repetir=True), {"CVTESTE1": "Trigo"})
    assert not conflitos
    ids = [d["lotId"] for c in benef for d in c["detail"]]
    assert ids.count("INV2626_TRIGO_99XX01") == 1
    assert bi.totais(benef)["bags"] == 102                       # não somou a linha repetida
    assert any("repete exatamente" in a for a in avisos)


def test_3_mesmo_numero_de_lote_em_culturas_diferentes_sao_identidades_diferentes():
    benef, conflitos, _ = bi.consolidar([linha("99QQ01", cv="CVA"), linha("99QQ01", cv="CVT", linha=4)], CULTURAS)
    assert not conflitos
    assert sorted(d["lotId"] for c in benef for d in c["detail"]) == \
        ["INV2626_AVEIA_BRANCA_99QQ01", "INV2626_TRIGO_99QQ01"]
    dados = {"LOTS_INVERNO": [{"lote": "99QQ01", "cultura": "Aveia Branca"}, {"lote": "99QQ01", "cultura": "Trigo"}]}
    q = cl.resumir_qualidade(dados)
    vinc, _ = cl.vincular_beneficiamento_inverno(q, benef)
    assert vinc == ["INV2626_AVEIA_BRANCA_99QQ01", "INV2626_TRIGO_99QQ01"]


@pytest.mark.parametrize("campo,valor,tipo", [
    ("cv", "CVB", "cultivar_divergente"),
    ("cat", "C2", "categoria_divergente"),
    ("peso", 1000, "peso_bag_divergente"),
])
def test_4_mesma_cultura_e_lote_com_dados_conflitantes_sinaliza_conflito(campo, valor, tipo):
    benef, conflitos, _ = bi.consolidar([linha("99QQ01"), linha("99QQ01", linha=4, **{campo: valor})], CULTURAS)
    assert benef == []                                            # nada para publicar
    assert [c["tipo"] for c in conflitos] == [tipo]
    assert conflitos[0]["lotId"] == "INV2626_AVEIA_BRANCA_99QQ01"


def test_4b_quantidade_incompativel_sinaliza_conflito():
    benef, conflitos, _ = bi.consolidar([linha("99QQ01", total=11000)], CULTURAS)
    assert benef == [] and [c["tipo"] for c in conflitos] == ["quantidade_incompativel"]


def test_lotid_do_beneficiamento_e_o_mesmo_da_central():
    for cultura, lote in [("Aveia Branca", "99QQ01"), ("Trigo", " 99qq01. "), ("Trigo Mourisco", "TM 01")]:
        assert bi.montar_lot_id(cultura, lote) == cl.montar_id_lote("INV2626", cultura, lote)


# ------------------------------------------------------------ índice: robô e função não se apagam

def _semear(pasta):
    os.environ["SEEDMAX_DESTINO"] = f"pasta:{pasta}"
    import seedmax_dados as s
    s.publicar(s.conectar(), {
        "LOTS_INVERNO": [{"lote": "A1"}], "LOTS": [1, 2], "TZ_DATA": {"x": 1},
        "CV_META_INVERNO": {"CVTESTE1": {"cultura": "Trigo", "obtentor": None},
                            "CVTESTE2": {"cultura": "Aveia Branca", "obtentor": None}},
        "BENEF_INVERNO": [],
    }, "inicial", meta_atual={})
    return s


def test_robo_com_indice_velho_nao_apaga_o_que_outro_processo_gravou(tmp_path):
    s = _semear(tmp_path / "banco")
    d = s.conectar()
    meta_robo, _ = s.ler_conjuntos(d)
    s.publicar(d, {"BENEF_INVERNO": [{"cultivar": "X"}]}, "sync", renovar_verificacao=False)
    s.publicar(d, {"LOTS": [1, 2, 3]}, "robo", meta_atual=meta_robo)
    _, dados = s.ler_conjuntos(d)                                  # sem "inconsistente"
    assert dados["BENEF_INVERNO"] == [{"cultivar": "X"}] and dados["LOTS"] == [1, 2, 3]
    s.publicar(d, {"LOTS": [1, 2, 3]}, "robo2", meta_atual=meta_robo)
    _, dados = s.ler_conjuntos(d)
    assert dados["BENEF_INVERNO"] == [{"cultivar": "X"}]


# ------------------------------------------------------------ PONTA A PONTA (Excel → script → função → banco)

@pytest.fixture
def servidor(tmp_path):
    if not NODE:
        pytest.skip("Node não instalado")
    banco = tmp_path / "banco"
    s = _semear(banco)
    p = subprocess.Popen([NODE, str(AQUI / "e2e_benef_inverno" / "servidor.cjs"), str(banco), "0"],
                         stdout=subprocess.PIPE, text=True)
    porta = int(p.stdout.readline().split()[1])
    yield {"banco": banco, "store": s, "url": f"http://127.0.0.1:{porta}/sync",
           "login": f"http://127.0.0.1:{porta}/login?key=", "registros": tmp_path / "sincronizacoes.json"}
    p.terminate()
    p.wait(5)


def _rodar(sv, plan, *extra, email="sinc@teste", senha="certa"):
    import sincronizar_benef_inverno as sync
    os.environ["SEEDMAX_SYNC_SENHA"] = senha
    os.environ["BENEF_INVERNO_LOGS"] = str(sv["banco"].parent / "logs")
    return sync.main(["--planilha", str(plan), "--email", email, "--url", sv["url"],
                      "--url-login", sv["login"], *extra])


def _arquivos(pasta):
    return {p.name: p.read_text() for p in sorted(pathlib.Path(pasta).glob("*.json"))}


def test_ponta_a_ponta(servidor, tmp_path):
    sv, s = servidor, servidor["store"]
    antes = _arquivos(sv["banco"])
    plan = planilha(tmp_path / "p.xlsx")

    # simulação: não grava nada
    assert _rodar(sv, plan, "--simular") == 0
    assert _arquivos(sv["banco"]) == antes

    # 1ª sincronização: grava só BENEF_INVERNO
    assert _rodar(sv, plan) == 0
    depois = _arquivos(sv["banco"])
    assert sorted(k for k in depois if depois[k] != antes.get(k)) == ["BENEF_INVERNO__0.json", "_meta.json"]
    meta, dados = s.ler_conjuntos(s.conectar())                   # o robô/dashboard lê sem erro
    assert meta["mudaramNaUltima"] == ["BENEF_INVERNO"]
    assert bi.totais(dados["BENEF_INVERNO"]) == {"cultivares": 2, "lotes": 5, "bags": 102, "kg": 61200}
    assert dados["BENEF_INVERNO"][0]["cultura"] == "Trigo"        # cultura do CV_META_INVERNO, via função
    assert dados["LOTS"] == [1, 2] and dados["LOTS_INVERNO"] == [{"lote": "A1"}]
    assert meta["datasets"]["BENEF_INVERNO"]["sincronizadoEm"]
    reg = json.loads(sv["registros"].read_text())
    assert reg[-1]["resultado"] == "PUBLICADO" and reg[-1]["uid"] == "u-sync"

    # 2ª execução sem mudança: não envia nada (o banco não muda)
    assert _rodar(sv, plan) == 0
    assert _arquivos(sv["banco"]) == depois

    # linha repetida no Excel: mesmo resultado, nada muda
    assert _rodar(sv, planilha(tmp_path / "rep.xlsx", repetir=True)) == 0
    assert _arquivos(sv["banco"]) == depois

    # conflito: o script para ANTES de enviar (código 3) e nada muda
    assert _rodar(sv, planilha(tmp_path / "conf.xlsx", conflito=True)) == 3
    assert _arquivos(sv["banco"]) == depois

    # senha errada e conta sem o perfil técnico: recusados, nada muda
    with pytest.raises(SystemExit, match="login da conta técnica recusado"):   # vira código 1 no Windows
        _rodar(sv, plan, senha="errada")
    assert _rodar(sv, plan, email="admin@teste") == 2
    assert _arquivos(sv["banco"]) == depois

    # robô publica LOTS com índice velho enquanto isso: tudo continua consistente
    s.publicar(s.conectar(), {"LOTS": [7]}, "robo", meta_atual=meta)
    _, dados = s.ler_conjuntos(s.conectar())
    assert dados["LOTS"] == [7] and bi.totais(dados["BENEF_INVERNO"])["lotes"] == 5


def test_ponta_a_ponta_funcao_recusa_conflito_mesmo_se_o_script_nao_detectar(servidor):
    """Defesa em profundidade: se um envio chegar sem passar pela validação do
    script, a função recusa sozinha (409) e não grava."""
    import sincronizar_benef_inverno as sync
    antes = _arquivos(servidor["banco"])
    token = sync.entrar("sinc@teste", "certa", servidor["login"])
    corpo = {"acao": "publicar", "formato": 1, "planilha": {"nome": "x.xlsx"},
             "linhas": [linha("99XX01", cv="CVTESTE1"), linha("99XX01", cv="CVTESTE1", cat="C2", linha=4)]}
    st, r = sync._post(servidor["url"], corpo, token)
    assert st == 409 and r["erro"] == "conflito"
    st, r = sync._post(servidor["url"], dict(corpo, linhas=[]), token)
    assert st == 400 and r["erro"] == "payload_invalido"
    st, r = sync._post(servidor["url"], dict(corpo, conjunto="LOTS"), token)
    assert st == 400
    assert _arquivos(servidor["banco"]) == antes
