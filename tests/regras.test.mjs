// Testes das regras de acesso (firestore.rules) contra o emulador.
// Rodar: npx firebase-tools emulators:exec --only firestore --project demo-seedmax \
//          --config ../firebase.json "node --test regras.test.mjs"
import { test, before, after } from 'node:test';
import { readFileSync } from 'node:fs';
import { initializeTestEnvironment, assertFails, assertSucceeds } from '@firebase/rules-unit-testing';
import { doc, getDoc, setDoc, updateDoc, deleteDoc, collection, getDocs } from 'firebase/firestore';

let env;
const usuarios = {
  admin:  { name: 'Admin',  email: 'admin@x.com',  role: 'ADMIN',        active: true },
  qual:   { name: 'Qual',   email: 'qual@x.com',   role: 'QUALIDADE',    active: true },
  visu:   { name: 'Visu',   email: 'visu@x.com',   role: 'VISUALIZACAO', active: true },
  tsi:    { name: 'Tsi',    email: 'tsi@x.com',    role: 'TSI',          active: true },
  inativo:{ name: 'Inativo',email: 'ina@x.com',    role: 'ADMIN',        active: false },
};

before(async () => {
  env = await initializeTestEnvironment({
    projectId: 'demo-seedmax',
    firestore: { rules: readFileSync('../firestore.rules', 'utf8') },
  });
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    for (const [uid, u] of Object.entries(usuarios)) await setDoc(doc(db, 'users', uid), u);
    await setDoc(doc(db, 'qualidade', '_meta'), { versao: 1 });
    await setDoc(doc(db, 'qualidade', 'LOTS__0'), { json: '[]' });
    await setDoc(doc(db, 'lots', 'SOJA2526_X1'), { lote: 'X1' });
    await setDoc(doc(db, 'outra', 'a'), { x: 1 });
  });
});
after(async () => { await env.cleanup(); });

const como = (uid) => uid ? env.authenticatedContext(uid).firestore() : env.unauthenticatedContext().firestore();

test('sem login: nada pode ser lido nem gravado', async () => {
  const db = como(null);
  await assertFails(getDoc(doc(db, 'qualidade', '_meta')));
  await assertFails(getDocs(collection(db, 'qualidade')));
  await assertFails(getDoc(doc(db, 'users', 'admin')));
  await assertFails(getDoc(doc(db, 'lots', 'SOJA2526_X1')));
  await assertFails(getDoc(doc(db, 'outra', 'a')));
  await assertFails(setDoc(doc(db, 'users', 'novo'), { ...usuarios.admin }));
});

test('logado mas sem cadastro em users: bloqueado', async () => {
  const db = como('desconhecido');
  await assertFails(getDocs(collection(db, 'qualidade')));
  await assertFails(getDoc(doc(db, 'lots', 'SOJA2526_X1')));
  // e não consegue se cadastrar sozinho
  await assertFails(setDoc(doc(db, 'users', 'desconhecido'), { name: 'Eu', email: 'e@x.com', role: 'ADMIN', active: true }));
});

test('conta desativada: bloqueada mesmo sendo ADMIN', async () => {
  const db = como('inativo');
  await assertFails(getDocs(collection(db, 'qualidade')));
  await assertFails(getDoc(doc(db, 'lots', 'SOJA2526_X1')));
  await assertSucceeds(getDoc(doc(db, 'users', 'inativo'))); // só vê o próprio cadastro (para a mensagem)
  await assertFails(updateDoc(doc(db, 'users', 'inativo'), { active: true }));
});

test('perfis da Qualidade leem os dados; ninguém grava pelo navegador', async () => {
  for (const uid of ['admin', 'qual', 'visu']) {
    const db = como(uid);
    await assertSucceeds(getDocs(collection(db, 'qualidade')));
    await assertFails(setDoc(doc(db, 'qualidade', 'LOTS__0'), { json: '[1]' }));
    await assertFails(deleteDoc(doc(db, 'qualidade', '_meta')));
  }
});

test('perfil TSI não lê Qualidade, mas lê a Central de Lotes', async () => {
  const db = como('tsi');
  await assertFails(getDocs(collection(db, 'qualidade')));
  await assertSucceeds(getDoc(doc(db, 'lots', 'SOJA2526_X1')));
  await assertFails(setDoc(doc(db, 'lots', 'SOJA2526_X1'), { lote: 'Y' }));
});

test('usuário comum: lê só o próprio cadastro e não muda o próprio perfil', async () => {
  const db = como('qual');
  await assertSucceeds(getDoc(doc(db, 'users', 'qual')));
  await assertFails(getDoc(doc(db, 'users', 'admin')));
  await assertFails(getDocs(collection(db, 'users')));
  await assertFails(updateDoc(doc(db, 'users', 'qual'), { role: 'ADMIN' }));
});

test('ADMIN gerencia usuários com campos válidos', async () => {
  const db = como('admin');
  await assertSucceeds(getDocs(collection(db, 'users')));
  await assertSucceeds(setDoc(doc(db, 'users', 'novo'), { name: 'Novo', email: 'n@x.com', role: 'VISUALIZACAO', active: true }));
  await assertFails(setDoc(doc(db, 'users', 'novo2'), { name: 'N', email: 'n@x.com', role: 'DONO', active: true }));
  await assertFails(setDoc(doc(db, 'users', 'novo3'), { name: 'N', email: 'n@x.com', role: 'ADMIN', active: 'sim' }));
  await assertFails(setDoc(doc(db, 'users', 'novo4'), { name: 'N', email: 'n@x.com', role: 'ADMIN', active: true, extra: 1 }));
  await assertSucceeds(updateDoc(doc(db, 'users', 'novo'), { active: false }));
  await assertFails(deleteDoc(doc(db, 'users', 'admin'))); // não apaga a si mesmo
  await assertSucceeds(deleteDoc(doc(db, 'users', 'novo')));
});

test('coleções não previstas ficam fechadas até para ADMIN', async () => {
  const db = como('admin');
  await assertFails(getDoc(doc(db, 'outra', 'a')));
  await assertFails(setDoc(doc(db, 'outra', 'b'), { x: 1 }));
});

test('Central de Lotes: leitura por perfil autorizado, ninguém grava ou apaga pelo navegador', async () => {
  for (const uid of ['admin', 'qual', 'visu', 'tsi']) {
    const db = como(uid);
    await assertSucceeds(getDocs(collection(db, 'lots')));
    await assertFails(setDoc(doc(db, 'lots', 'SOJA2526_NOVO'), { lote: 'NOVO' }));
    await assertFails(updateDoc(doc(db, 'lots', 'SOJA2526_X1'), { situacao: 'PRONTO' }));
    await assertFails(deleteDoc(doc(db, 'lots', 'SOJA2526_X1')));
  }
  await assertFails(getDocs(collection(como(null), 'lots')));
  await assertFails(getDocs(collection(como('inativo'), 'lots')));
});
