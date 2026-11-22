"""
SEEDMAX — simulação LOCAL do robô do Inverno (sem Firebase, sem Drive).

Lê CÓPIAS locais das planilhas, roda exatamente as mesmas funções do robô
(scripts/atualizar.py) e do sincronizador do Beneficiamento
(scripts/benef_inverno.py) e grava o resultado em JSON numa pasta local.
Nunca conecta ao Firestore nem ao Drive, e nunca altera as planilhas
(cada uma é lida em memória a partir de uma cópia dos bytes).

Uso:
  python scripts/simular_inverno_local.py --analises "ANALISES_INVERNO.xlsx" \
      [--benef "LOTES BENEFICIADOS INVERNO 26-26.xlsx"] \
      [--cv-meta CV_META_INVERNO.json] --saida pasta_saida [--lotes LOTE1,LOTE2]

  --cv-meta  (opcional) cadastro CV_META_INVERNO já publicado, em JSON, para a
             cultura vir do cadastro real; sem ele o cadastro é montado só com
             os lotes próprios da planilha (como na primeira execução do robô).
  --lotes    (opcional) códigos para o relatório de conferência (cultura,
             categoria, bags e kg em cada fonte).

A pasta de saída tem dados da empresa: NÃO versionar, NÃO enviar ao Drive.
"""
import argparse
import io
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
os.environ["SEEDMAX_DESTINO"] = "pasta:/dev/null/nao-usar"   # trava: nada aqui fala com o Firestore

import atualizar as robo          # noqa: E402
import benef_inverno              # noqa: E402


def _buf(caminho):
    return io.BytesIO(pathlib.Path(caminho).read_bytes())   # lê a cópia em memória; o arquivo não é tocado


def _norm(v):
    return robo._norm_txt(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--analises", required=True)
    ap.add_argument("--benef")
    ap.add_argument("--cv-meta")
    ap.add_argument("--saida", required=True)
    ap.add_argument("--lotes", default="")
    a = ap.parse_args()

    saida = pathlib.Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    cv_meta_pub = json.loads(pathlib.Path(a.cv_meta).read_text(encoding="utf-8")) if a.cv_meta else {}

    lots = robo.parse_inverno_lotes(_buf(a.analises))
    comprados = robo.parse_inverno_comprados(_buf(a.analises), lots)
    colheita = robo.parse_inverno_colheita(_buf(a.analises), lots)
    cv_meta = robo.montar_cv_meta_inverno(lots, cv_meta_pub)
    servico = robo.parse_inverno_servico(_buf(a.analises), lots, cv_meta_pub)

    conjuntos = {"LOTS_INVERNO": lots, "LOTES_COMPRADOS_INVERNO": comprados, "NOSSO_PLANTIO_INVERNO": colheita,
                 "CV_META_INVERNO": cv_meta, "LOTS_SERVICO_INVERNO": servico}
    conflitos = []
    if a.benef:
        culturas = {cv: (m or {}).get("cultura") for cv, m in cv_meta.items()}
        benef, conflitos, avisos = benef_inverno.ler(a.benef, culturas)
        conjuntos["BENEF_INVERNO"] = benef
        for x in avisos:
            print("aviso benef:", x)
    for nome, v in conjuntos.items():
        (saida / f"{nome}.json").write_text(json.dumps(v, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    print(f"Simulação: {len(lots)} lotes próprios · {len(comprados)} comprados · {len(servico)} PGW"
          + (f" · Beneficiamento: {sum(len(c.get('detail') or []) for c in conjuntos['BENEF_INVERNO'])} linhas, {len(conflitos)} conflitos" if a.benef else ""))
    pgw_bags = sum(x.get("bags") or 0 for x in servico)
    pgw_kg = sum(x.get("kg") or 0 for x in servico)
    print(f"PGW (aba de análises): {len(servico)} lotes · {pgw_bags:g} bags · {pgw_kg:g} kg")

    # relatório de conferência por lote: valor de CADA fonte, sem escolher nenhum
    alvo = [c.strip() for c in a.lotes.split(",") if c.strip()]
    if alvo:
        benef_det = [(c, d) for c in conjuntos.get("BENEF_INVERNO", []) for d in (c.get("detail") or [])]
        linhas = []
        for cod in alvo:
            q = [x for x in servico if _norm(x.get("lote")) == _norm(cod)]
            b = [(c, d) for c, d in benef_det if _norm(d.get("lote")) == _norm(cod)]
            linhas.append({
                "lote": cod,
                "pgw": [{k: x.get(k) for k in ("cultivar", "cultura", "fonte_cultura", "categoria", "bags", "kg", "pendencia")} for x in q],
                "beneficiamento": [{"cultivar": c.get("cultivar"), "cultura": d.get("cultura") or c.get("cultura"),
                                    "categoria": d.get("categoria"), "bags": d.get("bags"), "kg": d.get("kg")} for c, d in b],
                "cadastro_cultivar": (cv_meta.get(q[0]["cultivar"]) if q else None),
            })
        (saida / "conferencia_lotes.json").write_text(json.dumps(linhas, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        for l in linhas:
            print(json.dumps(l, ensure_ascii=False, default=str))
    if conflitos:
        (saida / "conflitos_benef.json").write_text(json.dumps(conflitos, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
