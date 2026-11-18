'use strict';
// SEEDMAX — Cloud Function sincronizarBenefInverno (2ª geração, HTTPS).
//
// Recebe do computador da empresa as linhas da planilha "LOTES BENEFICIADOS
// INVERNO" e grava SOMENTE qualidade/BENEF_INVERNO (+ a entrada dele no índice
// qualidade/_meta) e o registro em sincronizacoes/BENEF_INVERNO.
//
// * Roda como sinc-benef-inverno@seedmax-4c755 (conta própria, SEM chave JSON;
//   papel Cloud Datastore User) — separada da conta da ponte de login.
// * Quem chama: só a conta técnica de perfil SINC_BENEF_INVERNO (ID token do
//   Firebase Auth, vale 1 h). Nenhum outro perfil, nem ADMIN, usa esta porta.
// * Usa o app padrão do firebase-admin (o index.js da ponte já inicializa).
// Lógica e validação: benef-inverno.js (testada sem rede).

const { onRequest } = require('firebase-functions/v2/https');
const logger = require('firebase-functions/logger');
const { getFirestore, FieldValue } = require('firebase-admin/firestore');
const { getAuth } = require('firebase-admin/auth');
const bi = require('./benef-inverno');

const CONTA = process.env.SINC_BENEF_INVERNO_CONTA || 'sinc-benef-inverno@seedmax-4c755.iam.gserviceaccount.com';

function extrairBearer(cabecalho) {
  const m = /^Bearer\s+([A-Za-z0-9._-]+)$/.exec(String(cabecalho || '').trim());
  return m ? m[1] : null;
}

const sincronizador = bi.criarSincronizador({
  verificar: idToken => getAuth().verifyIdToken(idToken, true),            // true = confere revogação
  lerCadastro: async uid => { const s = await getFirestore().doc('users/' + uid).get(); return s.exists ? s.data() : null; },
  lerQualidade: async () => {
    const snap = await getFirestore().collection(bi.COLECAO).get();
    const docs = {}; snap.forEach(d => { docs[d.id] = d.data(); }); return docs;
  },
  // Transação: o _meta é relido na hora de gravar e só a entrada BENEF_INVERNO
  // muda — o robô do GitHub (seedmax_dados.gravar_mesclando) faz o mesmo, então
  // um nunca sobrescreve o índice do outro.
  publicar: async (partes, entrada, carimbo) => {
    const db = getFirestore();
    const col = db.collection(bi.COLECAO);
    const refMeta = col.doc('_meta');
    await db.runTransaction(async tx => {
      const snap = await tx.get(refMeta);
      const [novo, apagar] = bi.mesclarMeta(snap.exists ? snap.data() : {}, bi.CONJUNTO, entrada, carimbo);
      for (const [id, conteudo] of Object.entries(partes)) {
        if (!id.startsWith(bi.CONJUNTO + '__')) throw new Error('documento fora do BENEF_INVERNO');
        tx.set(col.doc(id), conteudo);
      }
      for (const id of apagar) {
        if (!id.startsWith(bi.CONJUNTO + '__')) throw new Error('documento fora do BENEF_INVERNO');
        tx.delete(col.doc(id));
      }
      tx.set(refMeta, Object.assign(novo, { atualizadoEmServidor: FieldValue.serverTimestamp() }));
    });
  },
  registrar: async reg => {
    const db = getFirestore();
    const r = Object.assign({}, reg, { em: FieldValue.serverTimestamp() });
    await db.doc('sincronizacoes/' + bi.CONJUNTO).set(r);
    await db.collection('sincronizacoes/' + bi.CONJUNTO + '/historico').add(r);
  },
  agora: () => new Date(),
  log: evento => logger.info('sincronizarBenefInverno', evento)            // nunca token nem planilha
});

exports.sincronizarBenefInverno = onRequest({
  region: 'southamerica-east1',
  serviceAccount: CONTA,
  maxInstances: 1, minInstances: 0, concurrency: 1, timeoutSeconds: 60, memory: '256MiB',
  invoker: 'public',                  // a autorização é o ID token da conta SINC_BENEF_INVERNO
  cors: false
}, async (req, res) => {
  res.set('Cache-Control', 'no-store');
  if (req.method !== 'POST') { res.status(405).json({ ok: false, erro: 'metodo', mensagem: 'use POST' }); return; }
  if (!/^application\/json/i.test(req.get('content-type') || '')) { res.status(415).json({ ok: false, erro: 'tipo', mensagem: 'envie application/json' }); return; }
  if (req.rawBody && req.rawBody.length > 2 * 1024 * 1024) { res.status(413).json({ ok: false, erro: 'grande_demais', mensagem: 'envio maior que 2 MB' }); return; }
  try {
    const out = await sincronizador({ idToken: extrairBearer(req.get('authorization')), corpo: req.body });
    res.status(200).json(out);
  } catch (e) {
    if (e instanceof bi.ErroSync) {
      logger.warn('sincronizarBenefInverno recusado', { erro: e.erro, status: e.status });
      res.status(e.status).json({ ok: false, erro: e.erro, mensagem: e.mensagem, detalhes: e.detalhes || [] });
      return;
    }
    logger.error('sincronizarBenefInverno erro interno', { tipo: e && e.name });
    res.status(500).json({ ok: false, erro: 'interno', mensagem: 'erro interno — nada foi publicado' });
  }
});
