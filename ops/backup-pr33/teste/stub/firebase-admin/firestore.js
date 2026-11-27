// Firestore FALSO para teste: lê a pasta FAKE_DB; qualquer tentativa de escrita derruba o teste.
const fs = require('fs'), path = require('path');
class Timestamp { constructor(s, ns) { this.seconds = s; this.nanoseconds = ns; } toDate() { return new Date(this.seconds * 1000); } }
const proibido = () => { throw new Error('ESCRITA_PROIBIDA'); };
function revive(v) { // _criadoEm vira Timestamp de verdade, para testar a serialização
  if (v && typeof v === 'object' && !Array.isArray(v)) { const o = {}; for (const k of Object.keys(v)) o[k] = k === '_criadoEm' ? new Timestamp(v[k], 5) : revive(v[k]); return o; }
  return v;
}
function colecao(nome, docs, subs) {
  return { id: nome, set: proibido, add: proibido, doc: proibido,
    get: async () => { const lista = Object.entries(docs).map(([id, d]) => ({ id, data: () => revive(d),
      ref: { set: proibido, update: proibido, delete: proibido, listCollections: async () => (subs[id] || []) } }));
      return { size: lista.length, docs: lista }; } };
}
exports.getFirestore = () => {
  const dir = process.env.FAKE_DB; const docs = {};
  for (const f of fs.readdirSync(dir)) if (f.endsWith('.json')) docs[f.slice(0, -5)] = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
  const usuarios = { u1: { role: 'ADMIN', active: true, _criadoEm: 1764240000 } };
  const hist = colecao('historico', { h1: { ok: true } }, {});
  return { batch: proibido, runTransaction: proibido, doc: proibido,
    collection: n => n === 'qualidade' ? colecao('qualidade', docs, {}) : proibido(),
    listCollections: async () => [colecao('qualidade', docs, {}), colecao('users', usuarios, {}), colecao('sincronizacoes', { BENEF_INVERNO: { ok: 1 } }, { BENEF_INVERNO: [hist] })] };
};
exports.Timestamp = Timestamp;
