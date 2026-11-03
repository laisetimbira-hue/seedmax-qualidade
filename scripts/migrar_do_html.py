#!/usr/bin/env python3
"""
SEEDMAX — migração inicial: leva os dados que hoje estão escritos no
index.html do dashboard antigo para o banco protegido (Firestore).

Roda UMA vez, antes de ligar a nova atualização automática. Traz também
os conjuntos que a automação não recalcula (histórico de aprovação,
TZ_DATA, CAMPOS_SIGEF, CV_META, CV_UBS, dados de Inverno já publicados).

Uso:
  python scripts/migrar_do_html.py <caminho-ou-URL-do-index.html-antigo> [--forcar]

Sem --forcar, recusa sobrescrever um banco que já tenha dados.
"""

import json
import re
import sys

import requests

import seedmax_dados as store

DATASETS = ["LOTS", "SUMMARY", "SUMMARY_PREV", "PMS_CV", "LOTES_COMPRADOS",
            "NOSSO_PLANTIO", "LOTS_INVERNO", "NOSSO_PLANTIO_INVERNO",
            "LOTES_COMPRADOS_INVERNO", "CV_META_INVERNO", "BENEF_INVERNO",
            "HISTORICO_APROVACAO", "MUDANCAS_RECENTES", "BENEF", "DIAG_DATA",
            "TZ_DATA", "CAMPOS_SIGEF", "CV_META", "CV_UBS"]


def carregar_html(origem):
    if re.match(r"https?://", origem):
        r = requests.get(origem, timeout=120)
        r.raise_for_status()
        return r.text
    with open(origem, encoding="utf-8") as f:
        return f.read()


def extrair(html):
    dados = {}
    for nome in DATASETS:
        m = re.search(rf"^\s*const {nome} = (.*);\s*$", html, re.M)
        if not m:
            raise SystemExit(f"ERRO: não encontrei 'const {nome}' no HTML antigo.")
        dados[nome] = json.loads(m.group(1))
    carimbo = re.search(r'id="h-data"[^>]*>([^<]*)<', html)
    return dados, (carimbo.group(1).strip() if carimbo else "")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    forcar = "--forcar" in sys.argv
    if len(args) != 1:
        raise SystemExit(__doc__)

    dados, carimbo = extrair(carregar_html(args[0]))
    store.aplicar_lot_ids(dados["LOTS"], store.SAFRA_VERAO)
    store.aplicar_lot_ids(dados["LOTES_COMPRADOS"], store.SAFRA_VERAO)
    store.aplicar_lot_ids(dados["LOTS_INVERNO"], store.SAFRA_INVERNO)

    destino = store.conectar()
    meta, publicado = store.ler_conjuntos(destino)
    if publicado and not forcar:
        raise SystemExit("O banco já tem dados. Use --forcar só se tiver certeza.")

    mudaram = store.publicar(destino, dados, carimbo or "migração inicial", meta_atual=meta)
    print(f"Migração concluída: {len(mudaram)} conjuntos gravados no banco protegido.")

    # conferência: relê do banco e compara com o que saiu do HTML
    _, relido = store.ler_conjuntos(destino)
    for nome in DATASETS:
        # compara o texto serializado (NaN != NaN numa comparação direta)
        if store._js(relido.get(nome)) != store._js(dados[nome]):
            raise SystemExit(f"ERRO na conferência: {nome} não bate com o HTML.")
    print("Conferência OK: o banco tem exatamente os mesmos dados do HTML antigo.")


if __name__ == "__main__":
    main()
