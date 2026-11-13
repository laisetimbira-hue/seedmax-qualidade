"""E2E do TSI — Safra em operação como contexto visual (branch safra-contexto).
Firebase falso em memória; nada real é lido ou gravado.
Uso: python3 test_tsi_contexto.py /caminho/estoquetsi/index.html"""
import json
import sys
import pathlib
from playwright.sync_api import sync_playwright

HTML = pathlib.Path(sys.argv[1]).resolve()
MOCK = (pathlib.Path(__file__).parent / "mock-fb.js").read_text()
TS = {"__ts": True, "seconds": 1762000000, "nanoseconds": 0}


def ordem(num, cultivar, kg, sobra, **extra):
    d = {"numeroLote": num, "cultivar": cultivar, "quantidadeSementes": kg, "sobraKg": sobra,
         "receitaId": "r1", "receitaNome": "TSI A", "operador": "Celso", "data": "__HOJE__",
         "itensConsumidos": [{"produtoId": "p1", "produtoNome": "Produto A", "quantidade": 2, "unidade": "L"}],
         "lotesDetalhe": [{"origem": "L" + num, "destino": "L" + num, "kg": kg}], "criadoEm": TS}
    d.update(extra)
    return d


ESTADO = {
    "user": {"uid": "u1", "email": "celso@tsiestoque.com"},
    "db": {
        "users": {"u1": {"name": "Celso", "email": "celso@tsiestoque.com", "role": "ADMIN", "active": True}},
        "produtos": {"p1": {"nome": "Produto A", "unidade": "L", "quantidade": 100, "estoqueMinimo": 0, "categoria": "Inseticida"}},
        "receitas": {"r1": {"nome": "TSI A", "itens": [{"produtoId": "p1", "produtoNome": "Produto A", "dosePorKg": 2}]}},
        "lotesTratamento": {
            "old1": ordem("5001", "Zeus", 1000, 10),                                   # antiga, sem safra → Verão
            "v2": ordem("5002", "Orion", 800, 5, safra="SOJA2526", cultura="Soja"),
            "i1": ordem("7101", "TBIO Ello", 600, 3, safra="INV2626", cultura="Trigo"),
            "ab1": ordem("7001", "ANA 01", 500, 0, status="aberta", safra="INV2626", cultura="Cevada", itensConsumidos=[]),
            "ab2": ordem("5003", "Zeus", 700, 0, status="aberta", safra="SOJA2526", cultura="Soja", itensConsumidos=[]),
        },
        "movimentacoes": {
            "m1": {"produtoId": "p1", "produtoNome": "Produto A", "tipo": "saida", "motivo": "Consumo em tratamento de sementes",
                   "quantidade": 2, "data": "__HOJE__", "responsavel": "Celso", "saldoApos": 100, "criadoEm": TS},
            "m2": {"produtoId": "p1", "produtoNome": "Produto A", "tipo": "saida", "motivo": "Consumo em tratamento de sementes",
                   "quantidade": 2, "data": "__HOJE__", "responsavel": "Celso", "saldoApos": 100, "criadoEm": TS,
                   "safra": "INV2626", "cultura": "Trigo"},
            "m3": {"produtoId": "p1", "produtoNome": "Produto A", "tipo": "entrada", "motivo": "Compra",
                   "quantidade": 10, "data": "__HOJE__", "responsavel": "Celso", "saldoApos": 100, "criadoEm": TS},
        },
    },
}

falhas = []


def ok(cond, msg):
    print(("  OK  " if cond else "  FALHOU  ") + msg)
    if not cond:
        falhas.append(msg)


ESTADO_JS = """(() => ({
  topo: document.getElementById('tsiSafraOperacional').value,
  coSafra: document.getElementById('coSafra').value,
  coCultura: document.getElementById('coCultura').value,
  filtro: document.getElementById('lotesSafraFiltro').value,
  historico: [...document.querySelectorAll('#tblLotes tr')].map(tr => tr.children[2] && tr.children[2].textContent.trim()).sort(),
  abertas: [...document.querySelectorAll('#abertasBox b')].map(b => b.textContent).filter(t => /^Ordem /.test(t)).sort(),
  avisoOutras: (document.querySelector('#abertasBox .abertas-outras-safras') || {}).textContent || '',
  sobra: document.getElementById('sobraTotalResumo').textContent,
  centro: (document.getElementById('coPeriodo').value = 'total', renderCentroOperacoes(), lotesFiltrados().map(l => l.numeroLote).sort()),
  vazio: getComputedStyle(document.getElementById('emptyLotes')).display === 'none' ? '' : document.getElementById('emptyLotes').textContent.trim(),
}))()"""


def trocar(pg, sel, valor):
    pg.evaluate("([s,v]) => { const e = document.getElementById(s); e.value = v; e.dispatchEvent(new Event('change')); }", [sel, valor])
    pg.wait_for_timeout(150)


with sync_playwright() as p:
    nav = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx = nav.new_context()
    pg = ctx.new_page()
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))

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

    def abrir():
        pg.goto(HTML.as_uri())
        pg.wait_for_function("document.getElementById('app').style.display==='block'", timeout=10000)
        pg.wait_for_timeout(600)

    abrir()
    ok(not erros, "sem erro de JavaScript ao abrir: " + "; ".join(erros))
    e = pg.evaluate(ESTADO_JS)

    print("— Inverno no topo (padrão)")
    ok(e["topo"] == "INV2626", "Safra em operação começa em Inverno")
    ok(e["coSafra"] == "INV2626" and e["coCultura"] == "todas", "Centro: Safra = Inverno, Cultura = Todas")
    ok(e["centro"] == ["7101"], "Centro conta só as ordens fechadas de Inverno")
    ok(e["filtro"] == "INV2626", "filtro do Tratamento de Lotes começa em Inverno")
    ok(e["historico"] == ["7101"], "histórico mostra só Inverno")
    ok(e["abertas"] == ["Ordem 7001"], "ordens abertas mostram só Inverno")
    ok("+1 ordem aberta em outra safra" in e["avisoOutras"], "aviso da ordem aberta do Verão aparece")
    ok("3 kg" in e["sobra"] and "Inverno" in e["sobra"], "sobra soma só Inverno (3 kg): " + e["sobra"])
    ok(pg.evaluate("sobraAgrupada().reduce((a,x)=>a+x.sobra,0)") == 18, "relatório geral de sobra continua com todas as safras (18 kg)")

    print("— Busca de uma ordem do Verão com Inverno selecionado")
    pg.evaluate("document.getElementById('buscaLotes').value='5001'; renderLotes();")
    v = pg.evaluate(ESTADO_JS)["vazio"]
    ok("Todas as safras" in v, "mensagem orienta a trocar para Todas: " + v)
    pg.evaluate("document.getElementById('buscaLotes').value=''; renderLotes();")

    print("— Troca do topo para Verão")
    trocar(pg, "tsiSafraOperacional", "SOJA2526")
    e = pg.evaluate(ESTADO_JS)
    ok(e["coSafra"] == "SOJA2526" and e["coCultura"] == "todas", "Centro passa para Verão, Cultura = Todas")
    ok(e["centro"] == ["5001", "5002"], "Centro: ordem antiga sem safra conta como Verão")
    ok(e["filtro"] == "SOJA2526" and e["historico"] == ["5001", "5002"], "histórico mostra só Verão (inclui a antiga)")
    ok(e["abertas"] == ["Ordem 5003"] and "+1 ordem aberta" in e["avisoOutras"], "abertas: só Verão + aviso da de Inverno")
    ok("15 kg" in e["sobra"], "sobra soma só Verão (15 kg): " + e["sobra"])

    print("— Consulta manual de Todas as safras")
    trocar(pg, "coSafra", "todas")
    e = pg.evaluate(ESTADO_JS)
    ok(e["centro"] == ["5001", "5002", "7101"], "Centro com Todas as safras mostra as 3 ordens fechadas")
    ok(e["filtro"] == "SOJA2526", "trocar o Centro não mexe no filtro do Tratamento de Lotes")
    pg.evaluate("verAbertasTodasSafras()")
    pg.wait_for_timeout(150)
    e = pg.evaluate(ESTADO_JS)
    ok(e["filtro"] == "todas" and e["historico"] == ["5001", "5002", "7101"], "link 'ver todas as safras' mostra o histórico inteiro")
    ok(e["abertas"] == ["Ordem 5003", "Ordem 7001"] and not e["avisoOutras"], "abertas de todas as safras, sem aviso")
    ok("18 kg" in e["sobra"] and "todas as safras" in e["sobra"], "sobra com todas as safras (18 kg)")
    trocar(pg, "lotesSafraFiltro", "INV2626")
    ok(pg.evaluate(ESTADO_JS)["historico"] == ["7101"], "filtro manual do Tratamento de Lotes funciona (Inverno)")
    ok(pg.evaluate("document.getElementById('tsiSafraOperacional').value") == "SOJA2526", "filtro manual não muda a Safra em operação")

    print("— Nova ordem e Importar PDF herdam a Safra em operação")
    pg.evaluate("document.getElementById('btnNovoLote').click()")
    pg.wait_for_timeout(200)
    ok(pg.evaluate("document.getElementById('lSafra').value") == "SOJA2526", "Nova ordem manual vem com Verão (a do topo)")
    pg.evaluate("document.querySelectorAll('.modal.open, .modal-overlay.open').forEach(m=>m.classList.remove('open'))")
    ok("preencherSafraCultura(document.getElementById('pdfSafra'), document.getElementById('pdfCultura'), safraOperacional" in HTML.read_text(),
       "Importar PDF continua preenchendo a safra com a Safra em operação")

    print("— Telas gerais não filtram por safra")
    pg.evaluate("document.querySelector('.nav-item[data-section=\"movimentacoes\"]').click()")
    pg.wait_for_timeout(200)
    ok(pg.evaluate("document.querySelectorAll('#tblMov tr, #tblMovimentacoes tr').length") >= 3, "Movimentações mostra todas (3)")
    ok(pg.evaluate("__DB.produtos.p1.quantidade") == 100, "saldo do produto inalterado")

    print("— Reabrir o app mantém o contexto")
    abrir()
    e = pg.evaluate(ESTADO_JS)
    ok(e["topo"] == "SOJA2526" and e["coSafra"] == "SOJA2526" and e["filtro"] == "SOJA2526", "ao reabrir, o contexto continua Verão")

    ok(pg.evaluate("window.__WRITES.length") == 0, "nenhuma gravação no banco em todo o fluxo")
    ok(not erros, "sem erros de JavaScript no fluxo: " + "; ".join(erros))
    nav.close()

print("\nRESULTADO:", "TUDO OK" if not falhas else f"{len(falhas)} FALHA(S)")
sys.exit(1 if falhas else 0)
