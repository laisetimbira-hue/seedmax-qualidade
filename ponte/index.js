'use strict';
// SEEDMAX — Cloud Function "ponteModulo" (2ª geração, Firebase callable).
// *** NÃO IMPLANTADA. *** Precisa do plano Blaze no projeto seedmax-4c755.
// Roda como ponte-login@seedmax-4c755 (sem chave); assina custom tokens via
// IAM signBlob como ponte-assina-tsi@estoquetsi / ponte-assina-rastrel@rastreabilidade-a511a.
const { onCall, HttpsError } = require('firebase-functions/v2/https');
const logger = require('firebase-functions/logger');
const { initializeApp } = require('firebase-admin/app');
const { getAuth } = require('firebase-admin/auth');
const { getFirestore } = require('firebase-admin/firestore');
const { criarPonte, extrairBearer, ErroPonte } = require('./ponte');

const CENTRAL = initializeApp(); // projeto seedmax; credencial = conta da função (ADC)
const ASSINANTES = {
  tsi: { projectId: 'estoquetsi', serviceAccountId: 'ponte-assina-tsi@estoquetsi.iam.gserviceaccount.com' },
  rastrel: { projectId: 'rastreabilidade-a511a', serviceAccountId: 'ponte-assina-rastrel@rastreabilidade-a511a.iam.gserviceaccount.com' }
};
const appsModulo = {};
const appModulo = m => appsModulo[m] || (appsModulo[m] = initializeApp(ASSINANTES[m], 'assina-' + m));

const ponte = criarPonte({
  verificar: idToken => getAuth(CENTRAL).verifyIdToken(idToken, true),   // true = confere revogação
  lerCadastro: async uid => { const s = await getFirestore(CENTRAL).doc('users/' + uid).get(); return s.exists ? s.data() : null; },
  assinar: (modulo, uid, claims) => getAuth(appModulo(modulo)).createCustomToken(uid, claims),
  registrar: evento => logger.info('ponteModulo', evento)                 // sem token
});

exports.ponteModulo = onCall({
  region: 'southamerica-east1',
  serviceAccount: 'ponte-login@seedmax-4c755.iam.gserviceaccount.com',
  maxInstances: 2, minInstances: 0, timeoutSeconds: 10, memory: '256MiB',
  invoker: 'public'                    // o navegador chama; sem ID token válido nada é assinado
}, async req => {
  const idToken = extrairBearer(req.rawRequest && req.rawRequest.headers && req.rawRequest.headers.authorization);
  try {
    return await ponte({ idToken, modulo: req.data && req.data.modulo });
  } catch (e) {
    if (e instanceof ErroPonte) throw new HttpsError(e.codigo, e.motivo);
    logger.error('ponteModulo erro interno', { tipo: e && e.name });   // sem mensagem crua (pode conter dados)
    throw new HttpsError('internal', 'erro-interno');
  }
});
