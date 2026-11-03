// Proposta de regras do TSI (integracao/tsi.rules) contra o emulador.
import { test, before, after } from 'node:test';
import { readFileSync } from 'node:fs';
import { initializeTestEnvironment, assertFails, assertSucceeds } from '@firebase/rules-unit-testing';
import { doc, getDoc, setDoc, updateDoc, deleteDoc, collection, getDocs, addDoc } from 'firebase/firestore';

let env;
const U = {
  adm:  { nome: 'Adm', email: 'a@x', perfil: 'administrador', ativo: true },
  op:   { nome: 'Op',  email: 'o@x', perfil: 'operador',      ativo: true },
  vis:  { nome: 'Vis', email: 'v@x', perfil: 'visualizador',  ativo: true },
  ina:  { nome: 'Ina', email: 'i@x', perfil: 'administrador', ativo: false },
};
before(async () => {
  env = await initializeTestEnvironment({ projectId: 'demo-tsi', firestore: { rules: readFileSync('../integracao/tsi.rules', 'utf8') } });
  await env.withSecurityRulesDisabled(async (c) => {
    const db = c.firestore();
    for (const [uid, u] of Object.entries(U)) await setDoc(doc(db, 'usuarios', uid), u);
    await setDoc(doc(db, 'produtos', 'p1'), { nome: 'Dermacor', quantidade: 10 });
    await setDoc(doc(db, 'receitas', 'r1'), { nome: 'C', itens: [] });
    await setDoc(doc(db, 'lotesTratamento', 'o1'), { numeroLote: '2953', status: 'aberta', lotesOrigem: ['26S133C'] });
    await setDoc(doc(db, 'movimentacoes', 'm1'), { tipo: 'entrada', quantidade: 5 });
  });
});
after(async () => { await env.cleanup(); });
const db = (uid) => uid ? env.authenticatedContext(uid).firestore() : env.unauthenticatedContext().firestore();

test('sem login: nada', async () => {
  for (const c of ['produtos', 'receitas', 'lotesTratamento', 'movimentacoes', 'usuarios']) await assertFails(getDocs(collection(db(null), c)));
});
test('conta sem cadastro (ex.: criada por fora): bloqueada', async () => {
  await assertFails(getDocs(collection(db('estranho'), 'produtos')));
  await assertFails(setDoc(doc(db('estranho'), 'usuarios', 'estranho'), { nome: 'E', email: 'e', perfil: 'administrador', ativo: true }));
});
test('conta desativada: bloqueada', async () => {
  await assertFails(getDocs(collection(db('ina'), 'produtos')));
  await assertFails(updateDoc(doc(db('ina'), 'produtos', 'p1'), { quantidade: 0 }));
});
test('visualizador: lê tudo, não grava nada', async () => {
  for (const c of ['produtos', 'receitas', 'lotesTratamento', 'movimentacoes']) await assertSucceeds(getDocs(collection(db('vis'), c)));
  await assertFails(updateDoc(doc(db('vis'), 'produtos', 'p1'), { quantidade: 1 }));
  await assertFails(addDoc(collection(db('vis'), 'movimentacoes'), { tipo: 'saida', quantidade: 1 }));
});
test('operador: fluxo normal do dia a dia funciona', async () => {
  const d = db('op');
  await assertSucceeds(addDoc(collection(d, 'produtos'), { nome: 'Novo', quantidade: 0 }));
  await assertSucceeds(updateDoc(doc(d, 'produtos', 'p1'), { quantidade: 8 }));
  await assertSucceeds(updateDoc(doc(d, 'receitas', 'r1'), { nome: 'C2' }));
  await assertSucceeds(addDoc(collection(d, 'lotesTratamento'), { numeroLote: '3000', status: 'aberta' }));
  await assertSucceeds(updateDoc(doc(d, 'lotesTratamento', 'o1'), { status: 'fechada' }));
  await assertSucceeds(addDoc(collection(d, 'movimentacoes'), { tipo: 'saida', quantidade: 2 }));
});
test('operador: não apaga nem mexe em usuários', async () => {
  const d = db('op');
  await assertFails(deleteDoc(doc(d, 'produtos', 'p1')));
  await assertFails(deleteDoc(doc(d, 'lotesTratamento', 'o1')));
  await assertFails(deleteDoc(doc(d, 'movimentacoes', 'm1')));
  await assertFails(updateDoc(doc(d, 'usuarios', 'op'), { perfil: 'administrador' }));
  await assertFails(getDocs(collection(d, 'usuarios')));
  await assertFails(addDoc(collection(d, 'movimentacoes'), { tipo: 'outra', quantidade: 1 }));
});
test('administrador: apaga e gerencia usuários', async () => {
  const d = db('adm');
  await assertSucceeds(deleteDoc(doc(d, 'movimentacoes', 'm1')));
  await assertSucceeds(getDocs(collection(d, 'usuarios')));
  await assertSucceeds(setDoc(doc(d, 'usuarios', 'novo'), { nome: 'N', email: 'n@x', perfil: 'operador', ativo: true }));
  await assertFails(setDoc(doc(d, 'usuarios', 'novo2'), { nome: 'N', email: 'n@x', perfil: 'dono', ativo: true }));
  await assertFails(deleteDoc(doc(d, 'usuarios', 'adm')));
});
test('coleção não prevista: fechada', async () => {
  await assertFails(setDoc(doc(db('adm'), 'outra', 'x'), { a: 1 }));
});
