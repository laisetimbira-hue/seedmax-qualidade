"""E2E do TSI (branch safra-inverno) com Firebase falso em memória.
Uso: python3 test_tsi.py /caminho/estoquetsi/index.html"""
import json
import sys
import pathlib
from playwright.sync_api import sync_playwright

HTML = pathlib.Path(sys.argv[1]).resolve()
MOCK = (pathlib.Path(__file__).parent / "mock-fb.js").read_text()
TS_OLD = {"__ts": True, "seconds": 1762000000, "nanoseconds": 0}
HOJE_ISO = None

ESTADO = {
    "user": {"uid": "u1", "email": "celso@tsiestoque.com"},
    "db": {
        "users": {"u1": {"name": "Celso", "email": "celso@tsiestoque.com", "role": "ADMIN", "active": True}},
        "produtos": {
            "p1": {"nome": "Produto A", "unidade": "L", "quantidade": 100, "estoqueMinimo": 0, "categoria": "Inseticida"},
            "p2": {"nome": "Produto B", "unidade": "kg", "quantidade": 50.5, "estoqueMinimo": 0, "categoria": "Fungicida"},
        },
        "receitas": {"r1": {"nome": "TSI A", "itens": [{"produtoId": "p1", "produtoNome": "Produto A", "dosePorKg": 2}]}},
        "lotesTratamento": {
            # ordem ANTIGA de soja: sem safra/cultura
            "old1": {"numeroLote": "5001", "cultivar": "Zeus", "quantidadeSementes": 1000, "sobraKg": 0,
                     "receitaId": "r1", "receitaNome": "TSI A", "operador": "Celso", "data": "__HOJE__",
                     "itensConsumidos": [{"produtoId": "p1", "produtoNome": "Produto A", "quantidade": 2, "unidade": "L"}],
                     "lotesDetalhe": [{"origem": "26S100A", "destino": "26S100A", "kg": 1000}], "criadoEm": TS_OLD},
            # ordem aberta de Inverno importada (Cevada)
            "ab1": {"status": "aberta", "numeroLote": "7001", "cultivar": "ANA 01", "quantidadeSementes": 500,
                    "data": "__HOJE__", "receitaNome": "TSI A", "tratamentoPdf": "TSI A", "safra": "INV2626", "cultura": "Cevada",
                    "lotesDetalhe": [{"origem": "27CV01", "destino": "27CV01", "sourceLotCode": "27CV01",
                                      "sourceLotId": "INV2626_CEVADA_27CV01", "treatedLotCode": "27CV01",
                                      "treatedLotId": "INV2626_CEVADA_27CV01"}],
                    "sobraKg": 0, "itensConsumidos": [], "operador": "", "criadoEm": TS_OLD, "importadoEm": TS_OLD},
        },
        "movimentacoes": {
            "m_old": {"produtoId": "p1", "produtoNome": "Produto A", "tipo": "saida", "motivo": "Consumo em tratamento de sementes",
                      "quantidade": 2, "data": "__HOJE__", "observacoes": "Ordem 5001 — Zeus (receita: TSI A)", "responsavel": "Celso",
                      "saldoApos": 100, "criadoEm": TS_OLD},
            "m_emp": {"produtoId": "p2", "produtoNome": "Produto B", "tipo": "saida", "motivo": "Empréstimo", "quantidade": 1,
                      "data": "__HOJE__", "responsavel": "Celso", "saldoApos": 50.5, "criadoEm": TS_OLD,
                      "emprestimo": {"id": "m_emp", "entregador": "Celso", "recebedor": "Fulano", "empresa": "Vizinho",
                                     "previsaoDevolucao": "", "finalidade": "teste", "unidade": "kg"}},
        },
    },
}

falhas = []


def ok(cond, msg):
    print(("  OK  " if cond else "  FALHOU  ") + msg)
    if not cond:
        falhas.append(msg)


with sync_playwright() as p:
    nav = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = nav.new_page()
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    dialogos = []
    def _dlg(d):
        dialogos.append(d.message); d.accept()
    pg.on("dialog", _dlg)

    def rota(route):
        url = route.request.url
        if "firebase-app-compat" in url:
            est = json.dumps(ESTADO)
            return route.fulfill(content_type="application/javascript",
                                 body="(function(){const H=new Date();const hoje=H.getFullYear()+'-'+String(H.getMonth()+1).padStart(2,'0')+'-'+String(H.getDate()).padStart(2,'0');"
                                      "window.__MOCK=JSON.parse(" + json.dumps(est) + ".split('__HOJE__').join(hoje));})();\n" + MOCK)
        if url.startswith("file://"):
            return route.continue_()
        return route.fulfill(content_type="application/javascript", body="")
    pg.route("**/*", rota)
    pg.goto(HTML.as_uri())
    pg.wait_for_function("document.getElementById('app').style.display==='block'", timeout=10000)
    pg.wait_for_timeout(600)
    ok(not erros, "sem erro de JavaScript ao abrir: " + "; ".join(erros))

    # 11/12 — nada é gravado só por abrir
    ok(pg.evaluate("window.__WRITES.length") == 0, "abrir o app não grava nada (nenhum dado antigo atualizado)")
    # 3 — estoque inalterado
    ok(pg.evaluate("[__DB.produtos.p1.quantidade, __DB.produtos.p2.quantidade]") == [100, 50.5], "saldos dos produtos inalterados")
    ok(pg.evaluate("document.getElementById('tsiSafraOperacional').value") == "INV2626", "safra em operação padrão = Inverno")

    # 1 — ordem antiga aparece
    pg.evaluate("document.querySelector('.nav-item[data-section=\"lotes\"]').click()")
    pg.wait_for_timeout(200)
    ok("5001" in pg.inner_text("#tblLotes"), "ordem antiga de soja (sem safra) aparece na lista de ordens")
    ok("Inverno" in pg.inner_text("#abertasBox") and "Cevada" in pg.inner_text("#abertasBox"), "ordem aberta de Inverno mostra o selo Inverno · Cevada")

    # Centro de Operações — filtros
    pg.evaluate("document.querySelector('.nav-item[data-section=\"centro\"]').click()")
    pg.select_option("#coPeriodo", "total")
    pg.wait_for_timeout(200)
    ok("5001" in pg.inner_text("#coLotes"), "Centro (Todas) mostra a ordem antiga")
    pg.select_option("#coSafra", "SOJA2526"); pg.wait_for_timeout(150)
    ok("5001" in pg.inner_text("#coLotes"), "Centro (Verão) mostra a ordem antiga de soja")
    ok("Soja" in pg.evaluate("[...document.getElementById('coCultura').options].map(o=>o.text).join(',')"), "cultura do Verão = Soja")
    pg.select_option("#coSafra", "INV2626"); pg.wait_for_timeout(150)
    ok("5001" not in pg.inner_text("#coLotes"), "Centro (Inverno) NÃO mostra a ordem de soja")
    movs_inv = pg.evaluate("movsFiltradas().map(m=>m.id)")
    ok("m_old" not in movs_inv and "m_emp" in movs_inv, "Inverno: consumo antigo de soja sai, empréstimo (estoque único) continua")
    pg.select_option("#coSafra", "todas"); pg.wait_for_timeout(150)

    # 4 — nova ordem manual de Inverno (Trigo)
    pg.evaluate("document.querySelector('.nav-item[data-section=\"lotes\"]').click()")
    pg.click("#btnNovoLote")
    ok(pg.evaluate("document.getElementById('lSafra').value") == "INV2626", "modal novo: safra = Inverno (contexto)")
    pg.select_option("#lCultura", "Trigo")
    ok(pg.evaluate("getComputedStyle(document.getElementById('lCultivar')).display") == "none", "Inverno: lista de cultivares de soja escondida")
    pg.fill("#lCultivarManual", "TBIO CALIBRE")
    pg.fill("#lLote", "8001")
    pg.fill("#lQuantidade", "1000"); pg.dispatch_event("#lQuantidade", "input")
    pg.select_option("#lReceita", "r1"); pg.dispatch_event("#lReceita", "change")
    pg.fill("#lOperador", "Celso")
    pg.fill("#lLotesLista input[aria-label='Lote de origem']", "27ab001")
    pg.click("#btnSalvarLote")
    pg.wait_for_timeout(400)
    nova = pg.evaluate("Object.values(__DB.lotesTratamento).find(o=>o.numeroLote==='8001')")
    ok(nova and nova["safra"] == "INV2626" and nova["cultura"] == "Trigo", "nova ordem grava safra INV2626 + cultura Trigo")
    ok(nova and nova["lotesDetalhe"][0]["sourceLotId"] == "INV2626_TRIGO_27AB001", "lote da ordem: INV2626_TRIGO_27AB001")
    ok(nova and nova["sourceLotIds"] == ["INV2626_TRIGO_27AB001"], "sourceLotIds da ordem com a identidade nova")
    mv = pg.evaluate("Object.values(__DB.movimentacoes).filter(m=>String(m.observacoes||'').startsWith('Ordem 8001'))")
    ok(len(mv) == 1 and mv[0]["safra"] == "INV2626" and mv[0]["cultura"] == "Trigo", "saída automática de consumo grava safra/cultura")
    ok(pg.evaluate("__DB.produtos.p1.quantidade") == 98, "baixa do estoque igual à lógica atual (100 − 2 L)")
    ok(pg.evaluate("__DB.produtos.p2.quantidade") == 50.5, "produto fora da receita não muda")
    ok(pg.evaluate("__DB.lotesTratamento.old1.safra") is None, "ordem antiga continua sem safra no banco")

    # nova ordem de Verão (troca de contexto) — ID histórico
    pg.select_option("#tsiSafraOperacional", "SOJA2526")
    pg.click("#btnNovoLote")
    ok(pg.evaluate("document.getElementById('lCultura').value") == "Soja" and pg.evaluate("document.getElementById('lCultura').disabled"), "Verão: cultura fixa = Soja")
    pg.fill("#lLote", "8002"); pg.fill("#lQuantidade", "500"); pg.dispatch_event("#lQuantidade", "input")
    pg.select_option("#lReceita", "r1"); pg.dispatch_event("#lReceita", "change")
    pg.fill("#lLotesLista input[aria-label='Lote de origem']", "26S200A")
    pg.click("#btnSalvarLote"); pg.wait_for_timeout(400)
    v = pg.evaluate("Object.values(__DB.lotesTratamento).find(o=>o.numeroLote==='8002')")
    ok(v and v["safra"] == "SOJA2526" and v["cultura"] == "Soja" and v["lotesDetalhe"][0]["sourceLotId"] == "SOJA2526_26S200A",
       "ordem nova de Verão: SOJA2526 / Soja / SOJA2526_26S200A (ID histórico)")

    # fechar ordem aberta de Inverno: mantém a safra/cultura da ordem
    pg.evaluate("fecharOrdem('ab1')"); pg.wait_for_timeout(200)
    ok(pg.evaluate("[document.getElementById('lSafra').value, document.getElementById('lCultura').value, document.getElementById('lSafra').disabled]") == ["INV2626", "Cevada", True],
       "fechar ordem: safra/cultura da ordem, bloqueadas")
    pg.fill("#lOperador", "Celso"); pg.click("#btnSalvarLote"); pg.wait_for_timeout(400)
    f = pg.evaluate("__DB.lotesTratamento.ab1")
    ok(f["status"] == "fechada" and f["safra"] == "INV2626" and f["cultura"] == "Cevada" and f["lotesDetalhe"][0]["sourceLotId"] == "INV2626_CEVADA_27CV01",
       "ordem de Inverno fechada mantém INV2626 / Cevada / INV2626_CEVADA_27CV01")

    # Centro: filtros combinados + relatório
    pg.evaluate("document.querySelector('.nav-item[data-section=\"centro\"]').click()")
    pg.select_option("#coPeriodo", "total"); pg.select_option("#coSafra", "INV2626"); pg.wait_for_timeout(100)
    pg.select_option("#coCultura", "Trigo"); pg.wait_for_timeout(150)
    txt = pg.inner_text("#coLotes")
    ok("8001" in txt and "7001" not in txt and "5001" not in txt, "Centro Inverno + Trigo: só a ordem de Trigo")
    pg.select_option("#coCultivar", "TBIO CALIBRE"); pg.wait_for_timeout(100)
    ok("8001" in pg.inner_text("#coLotes"), "filtro de cultivar atua junto com Safra/Cultura")
    pg.evaluate("window.print=()=>{}")
    pg.click("#btnRelatorioCO"); pg.wait_for_timeout(200)
    rel = pg.inner_text("#printReport")
    ok("Safra" in rel and "Inverno 26/26" in rel and "Trigo" in rel and "8001" in rel and "5001" not in rel, "Emitir Relatório mostra e respeita Safra/Cultura")
    pg.select_option("#coSafra", "todas"); pg.wait_for_timeout(100)
    pg.select_option("#coCultura", "todas"); pg.wait_for_timeout(100)
    pg.select_option("#coCultivar", "todas"); pg.wait_for_timeout(100)
    pg.click("#btnRelatorioCO"); pg.wait_for_timeout(200)
    rel2 = pg.inner_text("#printReport")
    ok("5001" in rel2 and "8001" in rel2 and "8002" in rel2, "relatório com Todas: Verão + Inverno")

    # importação de PDF: Safra + Cultura escolhidas antes do arquivo
    pg.evaluate("document.querySelector('.nav-item[data-section=\"lotes\"]').click()")
    pg.select_option("#tsiSafraOperacional", "INV2626")
    pg.evaluate("""() => { window.lerLinhasPdf = async (f) => f.name.startsWith('soja') ? [
      'ORDEM DE TRATAMENTO DE SEMENTES', 'Ordem: 9002 Produtor: Fulano', 'Cultivar: Zeus', 'Tratamento: TSI A', 'Data: 13/11/2026',
      '26S300B 26S300B 1.000,00 190,00 5,0M 1,00 1,00 1.000,00', 'Resumo: 1.000,00'] : [
      'ORDEM DE TRATAMENTO DE SEMENTES', 'Ordem: 9001 Produtor: Fulano', 'Cultivar: TBIO CALIBRE', 'Tratamento: TSI A', 'Data: 13/11/2026',
      '27ab009 27ab009 1.000,00 38,00 5,0M 1,00 1,00 1.000,00', 'Resumo: 1.000,00']; }""")
    pg.click("#btnNovoImportPdf")
    ok(pg.evaluate("document.getElementById('pdfSafra').value") == "INV2626", "importar PDF: safra vem do contexto (Inverno)")
    pg.select_option("#pdfCultura", "Trigo")
    with pg.expect_file_chooser() as fc:
        pg.click("#btnEscolherPdf")
    fc.value.set_files([{"name": "trigo.pdf", "mimeType": "application/pdf", "buffer": b"%PDF"},
                        {"name": "soja.pdf", "mimeType": "application/pdf", "buffer": b"%PDF"}])
    pg.wait_for_timeout(600)
    o9 = pg.evaluate("Object.values(__DB.lotesTratamento).find(o=>o.numeroLote==='9001')")
    ok(o9 and o9["status"] == "aberta" and o9["safra"] == "INV2626" and o9["cultura"] == "Trigo"
       and o9["lotesDetalhe"][0]["sourceLotId"] == "INV2626_TRIGO_27AB009", "ordem importada por PDF grava INV2626 / Trigo / INV2626_TRIGO_27AB009")
    ok(any("cultivar de SOJA" in d for d in dialogos), "PDF com cultivar de soja importado como Inverno pede confirmação")
    ok(pg.evaluate("__DB.produtos.p1.quantidade") == 98 - 1 - 1, "importar PDF não baixa estoque (só o fechamento da ab1 baixou)")

    # 10 — Termo de Empréstimo continua funcionando
    pg.evaluate("termoEmprestimoDoHistorico('m_emp')"); pg.wait_for_timeout(200)
    termo = pg.evaluate("document.getElementById('printReport').innerText")
    ok("Fulano" in termo, "Termo de Empréstimo gerado a partir do histórico")
    ok(not erros, "sem erros de JavaScript no fluxo: " + "; ".join(erros))
    nav.close()

print("\nRESULTADO:", "TUDO OK" if not falhas else f"{len(falhas)} falha(s)")
sys.exit(1 if falhas else 0)
