"""Identificação de empresas no Beneficiamento de Inverno."""

import unicodedata


def normalizar(texto):
    texto = str(texto or "").strip().upper()
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def identificar_empresa(nome_aba):
    aba = normalizar(nome_aba)

    if aba == "PGW":
        return "PGW"

    if aba == "AMBEV":
        return "AMBEV"

    return None


def separar_linhas(linhas):
    resultado = {
        "producao_propria": [],
        "PGW": [],
        "AMBEV": [],
        "outras_abas": [],
    }

    for linha in linhas:
        empresa = identificar_empresa(linha.get("aba"))

        if empresa:
            resultado[empresa].append(dict(linha))
        elif normalizar(linha.get("aba")) == "INVERNO 2026":
            resultado["producao_propria"].append(dict(linha))
        else:
            resultado["outras_abas"].append(dict(linha))

    return resultado
