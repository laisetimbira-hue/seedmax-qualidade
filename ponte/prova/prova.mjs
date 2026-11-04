// SEEDMAX — PROVA TÉCNICA DA PONTE DE LOGIN (seção 17). Roda no Cloud Shell, SEM Blaze.
// - A "função" roda aqui mesmo, com o mesmo código (../ponte.js) e agindo COMO ponte-login
//   (impersonação temporária), sem chave JSON.
// - O login no TSI/RASTREL é feito com o SDK web real (signInWithCustomToken).
// - Nenhum token é impresso, gravado em arquivo ou passado por URL.
// - Só toca em: cadastro do usuário de teste (restaurado no fim), users/{uid de teste} nos
//   módulos (criado e apagado), usuário de Auth criado pela prova nos módulos (apagado).
import { execSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { writeFileSync } from 'node:fs';
import readline from 'node:readline';
import { OAuth2Client, Impersonated } from 'google-auth-library';
import admin from 'firebase-admin';
import { initializeApp as initWeb, deleteApp } from 'firebase/app';
import { getAuth as authWeb, signInWithCustomToken, signOut } from 'firebase/auth';
import { getFirestore as fsWeb, collection, query, limit, getDocs, doc, setDoc, terminate } from 'firebase/firestore';
const require = createRequire(import.meta.url);
const { criarPonte } = require('../ponte.js');

const SEED = 'seedmax-4c755', TSI = 'estoquetsi', RAS = 'rastreabilidade-a511a';
const PL = `ponte-login@${SEED}.iam.gserviceaccount.com`;
const ASSINA = { tsi: `ponte-assina-tsi@${TSI}.iam.gserviceaccount.com`, rastrel: `ponte-assina-rastrel@${RAS}.iam.gserviceaccount.com` };
const PROJ = { tsi: TSI, rastrel: RAS };
// configurações WEB públicas (as mesmas que já estão nos apps)
const WEB = {
  seedmax: { apiKey: 'AIzaSyAVW7rA87T3S_AdrP83gCGIFl6jgcWehCE' },
  tsi: { apiKey: 'AIzaSyD4iZ7eGWWBx48D2sq7TcNhrpBg02ejhCQ', authDomain: 'estoquetsi.firebaseapp.com', projectId: TSI, appId: '1:280321718209:web:b7113e3b99f48c377b6140' },
  rastrel: { apiKey: 'AIzaSyC_1suDbjnnySBqsG8XBsHTlqjA8XBsrS8', authDomain: 'rastreabilidade-a511a.firebaseapp.com', projectId: RAS, appId: '1:580280416030:web:7eeed32f444611d7247b0f' }
};
const COLECAO = { tsi: 'produtos', rastrel: 'bags' };          // leitura liberada a qualquer cadastro ativo
const DOC_PROVA = '__prova_ponte_seedmax';                     // gravação que DEVE ser negada (VISUALIZADOR)

// As chaves web podem ter restrição de site (como no navegador): as chamadas de login do SDK
// saem daqui com o mesmo Referer do app correspondente. Só cabeçalho; nada vai na URL.
const REFERER = { [WEB.tsi.apiKey]: 'https://tsi.seedmax.com.br/', [WEB.rastrel.apiKey]: 'https://rastrel.seedmax.com.br/', [WEB.seedmax.apiKey]: 'https://app.seedmax.com.br/' };
const fetchOriginal = globalThis.fetch;
globalThis.fetch = (u, o = {}) => {
  const url = String(u && u.url ? u.url : u);
  if (/identitytoolkit|securetoken/.test(url)) {
    const chave = Object.keys(REFERER).find(k => url.includes(k));
    if (chave) { const h = new Headers(o.headers || {}); h.set('Referer', REFERER[chave]); o = Object.assign({}, o, { headers: h }); }
  }
  return fetchOriginal(u, o);
};

const SEGREDOS = new Set();                                    // tokens vistos: nunca podem aparecer na saída
const saida = [];
const log = (...a) => { const s = a.join(' '); for (const t of SEGREDOS) if (t && s.includes(t)) throw new Error('VAZAMENTO: token na saída'); saida.push(s); console.log(s); };
const resultados = [];
const registra = (cenario, esperado, obtido, detalhe) => { const ok = esperado === obtido; resultados.push({ cenario, esperado, obtido, ok, detalhe }); log((ok ? '  PASSOU ' : '  FALHOU ') + cenario + ' — esperado: ' + esperado + ' · obtido: ' + obtido + (detalhe ? ' (' + detalhe + ')' : '')); };

// ---------------------------------------------------------------- credenciais
const tokenEu = () => execSync('gcloud auth print-access-token', { encoding: 'utf8' }).trim();
const fonte = new OAuth2Client(); fonte.setCredentials({ access_token: tokenEu() });
const imp = new Impersonated({ sourceClient: fonte, targetPrincipal: PL, targetScopes: ['https://www.googleapis.com/auth/cloud-platform'], lifetime: 900 });
const credPonte = { async getAccessToken() { const t = await imp.getAccessToken(); return { access_token: t.token, expires_in: 600 }; } };

// ---------------------------------------------------------------- Firestore REST
const enc = v => v === null ? { nullValue: null } : typeof v === 'boolean' ? { booleanValue: v } : typeof v === 'string' ? { stringValue: v }
  : { mapValue: { fields: Object.fromEntries(Object.entries(v).map(([k, x]) => [k, enc(x)])) } };
const dec = f => 'stringValue' in f ? f.stringValue : 'booleanValue' in f ? f.booleanValue : 'nullValue' in f ? null : 'integerValue' in f ? Number(f.integerValue)
  : 'mapValue' in f ? Object.fromEntries(Object.entries(f.mapValue.fields || {}).map(([k, x]) => [k, dec(x)])) : f;
async function rest(projeto, metodo, caminho, corpo, token, comoPonte) {
  const url = `https://firestore.googleapis.com/v1/projects/${projeto}/databases/(default)/documents/${caminho}`;
  const h = { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' };
  if (!comoPonte) h['x-goog-user-project'] = projeto;   // credencial de usuário (você) precisa do projeto de cota
  const r = await fetch(url, { method: metodo, headers: h, body: corpo ? JSON.stringify(corpo) : undefined });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`Firestore ${metodo} ${projeto}/${caminho}: HTTP ${r.status}`);
  return r.status === 200 ? r.json() : {};
}
const lerDoc = async (p, c, token, comoPonte) => { const d = await rest(p, 'GET', c, null, token, comoPonte); return d ? Object.fromEntries(Object.entries(d.fields || {}).map(([k, x]) => [k, dec(x)])) : null; };
const gravarDoc = (p, c, obj, token) => rest(p, 'PATCH', c, { fields: Object.fromEntries(Object.entries(obj).map(([k, x]) => [k, enc(x)])) }, token);
const apagarDoc = (p, c, token) => rest(p, 'DELETE', c, null, token);
async function apagarUsuarioAuth(projeto, uid) {
  const r = await fetch(`https://identitytoolkit.googleapis.com/v1/projects/${projeto}/accounts:delete`, { method: 'POST', headers: { Authorization: 'Bearer ' + tokenEu(), 'x-goog-user-project': projeto, 'Content-Type': 'application/json' }, body: JSON.stringify({ localId: uid }) });
  return r.ok;
}

// ---------------------------------------------------------------- login central (senha digitada por você, oculta)
function perguntarOculto(pergunta) {
  return new Promise(res => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: true });
    rl._writeToOutput = s => { if (s.startsWith(pergunta)) process.stdout.write(s); };
    rl.question(pergunta, v => { rl.close(); process.stdout.write('\n'); res(v); });
  });
}
async function loginCentral(email, senha) {
  // corpo POST (nunca na URL); a chave web pública é a mesma do app
  const r = await fetch('https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=' + WEB.seedmax.apiKey, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Referer: 'https://app.seedmax.com.br/' },
    body: JSON.stringify({ email, password: senha, returnSecureToken: true }) });
  const j = await r.json();
  if (!r.ok) throw new Error('login central recusado: ' + (j.error && j.error.message));
  SEGREDOS.add(j.idToken); SEGREDOS.add(j.refreshToken);
  return { uid: j.localId, idToken: j.idToken };
}

// ---------------------------------------------------------------- a ponte, com as peças reais
const appCentral = admin.initializeApp({ credential: credPonte, projectId: SEED }, 'central');
const appsAssina = {};
const appAssina = (modulo, conta) => { const k = modulo + '|' + conta; return appsAssina[k] || (appsAssina[k] = admin.initializeApp({ credential: credPonte, projectId: PROJ[modulo], serviceAccountId: conta }, 'assina-' + Object.keys(appsAssina).length)); };
const eventos = [];
const ponte = criarPonte({
  verificar: t => admin.auth(appCentral).verifyIdToken(t, true),
  lerCadastro: async uid => lerDoc(SEED, 'users/' + uid, (await imp.getAccessToken()).token, true),   // lido COMO ponte-login
  assinar: async (m, uid, claims) => { const t = await admin.auth(appAssina(m, ASSINA[m])).createCustomToken(uid, claims); SEGREDOS.add(t); return t; },
  registrar: e => { eventos.push(e); log('    [log da ponte] ' + JSON.stringify(e)); }
});

// ---------------------------------------------------------------- login no módulo + regras
async function entrarNoModulo(modulo, customToken, nome) {
  const app = initWeb(WEB[modulo], nome);
  const auth = authWeb(app), db = fsWeb(app);
  const out = { app, auth, db };
  try { const cred = await signInWithCustomToken(auth, customToken); out.uid = cred.user.uid; out.ok = true; }
  catch (e) { out.ok = false; out.erro = e.code || e.message; }
  return out;
}
async function testarRegras(modulo, s) {
  let leitura, gravacao;
  try { await getDocs(query(collection(s.db, COLECAO[modulo]), limit(1))); leitura = 'liberada'; } catch (e) { leitura = e.code === 'permission-denied' ? 'negada' : 'erro:' + e.code; }
  try { await setDoc(doc(s.db, COLECAO[modulo], DOC_PROVA), { prova: true, lote: 'PROVA' }); gravacao = 'liberada'; } catch (e) { gravacao = e.code === 'permission-denied' ? 'negada' : 'erro:' + e.code; }
  return { leitura, gravacao };
}
async function sair(s) { try { await signOut(s.auth); } catch (e) {} try { await terminate(s.db); } catch (e) {} try { await deleteApp(s.app); } catch (e) {} }

// ---------------------------------------------------------------- roteiro
const email = process.env.PROVA_EMAIL;
if (!email) { console.error('Defina PROVA_EMAIL=<e-mail do usuário de teste>'); process.exit(2); }
log('SEEDMAX — prova técnica da ponte · ' + new Date().toISOString());
const senha = await perguntarOculto('Senha do usuário de teste (não aparece na tela): ');
const central = await loginCentral(email, senha);
log('UID central testado: ' + central.uid);
const eu = tokenEu();
const original = await lerDoc(SEED, 'users/' + central.uid, eu);
if (!original) throw new Error('crie antes users/' + central.uid + ' no Firestore do seedmax (name, email, role, active)');
for (const m of ['tsi', 'rastrel']) {
  if (await lerDoc(PROJ[m], 'users/' + central.uid, eu)) throw new Error(`users/${central.uid} já existe em ${PROJ[m]} — a prova não sobrescreve cadastros`);
}
const cadastroModulo = { name: 'Prova ponte SEEDMAX', email, role: 'VISUALIZADOR', active: true };
const setCentral = campos => gravarDoc(SEED, 'users/' + central.uid, Object.assign({ name: original.name || 'Prova ponte', email: original.email || email }, campos), eu);
const pedir = async (modulo) => { try { const r = await ponte({ idToken: central.idToken, modulo }); return { ok: true, token: r.token, papel: r.papel }; } catch (e) { return { ok: false, motivo: e.motivo, codigo: e.codigo }; } };
let n = 0;
try {
  await gravarDoc(TSI, 'users/' + central.uid, cadastroModulo, eu);
  await gravarDoc(RAS, 'users/' + central.uid, cadastroModulo, eu);
  log('Cadastros de teste criados nos módulos (VISUALIZADOR).');
  await new Promise(r => setTimeout(r, 1500));

  log('\n[1] Perfil central TSI (modulos.tsi = VISUALIZADOR)');
  await setCentral({ role: 'TSI', active: true, modulos: { tsi: 'VISUALIZADOR' } });
  let p = await pedir('tsi');
  registra('1a ponte emite login do TSI', 'emitido', p.ok ? 'emitido' : 'recusado:' + p.motivo);
  if (p.ok) {
    const s = await entrarNoModulo('tsi', p.token, 'tsi-' + (++n));
    registra('1b signInWithCustomToken no Firebase do TSI', 'ok', s.ok ? 'ok' : s.erro);
    registra('1c UID no TSI = UID central', central.uid, s.uid || '-');
    if (s.ok) {
      const t2 = await s.auth.currentUser.getIdToken(true); SEGREDOS.add(t2);
      registra('1d sessão do TSI renova o ID token sozinha (sessão normal)', 'renovou', t2 ? 'renovou' : 'não');
      const r = await testarRegras('tsi', s);
      registra('1e regra do TSI: leitura (VISUALIZADOR)', 'liberada', r.leitura);
      registra('1f regra do TSI: gravação (VISUALIZADOR)', 'negada', r.gravacao);
    }
    await sair(s);
  }
  p = await pedir('rastrel');
  registra('2  perfil TSI pede RASTREL', 'recusado:perfil-sem-modulo', p.ok ? 'emitido' : 'recusado:' + p.motivo);

  log('\n[3] Perfil central RASTREL (modulos.rastrel = VISUALIZADOR)');
  await setCentral({ role: 'RASTREL', active: true, modulos: { rastrel: 'VISUALIZADOR' } });
  p = await pedir('rastrel');
  registra('3a ponte emite login do RASTREL', 'emitido', p.ok ? 'emitido' : 'recusado:' + p.motivo);
  if (p.ok) {
    const s = await entrarNoModulo('rastrel', p.token, 'ras-' + (++n));
    registra('3b signInWithCustomToken no Firebase do RASTREL', 'ok', s.ok ? 'ok' : s.erro);
    registra('3c UID no RASTREL = UID central', central.uid, s.uid || '-');
    if (s.ok) {
      const r = await testarRegras('rastrel', s);
      registra('3d regra do RASTREL: leitura (VISUALIZADOR)', 'liberada', r.leitura);
      registra('3e regra do RASTREL: gravação (VISUALIZADOR)', 'negada', r.gravacao);
    }
    await sair(s);
  }
  p = await pedir('tsi');
  registra('4  perfil RASTREL pede TSI', 'recusado:perfil-sem-modulo', p.ok ? 'emitido' : 'recusado:' + p.motivo);

  log('\n[5] Não autorizados');
  await setCentral({ role: 'QUALIDADE', active: true, modulos: { tsi: 'ADMIN', rastrel: 'ADMIN' } });
  for (const m of ['tsi', 'rastrel']) { p = await pedir(m); registra('5  QUALIDADE pede ' + m, 'recusado:perfil-sem-modulo', p.ok ? 'emitido' : 'recusado:' + p.motivo); }
  await setCentral({ role: 'VISUALIZACAO', active: true, modulos: { tsi: 'VISUALIZADOR', rastrel: 'VISUALIZADOR' } });
  for (const m of ['tsi', 'rastrel']) { p = await pedir(m); registra('6  VISUALIZACAO pede ' + m, 'recusado:perfil-sem-modulo', p.ok ? 'emitido' : 'recusado:' + p.motivo); }
  await setCentral({ role: 'TSI', active: false, modulos: { tsi: 'VISUALIZADOR' } });
  p = await pedir('tsi'); registra('7  cadastro central inativo', 'recusado:inativo', p.ok ? 'emitido' : 'recusado:' + p.motivo);
  try { await ponte({ idToken: central.idToken.slice(0, -4) + 'AAAA', modulo: 'tsi' }); registra('8  ID token adulterado', 'recusado:token-invalido', 'emitido'); }
  catch (e) { registra('8  ID token adulterado', 'recusado:token-invalido', 'recusado:' + e.motivo); }

  log('\n[9] Regra do módulo como proteção final');
  await setCentral({ role: 'TSI', active: true, modulos: { tsi: 'VISUALIZADOR' } });
  await gravarDoc(TSI, 'users/' + central.uid, Object.assign({}, cadastroModulo, { active: false }), eu);
  await new Promise(r => setTimeout(r, 1500));
  p = await pedir('tsi');
  if (p.ok) {
    const s = await entrarNoModulo('tsi', p.token, 'tsi-' + (++n));
    const r = s.ok ? await testarRegras('tsi', s) : { leitura: 'sem-login', gravacao: 'sem-login' };
    registra('9  cadastro do TSI inativo: leitura mesmo com login', 'negada', r.leitura);
    await sair(s);
  } else registra('9  cadastro do TSI inativo', 'emitido', 'recusado:' + p.motivo);

  log('\n[10] Assinatura por conta de OUTRO projeto');
  try {
    const tok = await admin.auth(appAssina('tsi', ASSINA.rastrel)).createCustomToken(central.uid, { ponte: true });
    SEGREDOS.add(tok);
    const s = await entrarNoModulo('tsi', tok, 'tsi-' + (++n));
    registra('10 token do TSI assinado pela conta do RASTREL', 'recusado', s.ok ? 'aceito' : 'recusado', s.erro);
    await sair(s);
  } catch (e) { registra('10 token do TSI assinado pela conta do RASTREL', 'recusado', 'recusado', 'assinatura negada: ' + (e.code || 'erro')); }
} finally {
  log('\n[Limpeza]');
  await setCentral({ role: original.role, active: original.active, ...(original.modulos ? { modulos: original.modulos } : {}) }).then(() => log('  cadastro central do teste restaurado')).catch(e => log('  ATENÇÃO: restaurar cadastro central: ' + e.message));
  for (const m of ['tsi', 'rastrel']) {
    await apagarDoc(PROJ[m], 'users/' + central.uid, eu).then(() => log('  apagado users/' + central.uid + ' em ' + PROJ[m])).catch(e => log('  ATENÇÃO: ' + e.message));
    await apagarDoc(PROJ[m], COLECAO[m] + '/' + DOC_PROVA, eu).catch(() => {});
    log('  usuário de Auth criado pela prova em ' + PROJ[m] + ': ' + ((await apagarUsuarioAuth(PROJ[m], central.uid)) ? 'apagado' : 'não encontrado'));
  }
}
const falhas = resultados.filter(r => !r.ok).length;
const rel = { quando: new Date().toISOString(), uidCentral: central.uid, contas: { executa: PL, assinaTsi: ASSINA.tsi, assinaRastrel: ASSINA.rastrel },
  resultados, eventosDaPonte: eventos, falhas, verificacaoVazamento: [...SEGREDOS].every(t => !saida.join('\n').includes(t)) ? 'nenhum token na saída' : 'VAZOU' };
writeFileSync('prova-resultado.json', JSON.stringify(rel, null, 2));
log('\n' + (falhas ? falhas + ' FALHA(S)' : 'PROVA OK: ' + resultados.length + ' verificações') + ' · relatório (sem tokens): prova-resultado.json');
process.exit(falhas ? 1 : 0);
