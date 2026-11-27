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
