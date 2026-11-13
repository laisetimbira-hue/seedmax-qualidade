"""E2E do RASTREL (branch safra-inverno) com Firebase falso em memória.
Uso: python3 test_rastrel.py /caminho/rastrel/index.html"""
import json
import sys
import pathlib
from playwright.sync_api import sync_playwright

HTML = pathlib.Path(sys.argv[1]).resolve()
MOCK = (pathlib.Path(__file__).parent / "mock-fb.js").read_text()
TS = {"__ts": True, "seconds": 1762000000, "nanoseconds": 0}


def bag(i, lote, loc, epc=True, extra=None):
    b = {"epc": ("E%s%02d" % (lote, i)) if epc else None, "numero_bag": "%s-%02d" % (lote, i), "lote": lote,
         "cultivar_id": "zeus", "cultivar_nome": "55I57RSF IPRO — Zeus", "categoria": "S1", "peneira": "P1",
         "peso_kg": 1000, "tratamento": "TSI A", "produtor": "", "localizacao_atual": loc, "slot_posicao": 0,
         "status": "em_estoque", "criado_em": TS, "atualizado_em": TS}
    b.update(extra or {})
    return b


BAGS = {}
for i in range(1, 4):
    BAGS["old%d" % i] = bag(i, "26S01A", "A3B11")          # bags ANTIGOS de soja: sem safra/cultura
for i in range(1, 3):
    BAGS["oldB%d" % i] = bag(i, "26S02B", "A3B12")
ESTADO = {"user": {"uid": "u1", "email": "op@rastrel.com"},
          "db": {"bags": BAGS, "users": {"u1": {"name": "Op", "email": "op@rastrel.com", "role": "ADMIN", "active": True}},
                 "movimentacoes": {}}}
falhas = []


def ok(cond, msg):
    print(("  OK  " if cond else "  FALHOU  ") + msg)
    if not cond:
        falhas.append(msg)


with sync_playwright() as p:
    nav = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = nav.new_page(viewport={"width": 1280, "height": 900})
    erros = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    pg.on("dialog", lambda d: d.accept())

    def rota(route):
        url = route.request.url
        if "firebase-app-compat" in url:
            return route.fulfill(content_type="application/javascript",
                                 body="window.__MOCK=" + json.dumps(ESTADO) + ";\n" + MOCK)
        if url.startswith("file://") or url.startswith("about:"):
            return route.continue_()
        return route.fulfill(content_type="application/javascript", body="")
    pg.route("**/*", rota)
    pg.goto(HTML.as_uri())
    pg.wait_for_function("window.rastrelDb && typeof db !== 'undefined' && db", timeout=15000)
    pg.wait_for_timeout(800)
    ok(not erros, "sem erro de JavaScript ao abrir: " + "; ".join(erros[:3]))
    escritas_ini = pg.evaluate("window.__WRITES.filter(w=>w.path.startsWith('bags/')).length")
    ok(escritas_ini == 0, "abrir o app não grava nada nos bags existentes")

    # ---- Lotes
    pg.evaluate("goTab('lotes')"); pg.wait_for_timeout(300)
    pg.evaluate("carregarLotes()"); pg.wait_for_timeout(300)
    ok(pg.evaluate("document.getElementById('ltSafra').value") == "INV2626", "novo lote: safra padrão = Inverno")
    lista = pg.inner_text("#lotesLista")
    ok("26S01A" in lista and "26S02B" in lista, "bags antigos (sem safra) aparecem na tela de lotes")

    # mesmo número de lote já usado na soja → bloqueado no Inverno
    pg.select_option("#ltCultura", "Trigo")
    pg.fill("#ltNumero", "26S01A"); pg.fill("#ltCultivar", "TBIO CALIBRE"); pg.fill("#ltQtd", "2")
    pg.evaluate("criarLote()"); pg.wait_for_timeout(400)
    ok(pg.evaluate("Object.keys(__DB.bags).length") == 5, "número de lote da soja NÃO é reaproveitado no Inverno (bloqueado)")

    # 5 — novo lote de Inverno
    pg.fill("#ltNumero", "27ab001"); pg.fill("#ltCultivar", "TBIO CALIBRE"); pg.fill("#ltQtd", "2")
    pg.select_option("#ltLocalizacao", "A3B13")
    pg.evaluate("criarLote()"); pg.wait_for_timeout(500)
    novos = pg.evaluate("Object.values(__DB.bags).filter(b=>b.lote==='27AB001')")
    ok(len(novos) == 2, "2 bags criados para o lote 27AB001")
    ok(all(b["safra"] == "INV2626" and b["cultura"] == "Trigo" and b["lotId"] == "INV2626_TRIGO_27AB001" for b in novos),
       "cada bag novo guarda safra INV2626, cultura Trigo e lotId INV2626_TRIGO_27AB001")
    ok(all(b["numero_bag"].startswith("27AB001-") and b["status"] == "aguardando_tag" and b["localizacao_atual"] == "A3B13" for b in novos),
       "demais campos do bag como antes (numero_bag, status, posição)")
    antigos = pg.evaluate("['old1','old2','old3','oldB1','oldB2'].map(k=>__DB.bags[k])")
    ok(all("safra" not in b and "cultura" not in b for b in antigos), "bags antigos continuam sem safra/cultura no banco")
    ok(pg.evaluate("window.__WRITES.filter(w=>w.path.startsWith('bags/old')).length") == 0, "nenhuma gravação nos bags antigos")

    # filtros na tela de lotes
    pg.evaluate("carregarLotes()"); pg.wait_for_timeout(300)
    t = pg.inner_text("#lotesLista")
    ok("27AB001" in t and "26S01A" in t and "Inverno" in t, "Todas: Verão + Inverno; lote de Inverno com selo")
    pg.select_option("#lfSafra", "INV2626"); pg.wait_for_timeout(400)
    t = pg.inner_text("#lotesLista")
    ok("27AB001" in t and "26S01A" not in t, "filtro Inverno na tela de lotes")
    pg.select_option("#lfCultura", "Cevada"); pg.wait_for_timeout(400)
    ok("27AB001" not in pg.inner_text("#lotesLista"), "filtro Inverno + Cevada esconde o lote de Trigo")
    pg.select_option("#lfSafra", "SOJA2526"); pg.wait_for_timeout(400)
    t = pg.inner_text("#lotesLista")
    ok("26S01A" in t and "27AB001" not in t, "filtro Verão: bags antigos (lidos como SOJA2526/Soja)")

    # ---- Estoque / dashboard
    pg.evaluate("goTab('dashboard')"); pg.wait_for_timeout(300)
    pg.evaluate("carregarDashboard()"); pg.wait_for_timeout(400)
    ok(pg.inner_text("#kTotal").strip() == "7", "Estoque (Todas): 7 bags")
    pg.select_option("#dfSafra", "INV2626"); pg.wait_for_timeout(500)
    ok(pg.inner_text("#kTotal").strip() == "2", "Estoque (Inverno): 2 bags")
    pg.select_option("#dfSafra", "SOJA2526"); pg.wait_for_timeout(500)
    ok(pg.inner_text("#kTotal").strip() == "5" and pg.inner_text("#kEstoque").strip() == "5", "Estoque (Verão): 5 bags antigos em estoque")
    pg.select_option("#dfSafra", ""); pg.wait_for_timeout(400)

    # ---- Mapa (iframe): padrão = todas as safras; filtro só destaca
    pg.evaluate("goTab('mapa')"); pg.wait_for_timeout(800)
    fr = pg.frame_locator("iframe[title='Mapa de Bags']")
    fr.locator("#fntTag").click(); pg.wait_for_timeout(800)
    frame = [f for f in pg.frames if f != pg.main_frame][0]
    ok(frame.evaluate("document.getElementById('fSafra').value") == "", "mapa: padrão = Todas as safras")
    total_slots = frame.evaluate("document.querySelectorAll('.slot.live').length")
    dims = frame.evaluate("document.querySelectorAll('.slot.dim').length")
    ok(total_slots >= 3 and dims == 0, f"mapa (Todas): Verão + Inverno juntos, nada apagado ({total_slots} pilhas)")
    frame.select_option("#fSafra", "INV2626"); pg.wait_for_timeout(300)
    m = frame.evaluate("[...document.querySelectorAll('.slot.match')].map(s=>s.textContent).join('|')")
    d = frame.evaluate("document.querySelectorAll('.slot.dim').length")
    ok("27AB001" in m and "26S01A" not in m and d >= 2, "mapa filtro Inverno: destaca o lote de Inverno e esmaece a soja")
    ok(frame.evaluate("document.querySelectorAll('.slot.live').length") == total_slots, "mapa: filtro não muda posições/slots (mesma quantidade de pilhas)")
    frame.select_option("#fSafra", ""); pg.wait_for_timeout(300)
    ok(frame.evaluate("document.querySelectorAll('.slot.dim').length") == 0, "mapa volta para Todas sem esmaecer nada")
    ok(pg.evaluate("window.__WRITES.filter(w=>w.path.startsWith('bags/old')).length") == 0, "ainda nenhuma gravação nos bags antigos")
    ok(not erros, "sem erros de JavaScript no fluxo: " + "; ".join(erros[:3]))
    nav.close()

print("\nRESULTADO:", "TUDO OK" if not falhas else f"{len(falhas)} falha(s)")
sys.exit(1 if falhas else 0)
