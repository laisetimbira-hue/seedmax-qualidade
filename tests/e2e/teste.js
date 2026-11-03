// Uso local (precisa do banco exportado em pasta, NUNCA versionar):
//   SEEDMAX_DESTINO=pasta:<dir>/banco python scripts/migrar_do_html.py <index_antigo.html>
//   servir o index antigo em :8001 e este em :8002, e: node tests/e2e/teste.js <dir>
//   (<dir>/node_modules com leaflet, leaflet.markercluster, papaparse, html2canvas; <dir>/e2e/mock-firebase.js)
// Teste ponta a ponta: versão nova (protegida) x versão atual.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const S = process.argv[2];
const NM = path.join(S, 'node_modules');
const banco = path.join(S, 'banco');

const qualidade = {};
for (const f of fs.readdirSync(banco)) qualidade[f.replace(/\.json$/, '')] = JSON.parse(fs.readFileSync(path.join(banco, f), 'utf8'));
const ESTADO = {
  contas: {
    'qual@x.com': { senha: 'Senha#123', uid: 'u-qual' },
    'visu@x.com': { senha: 'Senha#123', uid: 'u-visu' },
    'ina@x.com': { senha: 'Senha#123', uid: 'u-ina' },
    'tsi@x.com': { senha: 'Senha#123', uid: 'u-tsi' },
    'estranho@x.com': { senha: 'Senha#123', uid: 'u-estranho' },
    'bloq@x.com': { senha: 'Senha#123', uid: 'u-bloq', disabled: true },
  },
  users: {
    'u-qual': { name: 'Quali Teste', email: 'qual@x.com', role: 'QUALIDADE', active: true },
    'u-visu': { name: 'Visu Teste', email: 'visu@x.com', role: 'VISUALIZACAO', active: true },
    'u-ina': { name: 'Inativo', email: 'ina@x.com', role: 'ADMIN', active: false },
    'u-tsi': { name: 'TSI', email: 'tsi@x.com', role: 'TSI', active: true },
  },
  qualidade,
};
const mock = 'window.__MOCK_ESTADO = ' + JSON.stringify(ESTADO) + ';\n' + fs.readFileSync(path.join(S, 'e2e/mock-firebase.js'), 'utf8');
const LIBS = {
  'leaflet.min.js': 'leaflet/dist/leaflet.js', 'leaflet.min.css': 'leaflet/dist/leaflet.css',
  'leaflet.markercluster.min.js': 'leaflet.markercluster/dist/leaflet.markercluster.js',
  'MarkerCluster.css': 'leaflet.markercluster/dist/MarkerCluster.css', 'MarkerCluster.Default.css': 'leaflet.markercluster/dist/MarkerCluster.Default.css',
  'papaparse.min.js': 'papaparse/papaparse.min.js', 'html2canvas.min.js': 'html2canvas/dist/html2canvas.min.js',
};

let falhas = 0;
const ok = (cond, msg) => { console.log((cond ? '  ✔ ' : '  ✘ ') + msg); if (!cond) falhas++; };

async function abrir(browser, url) {
  const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await ctx.newPage();
  const erros = [];
  page.on('pageerror', e => erros.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|ERR_|net::/.test(m.text())) erros.push('console: ' + m.text()); });
  await ctx.route('**/*', route => {
    const u = route.request().url();
    if (u.startsWith('http://localhost')) return route.continue();
    if (u.includes('firebase-app-compat.js')) return route.fulfill({ body: mock, contentType: 'application/javascript' });
    if (u.includes('gstatic.com/firebasejs')) return route.fulfill({ body: '', contentType: 'application/javascript' });
    const nome = Object.keys(LIBS).find(k => u.endsWith('/' + k));
    if (nome) return route.fulfill({ path: path.join(NM, LIBS[nome]) });
    return route.abort(); // fontes do Google e mapas (tiles) — iguais para as duas versões
  });
  await page.goto(url);
  return { ctx, page, erros };
}

async function entrarNovo(page, email, senha) {
  await page.waitForSelector('#email-input', { state: 'visible' });
  await page.fill('#email-input', email);
  await page.fill('#pw-input', senha);
  await page.click('#login-form .sml-btn');
}
const bloqueado = (page) => page.evaluate(() => ({
  locked: document.body.classList.contains('locked'),
  temLOTS: (() => { try { return typeof LOTS !== 'undefined'; } catch (e) { return false; } })(),
  erro: document.getElementById('login-error').textContent,
  loginVisivel: getComputedStyle(document.getElementById('login-screen')).display !== 'none',
}));

async function textoDasAbas(page, prefixo) {
  const out = {};
  const verao = ['overview', 'mapa', 'beneficiamento', 'cultivares', 'lotes', 'comprados', 'plantio'];
  for (const p of verao) {
    await page.evaluate(() => { mapaUnlocked = true; });
    await page.click(`.tab[onclick="showPage('${p}')"]`);
    await page.waitForTimeout(p === 'mapa' ? 1500 : 400);
    out['verao-' + p] = await page.evaluate(p => {
      const el = document.getElementById('page-' + p); return el ? el.innerText.replace(/\s+/g, ' ').trim() : null;
    }, p);
  }
  out['header'] = await page.evaluate(() => ['h-kg', 'h-lotes', 'h-cultivares', 'h-data'].map(i => document.getElementById(i).textContent).join(' | '));
  await page.evaluate(() => trocarSafra('inverno'));
  await page.waitForTimeout(400);
  for (const p of ['overview', 'lotes', 'cultivares', 'comprados', 'beneficiamento', 'plantio']) {
    await page.click(`.tab[onclick="showPageInverno('${p}')"]`);
    await page.waitForTimeout(300);
    out['inverno-' + p] = await page.evaluate(p => { const el = document.getElementById('page-inverno-' + p); return el ? el.innerText.replace(/\s+/g, ' ').trim() : null; }, p);
  }
  await page.evaluate(() => trocarSafra('verao'));
  await page.screenshot({ path: path.join(S, 'e2e', prefixo + '-final.png') });
  return out;
}

(async () => {
  const browser = await chromium.launch();
  const NOVO = 'http://localhost:8002/index.html';
  const VELHO = 'http://localhost:8001/index.html';

  console.log('\n1. Sem login');
  let { ctx, page, erros } = await abrir(browser, NOVO);
  await page.waitForSelector('#email-input', { state: 'visible' });
  let b = await bloqueado(page);
  ok(b.locked && b.loginVisivel && !b.temLOTS, 'área interna trancada e nenhum dado na memória da página');
  const html = await page.content();
  ok(!/const LOTS = \[/.test(html) && !/"lote":/.test(html), 'HTML entregue não contém lotes');
  ok((await page.evaluate(() => __MOCK_LEITURAS.filter(l => l.col === 'qualidade').length)) === 0, 'nenhuma leitura de dados foi tentada sem login');
  await page.evaluate(() => { try { buildLotes(); } catch (e) {} });
  ok(!(await bloqueado(page)).temLOTS, 'chamar funções da área interna pelo console não traz dados');
  await page.screenshot({ path: path.join(S, 'e2e', 'novo-login.png') });
  ok(erros.length === 0, 'console sem erros na tela de login' + (erros.length ? ' → ' + erros.join(' / ') : ''));

  console.log('\n2. Senha errada / conta desativada no Auth');
  await entrarNovo(page, 'qual@x.com', 'errada');
  await page.waitForTimeout(300);
  b = await bloqueado(page); ok(b.locked && /não conferem/.test(b.erro), 'senha errada recusada: "' + b.erro + '"');
  await entrarNovo(page, 'bloq@x.com', 'Senha#123');
  await page.waitForTimeout(300);
  b = await bloqueado(page); ok(b.locked && /desativada/.test(b.erro), 'conta desativada no Auth recusada: "' + b.erro + '"');

  console.log('\n3. Logado mas sem cadastro autorizado / inativo / perfil sem acesso');
  for (const [email, esperado] of [['estranho@x.com', /não tem acesso liberado/], ['ina@x.com', /desativada/], ['tsi@x.com', /não tem acesso à Gestão de Qualidade/]]) {
    await entrarNovo(page, email, 'Senha#123');
    await page.waitForFunction(() => document.getElementById('login-error').style.display === 'block' && document.getElementById('login-error').textContent.length > 0);
    b = await bloqueado(page);
    const sessao = await page.evaluate(() => localStorage.getItem('mockAuthUid'));
    ok(b.locked && !b.temLOTS && esperado.test(b.erro) && !sessao, `${email}: bloqueado e deslogado — "${b.erro}"`);
    await page.evaluate(() => document.getElementById('login-error').style.display = 'none');
  }
  ok(erros.length === 0, 'console sem erros nas tentativas bloqueadas' + (erros.length ? ' → ' + erros.join(' / ') : ''));
  await ctx.close();

  console.log('\n4. Versão atual (referência) x versão nova com usuário QUALIDADE');
  ({ ctx, page, erros } = await abrir(browser, VELHO));
  await page.fill('#pw-input', 'soja2026'); await page.click('.sml-btn');
  await page.waitForTimeout(1500);
  const errosVelho = erros;
  const ref = await textoDasAbas(page, 'velho');
  await ctx.close();

  ({ ctx, page, erros } = await abrir(browser, NOVO));
  await entrarNovo(page, 'qual@x.com', 'Senha#123');
  await page.waitForFunction(() => !document.body.classList.contains('locked'), null, { timeout: 15000 });
  await page.waitForTimeout(1500);
  b = await bloqueado(page); ok(!b.locked && !b.loginVisivel && b.temLOTS, 'login válido abre o dashboard');
  const novo = await textoDasAbas(page, 'novo');
  for (const k of Object.keys(ref)) {
    const igual = ref[k] === novo[k];
    let det = '';
    if (!igual) { let i = 0; while (i < ref[k].length && ref[k][i] === (novo[k] || '')[i]) i++; det = ` → difere em ${i}: velho="${ref[k].slice(i - 30, i + 60)}" novo="${(novo[k] || '').slice(i - 30, i + 60)}"`; }
    ok(igual, `aba ${k}: conteúdo idêntico (${(ref[k] || '').length} caracteres)` + det);
  }
  const soNovos = erros.filter(e => !errosVelho.includes(e));
  ok(soNovos.length === 0, 'nenhum erro de console novo em relação à versão atual' + (soNovos.length ? ' → ' + soNovos.join(' / ') : '') + ` (versão atual tem ${errosVelho.length})`);

  console.log('\n5. Sessão, atualização automática e logout');
  await page.reload();
  await page.waitForFunction(() => !document.body.classList.contains('locked'), null, { timeout: 15000 });
  ok(true, 'recarregar a página mantém a sessão');
  await page.evaluate(() => __mockNovaVersao());
  await page.waitForTimeout(200);
  ok(await page.isVisible('#sm-nova-versao'), 'quando o robô publica dados novos aparece o aviso "Dados atualizados"');
  await page.screenshot({ path: path.join(S, 'e2e', 'novo-aviso.png') });
  await page.click('button[title="Sair"]');
  await page.waitForTimeout(800);
  b = await bloqueado(page);
  ok(b.locked && b.loginVisivel && !b.temLOTS, 'botão Sair encerra a sessão e apaga os dados da página');
  await page.goto(NOVO + '#lotes');
  await page.waitForTimeout(500);
  b = await bloqueado(page); ok(b.locked && !b.temLOTS, 'abrir a URL direto depois do logout não dá acesso');
  await ctx.close();

  console.log('\n6. Perfil VISUALIZACAO');
  ({ ctx, page, erros } = await abrir(browser, NOVO));
  await entrarNovo(page, 'visu@x.com', 'Senha#123');
  await page.waitForFunction(() => !document.body.classList.contains('locked'), null, { timeout: 15000 });
  ok(true, 'VISUALIZACAO consegue consultar');
  await ctx.close();

  await browser.close();
  console.log(`\n${falhas === 0 ? 'TODOS OS TESTES PASSARAM' : falhas + ' FALHA(S)'}`);
  process.exit(falhas ? 1 : 0);
})();
