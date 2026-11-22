// Teste local da PGW (prestação de serviço) no Inverno: aba PGW, Beneficiamento por origem,
// Central de Lotes (só na tela) e PDFs. Dados 100% fictícios (dados.cjs).
// Uso: npm i leaflet leaflet.markercluster papaparse html2canvas playwright (numa pasta fora do repositório)
//      NODE_PATH=<pasta>/node_modules node tests/e2e_pgw/teste.cjs
const { chromium } = require('playwright');
const fs = require('fs'), path = require('path'), http = require('http');
const { qualidade, lots } = require('./dados.cjs');
const ESTADO = { contas: { 'a@x.com': { senha: 'x', uid: 'u1' } }, users: { u1: { name: 'T', email: 'a@x.com', role: 'ADMIN', active: true } }, qualidade, lots };
const mock = 'window.__MOCK_ESTADO = ' + JSON.stringify(ESTADO) + ';\n' + fs.readFileSync(path.join(__dirname, 'mock-firebase.cjs.js'), 'utf8');
const html = fs.readFileSync(path.join(__dirname, '../../index.html'));
const srv = http.createServer((q, r) => { r.setHeader('content-type', 'text/html; charset=utf-8'); r.end(html); }).listen(8131);
let falhas = 0; const ok = (c, m) => { console.log((c ? '  ✔ ' : '  ✘ ') + m); if (!c) falhas++; };
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1400, height: 950 } });
  const erros = []; p.on('pageerror', e => erros.push(e.message));
  await p.route('**/*', r => { const u = r.request().url(); if (u.startsWith('http://localhost')) return r.continue();
    if (u.includes('firebase-app-compat.js')) return r.fulfill({ body: mock, contentType: 'application/javascript' });
    if (u.includes('gstatic')) return r.fulfill({ body: '' }); return r.abort(); });
  await p.goto('http://localhost:8131/'); await p.fill('#email-input', 'a@x.com'); await p.fill('#pw-input', 'x'); await p.click('#login-form .sml-btn'); await p.waitForTimeout(2000);
  await p.evaluate(() => { trocarSafra('inverno'); showPageInverno('pgw'); });
  ok(await p.evaluate(() => document.getElementById('inv-pgw-kg').innerText.includes('72.600 kg')), 'aba PGW: 5 lotes base + 2 fictícios = 72.600 kg');
  ok(await p.evaluate(() => document.getElementById('h-kg').innerText === '108.000 kg' && /Produção própria/i.test(document.getElementById('h-kg-lbl').innerText)), 'cabeçalho: 108.000 kg marcado como Produção própria na aba PGW');
  await p.evaluate(() => showPageInverno('beneficiamento'));
  ok(await p.evaluate(() => document.getElementById('h-kg-lbl').textContent === 'Total KG'), 'cabeçalho volta a "Total KG" fora da aba PGW');
  ok(await p.evaluate(() => document.getElementById('invb-visao-propria').getAttribute('aria-pressed') === 'true'), 'Beneficiamento abre em Produção própria');
  ok(await p.evaluate(() => /108\.000 kg · Produção própria/.test(document.getElementById('inv-benef-kpis').innerText)), 'Produção própria: 108.000 kg (sem PGW e sem "a conferir")');
  ok(await p.evaluate(() => /1 lote · 10 bags · 6\.000 kg/.test(document.getElementById('invb-conferir').innerText)), 'Origem a conferir: bloco separado com 6.000 kg');
  await p.evaluate(() => invBenefTrocarVisao('pgw'));
  ok(await p.evaluate(() => /72\.600 kg · PGW/.test(document.getElementById('inv-benef-kpis').innerText)), 'Beneficiamento PGW: 72.600 kg');
  await p.evaluate(() => trocarSafra('verao')); await p.click(`.tab[onclick="showPage('central')"]`); await p.waitForTimeout(1200);
  ok(await p.evaluate(() => document.getElementById('central-pgw').style.display === 'none'), 'Central sem busca: PGW escondida');
  const total = await p.evaluate(() => document.getElementById('central-kpis').innerText);
  await p.fill('#central-search', 'PGW-T'); await p.waitForTimeout(500);
  ok(await p.evaluate(() => document.querySelectorAll('#central-pgw-tbody tr').length === 5), 'Central: busca acha os 5 lotes PGW');
  ok(await p.evaluate(() => document.getElementById('central-count').innerText === '0') && total === await p.evaluate(() => document.getElementById('central-kpis').innerText), 'Central: contadores e cartões não mudam com a PGW');
  ok(await p.evaluate(() => CENTRAL.every(x => !/^PGW/.test(x.lotCode))), 'Central: PGW não entra em CENTRAL (lots/)');
  await p.click('#central-pgw-tbody tr[data-pgw="0"]'); await p.waitForTimeout(300);
  ok(await p.evaluate(() => { const t = document.getElementById('cl-box').innerText; return /PGW · PRESTAÇÃO DE SERVIÇO/i.test(t) && /BENEFICIAMENTO/i.test(t) && /QUALIDADE/i.test(t); }), 'Central: detalhe do lote PGW com Qualidade e Beneficiamento');
  ok(await p.evaluate(() => /DIVERGÊNCIA · Categoria: aba PGW S2 × Beneficiamento C1/i.test(document.getElementById('cl-box').innerText)), 'Central: categoria divergente mostra o valor de cada fonte');
  ok(await p.evaluate(() => LOTS_SERVICO_INVERNO[0].categoria === 'S2' && BENEF_INVERNO.some(c => c.detail.some(d => d.lote === 'PGW-T-01' && d.categoria === 'C1'))), 'registros não são sobrescritos (S2 e C1 continuam como vieram)');
  ok(!erros.length, 'sem erros de JavaScript' + (erros.length ? ': ' + erros.join(' | ') : ''));
  await b.close(); srv.close();
  console.log(falhas ? falhas + ' falha(s)' : 'tudo certo'); process.exit(falhas ? 1 : 0);
})();
