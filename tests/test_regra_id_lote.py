"""A MESMA regra de identificador do lote (SAFRA + CULTURA + LOTE) em três lugares:

  * Central de Lotes  — scripts/central_lotes.py  (montar_id_lote)
  * TSI               — estoquetsi/index.html      (montarIdLote)
  * RASTREL           — rastrel/index.html         (montarIdLote)

A tabela CASOS é o contrato. A parte em Python sempre roda; a parte em
JavaScript roda quando os outros repositórios estão ao lado deste
(../estoquetsi e ../rastrel) ou nas variáveis TSI_HTML / RASTREL_HTML, e
quando o Node está instalado.

Rodar: python -m pytest tests/test_regra_id_lote.py -q
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "scripts"))
import central_lotes as cl  # noqa: E402

# (safra, cultura, lote) -> lotId esperado
CASOS = [
    (("SOJA2526", "Soja", "26S133C"), "SOJA2526_26S133C"),          # Verão: ID histórico preservado
    (("SOJA2526", None, " 26s35b. "), "SOJA2526_26S35B"),
    ((None, None, "26S133C"), "SOJA2526_26S133C"),                  # registro antigo sem safra/cultura
    (("", "", "26S/1"), "SOJA2526_26S-1"),
    (("SOJA2627", "Soja", "26S1"), "SOJA2526_26S1"),                # safra desconhecida → leitura SOJA2526
    (("INV2626", "Trigo", "27AB001"), "INV2626_TRIGO_27AB001"),
    (("inv2626", " trigo ", "27ab001"), "INV2626_TRIGO_27AB001"),
    (("INV2626", "Aveia Branca", "X1"), "INV2626_AVEIA_BRANCA_X1"),
    (("INV2626", "Aveia Preta", "x-1"), "INV2626_AVEIA_PRETA_X-1"),
    (("INV2626", "Trigo Mourisco", "TM 01"), "INV2626_TRIGO_MOURISCO_TM01"),
    (("INV2626", "Ervilhaca", "E/7"), "INV2626_ERVILHACA_E-7"),
    (("INV2626", "Cevada", "27C9"), "INV2626_CEVADA_27C9"),
    (("INV2626", "Nabo", "N1"), "INV2626_NABO_N1"),
    (("INV2626", "Ervilha", "EV1"), "INV2626_ERVILHA_EV1"),
    (("INV2626", "Feijão", "F1"), "INV2626_FEIJAO_F1"),             # acento normalizado
    (("INV2626", "", "X1"), "INV2626_SEMCULTURA_X1"),
    (("INV2626", "Trigo", "   "), None),
    (("SOJA2526", "Soja", ""), None),
]

FUNCOES_JS = ["codigoLote", "normalizarCultura", "safraDeLeitura", "culturaDeLeitura", "montarIdLote"]


@pytest.mark.parametrize("args,esperado", CASOS)
def test_python(args, esperado):
    assert cl.montar_id_lote(*args) == esperado


def _bloco(texto, inicio):
    """Do índice `inicio` até a chave que fecha o primeiro bloco { }."""
    i = texto.index("{", inicio)
    nivel = 0
    for j in range(i, len(texto)):
        if texto[j] == "{":
            nivel += 1
        elif texto[j] == "}":
            nivel -= 1
            if nivel == 0:
                return texto[inicio:j + 1]
    raise ValueError("bloco sem fim")


def _extrair_js(html):
    partes = []
    m = re.search(r"const SAFRAS = Object\.freeze\(", html)
    assert m, "const SAFRAS não encontrado"
    fim = html.index("});", m.start()) + 3
    partes.append(html[m.start():fim])
    for nome in ("SAFRA_LEITURA_PADRAO", "CULTURA_SOJA"):
        mm = re.search(r"const " + nome + r" = [^;]+;", html)
        assert mm, nome
        partes.append(mm.group(0))
    for nome in FUNCOES_JS:
        mm = re.search(r"function " + nome + r"\(", html)
        assert mm, "função " + nome + " não encontrada"
        partes.append(_bloco(html, mm.start()))
    return "\n".join(partes)


def _caminho(var, pasta):
    p = os.environ.get(var) or os.path.join(AQUI, "..", "..", pasta, "index.html")
    return p if os.path.exists(p) else None


@pytest.mark.parametrize("modulo,var,pasta", [("TSI", "TSI_HTML", "estoquetsi"),
                                              ("RASTREL", "RASTREL_HTML", "rastrel")])
def test_javascript_igual_ao_python(modulo, var, pasta, tmp_path):
    caminho = _caminho(var, pasta)
    if not caminho:
        pytest.skip(f"{modulo}: index.html não encontrado (repositório ao lado ou {var})")
    if not shutil.which("node"):
        pytest.skip("node não instalado")
    js = _extrair_js(open(caminho, encoding="utf-8").read())
    casos = [list(a) for a, _ in CASOS]
    script = js + "\nconst casos = " + json.dumps(casos) + ";\n" + \
        "console.log(JSON.stringify(casos.map(c => montarIdLote(c[0], c[1], c[2]))));\n"
    arq = tmp_path / "regra.js"
    arq.write_text(script, encoding="utf-8")
    out = subprocess.run(["node", str(arq)], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [e for _, e in CASOS]
    # e a leitura de cultura também é a mesma
    script2 = js + "\nconsole.log(JSON.stringify([culturaDeLeitura(null,null), culturaDeLeitura('aveia preta','INV2626'), " \
        "culturaDeLeitura('TRIGO','INV2626'), safraDeLeitura(''), safraDeLeitura('inv2626')]));\n"
    arq.write_text(script2, encoding="utf-8")
    out2 = subprocess.run(["node", str(arq)], capture_output=True, text=True, check=True).stdout
    assert json.loads(out2) == [cl.cultura_de_leitura(None, None), cl.cultura_de_leitura("aveia preta", "INV2626"),
                                cl.cultura_de_leitura("TRIGO", "INV2626"), cl.safra_de_leitura(""),
                                cl.safra_de_leitura("inv2626")]
