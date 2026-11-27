// seedmax-backup.cjs — backup e conferência do Firestore do SEEDMAX (seedmax-4c755).
// SOMENTE LEITURA no Firestore: nenhum comando aqui grava, altera ou apaga dados.
//   node seedmax-backup.cjs backup   <pasta>            -> copia todas as coleções (com subcoleções) em JSON + MANIFESTO
//   node seedmax-backup.cjs verificar <pasta>           -> confere hashes e remonta os conjuntos da coleção qualidade
//   node seedmax-backup.cjs totais   <firestore|pasta> <saida.json> -> totais e lista de lotes por conjunto
//   node seedmax-backup.cjs comparar <antes.json> <depois.json>
// firebase-admin já instalado na pasta da ponte do Cloud Shell (sem instalar nada novo)
const M = (process.env.SEEDMAX_NODE_MODULES || require('os').homedir() + '/seedmax-ponte/functions/node_modules').replace(/\/?$/, '/');
const fs = require('fs'), path = require('path'), crypto = require('crypto');
const sha = t => crypto.createHash('sha256').update(t).digest('hex');
const [cmd, a1, a2] = process.argv.slice(2);

function db() {
  const { initializeApp } = require(M + 'firebase-admin/app');
  const { getFirestore } = require(M + 'firebase-admin/firestore');
  initializeApp({ projectId: 'seedmax-4c755' });
  return getFirestore();
}
// tipos do Firestore viram objetos marcados, para poder restaurar fielmente
function enc(v) {
  if (v === null || typeof v !== 'object') return v;
  if (Array.isArray(v)) return v.map(enc);
  const n = v.constructor && v.constructor.name;
  if (n === 'Timestamp') return { __tipo: 'timestamp', s: v.seconds, ns: v.nanoseconds, iso: v.toDate().toISOString() };
  if (n === 'GeoPoint') return { __tipo: 'geopoint', lat: v.latitude, lng: v.longitude };
  if (n === 'DocumentReference') return { __tipo: 'ref', path: v.path };
  if (Buffer.isBuffer(v) || n === 'Bytes') return { __tipo: 'bytes', b64: Buffer.from(v).toString('base64') };
  const o = {}; for (const k of Object.keys(v)) o[k] = enc(v[k]); return o;
}
const arq = nome => nome.split('/').join('__') + '.json';

async function backup(out) {
  const d = db(); fs.mkdirSync(out, { recursive: true });
  const man = { projeto: 'seedmax-4c755', inicio: new Date().toISOString(), somenteLeitura: true, colecoes: {} };
  async function dump(col, nome) {
    const snap = await col.get(); const docs = {};
    for (const doc of snap.docs) {
      docs[doc.id] = enc(doc.data());
      for (const sub of await doc.ref.listCollections()) await dump(sub, nome + '/' + doc.id + '/' + sub.id);
    }
    const txt = JSON.stringify(docs);
    fs.writeFileSync(path.join(out, arq(nome)), txt);
    man.colecoes[nome] = { arquivo: arq(nome), docs: snap.size, bytes: Buffer.byteLength(txt), sha256: sha(txt) };
  }
  for (const c of await d.listCollections()) await dump(c, c.id);
  man.fim = new Date().toISOString();
  fs.writeFileSync(path.join(out, 'MANIFESTO.json'), JSON.stringify(man, null, 1));
  let t = 0; for (const [k, v] of Object.entries(man.colecoes)) { t += v.docs; console.log(k.padEnd(55), String(v.docs).padStart(6), 'docs'); }
  console.log('TOTAL', Object.keys(man.colecoes).length, 'coleções,', t, 'documentos');
}

function lerPasta(dir, nome) { return JSON.parse(fs.readFileSync(path.join(dir, arq(nome)), 'utf8')); }
function conjuntos(docs) { // remonta os conjuntos da coleção qualidade (mesma regra de seedmax_dados.ler)
  const meta = docs._meta || {}; const r = {}; const erros = [];
  for (const [nome, info] of Object.entries(meta.datasets || {})) {
    let t = '';
    for (let i = 0; i < info.partes; i++) {
      const p = docs[`${nome}__${i}`];
      if (!p || p.hash !== info.hash) { erros.push(nome); t = null; break; }
      t += p.json;
    }
    if (t !== null) {
      if (sha(t).slice(0, 16) !== info.hash) erros.push(nome + ' (hash do conteúdo)');
      r[nome] = JSON.parse(t);
    }
  }
  return { meta, dados: r, erros };
}

function verificar(dir) {
  const man = JSON.parse(fs.readFileSync(path.join(dir, 'MANIFESTO.json'), 'utf8')); let ok = true, n = 0;
  for (const [nome, v] of Object.entries(man.colecoes)) {
    const txt = fs.readFileSync(path.join(dir, v.arquivo), 'utf8');
    const docs = Object.keys(JSON.parse(txt)).length;
    if (sha(txt) !== v.sha256 || docs !== v.docs) { ok = false; console.log('FALHA', nome); } else n++;
  }
  console.log(`hash e contagem conferidos: ${n}/${Object.keys(man.colecoes).length} coleções`);
  const q = conjuntos(lerPasta(dir, 'qualidade'));
  console.log(`coleção qualidade: ${Object.keys(q.dados).length} conjuntos remontados do backup, ${q.erros.length} com erro ${q.erros.join(', ')}`);
  if (q.erros.length) ok = false;
  console.log(ok ? 'BACKUP_OK' : 'BACKUP_COM_FALHA'); if (!ok) process.exit(2);
}

const QTD = /(^|_)(kg|peso|sacos?|bags?|qtd|quantidade|sc|volume)/i;
function resumo(lista) {
  const r = { itens: lista.length, somas: {}, lotes: [] };
  for (const it of lista) {
    if (!it || typeof it !== 'object') continue;
    for (const [k, v] of Object.entries(it)) if (QTD.test(k) && typeof v === 'number' && isFinite(v)) r.somas[k] = Math.round(((r.somas[k] || 0) + v) * 1000) / 1000;
    if (it.lote != null) r.lotes.push([it.empresa, it.cultura, it.lote].filter(x => x != null && x !== '').join('|'));
  }
  r.lotes.sort(); return r;
}
async function totais(fonte, saida) {
  let docs;
  if (fonte === 'firestore') { docs = {}; (await db().collection('qualidade').get()).docs.forEach(d => docs[d.id] = enc(d.data())); }
  else docs = lerPasta(fonte, 'qualidade');
  const q = conjuntos(docs); const out = { fonte, em: new Date().toISOString(), versaoMeta: q.meta.versao, atualizadoEm: q.meta.atualizadoEm, erros: q.erros, conjuntos: {} };
  for (const [nome, v] of Object.entries(q.dados)) {
    out.conjuntos[nome] = { hash: q.meta.datasets[nome].hash };
    if (Array.isArray(v)) Object.assign(out.conjuntos[nome], resumo(v));
    else if (v && typeof v === 'object') for (const [k, x] of Object.entries(v)) out.conjuntos[nome + '.' + k] = Array.isArray(x) ? resumo(x) : { tipo: typeof x };
  }
  fs.writeFileSync(saida, JSON.stringify(out, null, 1));
  console.log(`meta versão ${out.versaoMeta} (${out.atualizadoEm}); erros: ${out.erros.length}`);
  for (const [k, v] of Object.entries(out.conjuntos)) if (v.itens !== undefined) console.log(k.padEnd(34), String(v.itens).padStart(5), 'itens', JSON.stringify(v.somas));
}
function comparar(fa, fb) {
  const A = JSON.parse(fs.readFileSync(fa)).conjuntos, B = JSON.parse(fs.readFileSync(fb)).conjuntos; let dif = 0;
  for (const k of [...new Set([...Object.keys(A), ...Object.keys(B)])].sort()) {
    const a = A[k], b = B[k];
    if (!a || !b) { dif++; console.log((a ? '- REMOVIDO ' : '+ NOVO     ') + k); continue; }
    if (a.hash && a.hash === b.hash) continue;
    if (a.itens === undefined) continue;
    const sa = new Set(a.lotes), sb = new Set(b.lotes);
    const sai = a.lotes.filter(x => !sb.has(x)), ent = b.lotes.filter(x => !sa.has(x));
    if (a.itens !== b.itens || JSON.stringify(a.somas) !== JSON.stringify(b.somas) || sai.length || ent.length) {
      dif++; console.log(`~ ${k}: itens ${a.itens}->${b.itens} somas ${JSON.stringify(a.somas)} -> ${JSON.stringify(b.somas)}`);
      if (sai.length) console.log('    lotes que SUMIRAM:', sai.slice(0, 30).join(', '));
      if (ent.length) console.log('    lotes novos:', ent.slice(0, 30).join(', '));
    }
  }
  console.log(dif ? `${dif} conjunto(s) com diferença` : 'SEM_DIFERENCA'); if (dif) process.exitCode = 3;
}

process.on('unhandledRejection', e => { console.error('ERRO', e && e.message || e); process.exit(1); });
const cmds = { backup: () => backup(a1), verificar: () => verificar(a1), totais: () => totais(a1, a2), comparar: () => comparar(a1, a2) };
if (!cmds[cmd] || !a1) { console.log('uso: backup|verificar|totais|comparar <args>'); process.exit(64); }
Promise.resolve(cmds[cmd]()).catch(e => { console.error('ERRO', e.message); process.exit(1); });
