'use strict';
// Servidor de TESTE: roda o mesmo núcleo da Cloud Function sincronizarBenefInverno
// (ponte/benef-inverno.js) com um "banco" numa pasta — um arquivo JSON por
// documento, no MESMO formato que scripts/seedmax_dados.py lê (SEEDMAX_DESTINO=pasta:).
// Também simula o login do Firebase Auth (signInWithPassword).
// Uso: node servidor.cjs <pasta-banco> <porta>
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const bi = require('../../ponte/benef-inverno');
const { extrairBearer } = require('../../ponte/ponte');

const [pasta, porta] = [process.argv[2], Number(process.argv[3] || 0)];
const CONTAS = { 'sinc@teste': { senha: 'certa', uid: 'u-sync' }, 'admin@teste': { senha: 'certa', uid: 'u-adm' } };
const CADASTRO = { 'u-sync': { role: 'SINC_BENEF_INVERNO', active: true }, 'u-adm': { role: 'ADMIN', active: true } };

const ler = () => Object.fromEntries(fs.readdirSync(pasta).filter(f => f.endsWith('.json'))
  .map(f => [f.slice(0, -5), JSON.parse(fs.readFileSync(path.join(pasta, f), 'utf8'))]));
const gravar = (id, c) => fs.writeFileSync(path.join(pasta, id + '.json'), JSON.stringify(c));
const registros = [];

const sinc = bi.criarSincronizador({
  verificar: async t => { const m = /^tok\.(.+)$/.exec(t); if (!m) throw new Error('inválido'); return { uid: m[1] }; },
  lerCadastro: async uid => CADASTRO[uid] || null,
  lerQualidade: async () => ler(),
  publicar: async (partes, entrada, carimbo) => {                 // transação: relê o _meta agora
    const atual = fs.existsSync(path.join(pasta, '_meta.json')) ? JSON.parse(fs.readFileSync(path.join(pasta, '_meta.json'), 'utf8')) : {};
    const [novo, apagar] = bi.mesclarMeta(atual, bi.CONJUNTO, entrada, carimbo);
    for (const [id, c] of Object.entries(partes)) gravar(id, c);
    for (const id of apagar) fs.rmSync(path.join(pasta, id + '.json'), { force: true });
    gravar('_meta', novo);
  },
  registrar: async r => { registros.push(r); fs.writeFileSync(path.join(pasta, '..', 'sincronizacoes.json'), JSON.stringify(registros, null, 1)); },
  agora: () => new Date(),
  log: () => {}
});

http.createServer((req, res) => {
  let corpo = '';
  req.on('data', d => { corpo += d; });
  req.on('end', async () => {
    const env = (st, o) => { res.writeHead(st, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(o)); };
    try {
      const dados = corpo ? JSON.parse(corpo) : {};
      if (req.url.startsWith('/login')) {
        const c = CONTAS[dados.email];
        if (!c || c.senha !== dados.password) return env(400, { error: { message: 'INVALID_LOGIN_CREDENTIALS' } });
        return env(200, { idToken: 'tok.' + c.uid });
      }
      if (req.method !== 'POST') return env(405, { ok: false, erro: 'metodo' });
      const out = await sinc({ idToken: extrairBearer(req.headers.authorization), corpo: dados });
      env(200, out);
    } catch (e) {
      if (e instanceof bi.ErroSync) return env(e.status, { ok: false, erro: e.erro, mensagem: e.mensagem, detalhes: e.detalhes || [] });
      env(500, { ok: false, erro: 'interno', mensagem: String(e && e.message) });
    }
  });
}).listen(porta, '127.0.0.1', function () { console.log('PORTA ' + this.address().port); });
