"""Gera uma coleção `qualidade` FICTÍCIA no formato real (seedmax_dados.publicar),
para testar o backup sem tocar no Firebase. Nenhum dado real."""
import json, pathlib, sys
raiz = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(raiz / "scripts"))
import seedmax_dados as sd
pasta = pathlib.Path(sys.argv[1])
dest = sd._DestinoPasta(pasta)
grande = [{"lote": f"26S{i:04d}X", "cultivar": "TESTE" * 40, "kg": 600.5, "sacos": 1, "germ": float("nan")} for i in range(5000)]
sd.publicar(dest, {
    "LOTS": grande,  # > 900 KB -> várias partes
    "LOTS_SERVICO_INVERNO": [{"lote": "PGWTESTE1", "empresa": "PGW", "cultura": "Aveia Branca", "kg": 600, "sacos": 1},
                             {"lote": "AMBTESTE1", "empresa": "AMBEV", "cultura": "Cevada", "kg": 1200, "sacos": 2}],
    "BENEF_INVERNO": {"aveia": [{"lote": "INVTESTE1", "kg_benef": 300}], "obs": "x"},
}, "27/11/2026 12:00")
print(json.load(open(pasta / "_meta.json"))["datasets"]["LOTS"]["partes"], "partes em LOTS")
