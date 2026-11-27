"""Localização atual (RASTREL) dos lotes do Beneficiamento de Inverno — sem rede.
Rodar: python -m pytest tests/test_localizacao_rastrel.py -q"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import localizacao_rastrel as lr  # noqa: E402


def benef(*lotes):
    """lotes = (lote, cultura, cultivar)"""
    out = {}
    for lote, cultura, cv in lotes:
        out.setdefault((cv, cultura), []).append({
            "lotId": f"INV2626_{cultura.upper().replace(' ', '_')}_{lote}", "lote": lote,
            "cultura": cultura, "cultivar": cv, "bags": 10, "kg": 10000, "localizacao": "UBS MANUAL"})
    return [{"cultivar": cv, "cultura": c, "detail": ds} for (cv, c), ds in out.items()]


def bag(lote, cultura, loc, status="em_estoque", epc="E1", safra="INV2626"):
    return {"lote": lote, "safra": safra, "cultura": cultura, "localizacao_atual": loc,
            "status": status, "epc": epc}


def mapa(blocos, fora=None):
    """blocos = {armazem: {bloco: [pilha, ...]}}"""
    return {"armazens": {wh: [{"id": b, "pilhas": ps} for b, ps in bs.items()] for wh, bs in blocos.items()},
            "fora_do_bloco": fora or {}}


TRIGO = ("26T001", "Trigo", "TBIO AUDAZ")
AVEIA = ("26T001", "Aveia Branca", "URS CORONA")      # mesmo número, outra cultura


def test_bags_com_e_sem_tag_em_varias_posicoes():
    bs = [bag("26T001", "Trigo", "A3B12")] * 3 + [bag("26T001", "trigo", "a3b 13")] \
        + [bag("26T001", "Trigo", "A4B2", status="aguardando_tag", epc=None)] * 2
    r = lr.resumir(bs, None, benef(TRIGO))
    pos = r["INV2626_TRIGO_26T001"]["posicoes"]
    assert pos == [{"posicao": "A3B12", "bags": 3, "fonte": "tag"},
                   {"posicao": "A4B2", "bags": 2, "fonte": "sem_tag"},
                   {"posicao": "A3B13", "bags": 1, "fonte": "tag"}]


def test_homonimo_em_outra_cultura_nao_mistura():
    bs = [bag("26T001", "Trigo", "A3B12"), bag("26T001", "Aveia Branca", "A4B9")]
    r = lr.resumir(bs, None, benef(TRIGO, AVEIA))
    assert [p["posicao"] for p in r["INV2626_TRIGO_26T001"]["posicoes"]] == ["A3B12"]
    assert [p["posicao"] for p in r["INV2626_AVEIA_BRANCA_26T001"]["posicoes"]] == ["A4B9"]


def test_bag_sem_safra_e_soja_nunca_casa_com_inverno():
    bs = [bag("26T001", None, "A3B1", safra=None), bag("26T001", "Soja", "A3B2", safra="SOJA2526")]
    assert lr.resumir(bs, None, benef(TRIGO)) == {}


def test_expedido_e_sem_posicao_nao_viram_posicao():
    bs = [bag("26T001", "Trigo", "A3B1", status="expedido"), bag("26T001", "Trigo", ""),
          bag("26T001", "Trigo", "Armazém"), bag("26T001", "Trigo", "A3B1", status="perdido")]
    r = lr.resumir(bs, None, benef(TRIGO))["INV2626_TRIGO_26T001"]
    assert r == {"posicoes": [], "semPosicao": 2, "expedidos": 1}


def test_lote_cadastrado_no_mapa_sem_tag_casa_pelo_cultivar():
    # cadastro manual no mapa: só cultivar + lote (sem cultura) → cultivar decide entre homônimos
    m = mapa({"Armazém 3": {"A3B15": [{"lote": "26T001", "lotes": ["26T001"], "cultivar": "TBIO AUDAZ",
                                        "qtd": "9BB", "cadastrado_no_rastrel": True}]}})
    r = lr.resumir([], m, benef(TRIGO, AVEIA))
    assert r == {"INV2626_TRIGO_26T001": {"posicoes": [{"posicao": "A3B15", "bags": 9, "fonte": "mapa"}]}}


def test_pilha_do_excel_com_especie_e_varias_posicoes():
    m = mapa({"Armazém 3": {"A3B11": [{"lotes": ["26T001"], "especie": "Trigo", "cultivar": "AUDAZ", "qtd": "5BB"}]},
              "Armazém 2": {"Lado A": [{"lotes": ["26T001"], "especie": "Trigo", "qtd": "2BB"}]}},
             fora={"Armazém 4": [{"posicao": "Corredor", "lotes": ["26T001"], "especie": "Trigo", "qtd": "1,5BB"}]})
    r = lr.resumir([], m, benef(TRIGO, AVEIA))["INV2626_TRIGO_26T001"]["posicoes"]
    assert r == [{"posicao": "A3B11", "bags": 5, "fonte": "mapa"},
                 {"posicao": "Armazém 2 · Lado A", "bags": 2, "fonte": "mapa"},
                 {"posicao": "Armazém 4 · Corredor", "bags": 1.5, "fonte": "mapa"}]


def test_pilha_ambigua_nao_e_vinculada_e_gera_aviso():
    m = mapa({"Armazém 3": {"A3B11": [{"lotes": ["26T001"], "qtd": "5BB"}]}})   # sem cultura e sem cultivar
    r = lr.resumir([], m, benef(TRIGO, AVEIA))
    for lid in ("INV2626_TRIGO_26T001", "INV2626_AVEIA_BRANCA_26T001"):
        assert r[lid]["posicoes"] == [] and "homônimo" in r[lid]["avisos"][0]


def test_pilha_sem_identificacao_com_codigo_de_soja_nao_e_vinculada():
    m = mapa({"Armazém 3": {"A3B11": [{"lotes": ["26T001"], "qtd": "5BB"}]}})
    r = lr.resumir([], m, benef(TRIGO), codigos_fora_do_inverno={"26T001"})
    assert r["INV2626_TRIGO_26T001"]["posicoes"] == [] and "outra safra" in r["INV2626_TRIGO_26T001"]["avisos"][0]
    # sem homônimo em lugar nenhum: o código basta
    r = lr.resumir([], m, benef(TRIGO))
    assert r["INV2626_TRIGO_26T001"]["posicoes"] == [{"posicao": "A3B11", "bags": 5, "fonte": "mapa"}]


def test_pilha_de_outra_cultura_ou_safra_nao_casa():
    m = mapa({"Armazém 3": {"A3B11": [{"lotes": ["26T001"], "especie": "Soja", "qtd": "5BB"},
                                      {"lotes": ["26T001"], "safra": "SOJA2526", "qtd": "5BB"},
                                      {"lotes": ["26T001"], "cultivar": "TITANIUM", "qtd": "5BB"}]}})
    assert lr.resumir([], m, benef(TRIGO)) == {}


def test_tag_posicionada_manda_sobre_o_excel():
    bs = [bag("26T001", "Trigo", "A3B12")]
    m = mapa({"Armazém 3": {"A3B11": [{"lotes": ["26T001"], "especie": "Trigo", "qtd": "5BB"}]}})
    r = lr.resumir(bs, m, benef(TRIGO))["INV2626_TRIGO_26T001"]["posicoes"]
    assert r == [{"posicao": "A3B12", "bags": 1, "fonte": "tag"}]


def test_tag_toda_expedida_ignora_pilha_antiga_do_excel():
    bs = [bag("26T001", "Trigo", "A3B12", status="expedido")]
    m = mapa({"Armazém 3": {"A3B11": [{"lotes": ["26T001"], "especie": "Trigo", "qtd": "5BB"}]}})
    assert lr.resumir(bs, m, benef(TRIGO))["INV2626_TRIGO_26T001"] == {"posicoes": [], "expedidos": 1}


def test_sem_tag_aguardando_soma_com_excel_e_celula_mista():
    bs = [bag("26T001", "Trigo", "A3B12", status="aguardando_tag", epc=None)]
    m = mapa({"Armazém 3": {"A3B11": [{"lotes": ["26T001", "26T009"], "especie": "Trigo", "qtd": "5BB"}]}})
    r = lr.resumir(bs, m, benef(TRIGO))["INV2626_TRIGO_26T001"]["posicoes"]
    assert r == [{"posicao": "A3B12", "bags": 1, "fonte": "sem_tag"},
                 {"posicao": "A3B11", "fonte": "mapa", "qtd": "5BB", "misto": True}]


def test_sem_informacao_no_rastrel_fica_fora_e_tela_usa_planilha():
    assert lr.resumir([bag("99X", "Trigo", "A3B1")], mapa({}), benef(TRIGO)) == {}
    assert lr.resumir([], None, []) == {}


def test_codigos_de_outras_safras():
    dados = {"LOTS": [{"lote": "26s1."}], "LOTES_COMPRADOS": [{"lote_origem": "C9"}], "LOTS_INVERNO": [{"lote": "X"}]}
    assert lr.codigos_de_outras_safras(dados, [bag("B7", None, "", safra=None), bag("T1", "Trigo", "")]) == {"26S1", "C9", "B7"}


def test_nao_altera_as_entradas():
    import copy
    bs = [bag("26T001", "Trigo", "A3B12")]
    m = mapa({"Armazém 3": {"A3B11": [{"lotes": ["26T001"], "especie": "Trigo", "qtd": "5BB"}]}})
    b = benef(TRIGO)
    antes = copy.deepcopy((bs, m, b))
    lr.resumir(bs, m, b)
    assert (bs, m, b) == antes


# ---------------------------------------------------------------- publicação (banco em pasta)

def test_publicacao_so_grava_o_conjunto_novo_e_so_quando_muda(tmp_path, monkeypatch):
    import central_lotes as cl
    import seedmax_dados as store
    monkeypatch.setenv("SEEDMAX_DESTINO", f"pasta:{tmp_path}")
    b = benef(TRIGO)
    store.publicar(store.conectar(), {"BENEF_INVERNO": b, "LOTS": [{"lote": "26S1"}]}, "c0")
    antes = {p.name: p.read_text() for p in tmp_path.glob("*.json") if p.name != "_meta.json"}
    m = mapa({"Armazém 3": {"A3B15": [{"lotes": ["26T001"], "cultivar": "TBIO AUDAZ", "qtd": "9BB"}]}})
    monkeypatch.setattr(cl, "ler_mapa_fisico", lambda: m)
    bs = [bag("26T001", "Trigo", "A4B2", status="aguardando_tag", epc=None)]

    _, dados = store.ler_conjuntos(store.conectar())
    assert cl.publicar_localizacao_inverno(dados, bs, carimbo="c1") is True
    meta, dados = store.ler_conjuntos(store.conectar())
    loc = dados[lr.CONJUNTO]
    assert loc["fontes"] == {"bags": True, "mapaFisico": True} and loc["atualizadoEm"] == "c1"
    assert [p["posicao"] for p in loc["lotes"]["INV2626_TRIGO_26T001"]["posicoes"]] == ["A3B15", "A4B2"]
    assert meta["mudaramNaUltima"] == [lr.CONJUNTO]
    # os conjuntos que já existiam ficam byte a byte iguais
    for nome, txt in antes.items():
        assert (tmp_path / nome).read_text() == txt
    # nada mudou → não grava (nem a versão do _meta)
    versao = meta["versao"]
    assert cl.publicar_localizacao_inverno(dados, bs, carimbo="c2") is False
    assert store.ler_conjuntos(store.conectar())[0]["versao"] == versao
    # simulação não grava
    assert cl.publicar_localizacao_inverno(dados, [], simular=True, carimbo="c3") is False
    assert store.ler_conjuntos(store.conectar())[0]["versao"] == versao

    # mapa/fisico ilegível: segue só com os bags, sem quebrar
    def falha():
        raise RuntimeError("sem acesso")
    monkeypatch.setattr(cl, "ler_mapa_fisico", falha)
    assert cl.publicar_localizacao_inverno(dados, bs, carimbo="c4") is True
    loc = store.ler_conjuntos(store.conectar())[1][lr.CONJUNTO]
    assert loc["fontes"]["mapaFisico"] is False
    assert [p["posicao"] for p in loc["lotes"]["INV2626_TRIGO_26T001"]["posicoes"]] == ["A4B2"]
