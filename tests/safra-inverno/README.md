# Testes de navegador — Verão + Inverno (branch safra-inverno)

Testam o TSI e o RASTREL com um Firebase **falso, em memória** (`mock-fb.js`).
Nenhum banco real é lido ou gravado.

Pré-requisitos: Python com `playwright` e um Chrome/Chromium.

```
python3 tests/safra-inverno/test_tsi.py     ../estoquetsi/index.html
python3 tests/safra-inverno/test_rastrel.py ../rastrel/index.html
```

A regra do identificador do lote (Python × TSI × RASTREL) é conferida por
`tests/test_regra_id_lote.py` (pytest).
