// Regras do TSI (integracao/tsi.rules) contra o emulador.
import { test, before, after } from 'node:test';
import { readFileSync } from 'node:fs';
import { initializeTestEnvironment, assertFails, assertSucceeds } from '@firebase/rules-unit-testing';
import { doc, setDoc, updateDoc, deleteDoc, collection, getDocs, getDoc, addDoc, writeBatch, serverTimestamp } from 'firebase/firestore';

let env;
const U = {
  adm: { name: 'Adm', email: 'a@x', role: 'ADMIN', active: true },
  op:  { name: 'Op',  email: 'o@x', role: 'OPERADOR', active: true },
  vis: { name: 'Vis', email: 'v@x', role: 'VISUALIZADOR', active: true },
  ina: { name: 'Ina', email: 'i@x', role: 'ADMIN', active: false },
};
const mov = (x = {}) => { const o = { produtoId: 'p1', produtoNome: 'Dermacor', tipo: 'saida', motivo: 'Consumo', quantidade: 2, responsavel: 'Op', saldoApos: 8, criadoEm: serverTimestamp(), ...x }; for (const k of Object.keys(o)) if (o[k] === undefined) delete o[k]; return o; };
before(async () => {
  env = await initializeTestEnvironment({ projectId: 'demo-tsi', firestore: { rules: readFileSync('../integracao/tsi.rules', 'utf8') } });
  await env.withSecurityRulesDisabled(async (c) => {
    const db = c.firestore();
    for (const [uid, u] of Object.entries(U)) await setDoc(doc(db, 'users', uid), u);
    await setDoc(doc(db, 'produtos', 'p1'), { nome: 'Dermacor', quantidade: 10 });
    await setDoc(doc(db, 'receitas', 'r1'), { nome: 'C', itens: [] });
    await setDoc(doc(db, 'lotesTratamento', 'o1'), { numeroLote: '2953', status: 'aberta', lotesOrigem: ['26S133C'] });
    await setDoc(doc(db, 'movimentacoes', 'm1'), { tipo: 'entrada', quantidade: 5, responsavel: 'X' });
    await setDoc(doc(db, 'usuarios', 'legado'), { nome: 'x' });
  });
});
after(async () => { await env.cleanup(); });
const db = (uid) => uid ? env.authenticatedContext(uid).firestore() : env.unauthenticatedContext().firestore();

test('sem login: nada', async () => {
  for (const c of ['produtos', 'receitas', 'lotesTratamento', 'movimentacoes', 'users']) await assertFails(getDocs(collection(db(null), c)));
});
test('usuário não autorizado (sem cadastro): bloqueado e não se cadastra sozinho', async () => {
  await assertFails(getDocs(collection(db('estranho'), 'produtos')));
  await assertFails(setDoc(doc(db('estranho'), 'users', 'estranho'), { name: 'E', email: 'e', role: 'ADMIN', active: true }));
});
test('usuário active=false: bloqueado mesmo sendo ADMIN', async () => {
  await assertFails(getDocs(collection(db('ina'), 'produtos')));
  await assertFails(updateDoc(doc(db('ina'), 'produtos', 'p1'), { quantidade: 0 }));
  await assertSucceeds(getDoc(doc(db('ina'), 'users', 'ina')));
});
test('VISUALIZADOR: consulta tudo, não altera nada', async () => {
  const d = db('vis');
  for (const c of ['produtos', 'receitas', 'lotesTratamento', 'movimentacoes']) await assertSucceeds(getDocs(collection(d, c)));
  await assertFails(updateDoc(doc(d, 'produtos', 'p1'), { quantidade: 1 }));
  await assertFails(addDoc(collection(d, 'movimentacoes'), mov()));
  await assertFails(updateDoc(doc(d, 'lotesTratamento', 'o1'), { status: 'fechada' }));
});
test('OPERADOR: operações do dia a dia (como o app grava)', async () => {
  const d = db('op');
  await assertSucceeds(addDoc(collection(d, 'produtos'), { nome: 'Novo', quantidade: 0 }));
  await assertSucceeds(updateDoc(doc(d, 'receitas', 'r1'), { nome: 'C2' }));
  await assertSucceeds(addDoc(collection(d, 'lotesTratamento'), { numeroLote: '3000', status: 'aberta' }));
  // fechar ordem = lote + movimentação + baixa no produto, num lote de gravação
  const b = writeBatch(d);
  b.update(doc(d, 'lotesTratamento', 'o1'), { status: 'fechada' });
  b.set(doc(collection(d, 'movimentacoes')), mov());
  b.update(doc(d, 'produtos', 'p1'), { quantidade: 8 });
  await assertSucceeds(b.commit());
});
test('histórico: só registros novos, com usuário e data', async () => {
  const d = db('op');
  await assertFails(addDoc(collection(d, 'movimentacoes'), mov({ responsavel: undefined })));
  await assertFails(addDoc(collection(d, 'movimentacoes'), mov({ criadoEm: undefined })));
  await assertFails(addDoc(collection(d, 'movimentacoes'), mov({ tipo: 'ajuste' })));
  await assertFails(updateDoc(doc(d, 'movimentacoes', 'm1'), { quantidade: 99 }));
  await assertFails(deleteDoc(doc(d, 'movimentacoes', 'm1')));
});
test('exclusões administrativas restritas (Excluir ordem, Desfazer acerto, ZERAR)', async () => {
  const d = db('op');
  await assertFails(deleteDoc(doc(d, 'lotesTratamento', 'o1')));
  await assertFails(deleteDoc(doc(d, 'produtos', 'p1')));
  await assertFails(deleteDoc(doc(d, 'receitas', 'r1')));
  await assertFails(updateDoc(doc(d, 'users', 'op'), { role: 'ADMIN' }));
  await assertFails(getDocs(collection(d, 'users')));
});
test('ADMIN: trabalha normalmente, inclusive excluir e gerenciar usuários', async () => {
  const d = db('adm');
  await assertSucceeds(addDoc(collection(d, 'movimentacoes'), mov({ responsavel: 'Adm' })));
  await assertSucceeds(updateDoc(doc(d, 'produtos', 'p1'), { quantidade: 9 }));
  await assertSucceeds(getDocs(collection(d, 'usuarios')));
  await assertSucceeds(getDocs(collection(d, 'users')));
  await assertSucceeds(setDoc(doc(d, 'users', 'novo'), { name: 'N', email: 'n@x', role: 'OPERADOR', active: true }));
  await assertFails(setDoc(doc(d, 'users', 'novo2'), { name: 'N', email: 'n@x', role: 'DONO', active: true }));
  await assertFails(deleteDoc(doc(d, 'users', 'adm')));
  await assertSucceeds(deleteDoc(doc(d, 'movimentacoes', 'm1')));
  await assertSucceeds(deleteDoc(doc(d, 'lotesTratamento', 'o1')));
});
test('coleção não prevista: fechada', async () => {
  await assertFails(setDoc(doc(db('adm'), 'outra', 'x'), { a: 1 }));
  await assertFails(setDoc(doc(db('adm'), 'usuarios', 'x'), { a: 1 }));
});
test('diagnóstico: escrita com pré-condição "existe" em documento novo é avaliada como update', async () => {
  // updateDoc em documento inexistente = escrita com pré-condição exists=true.
  // Se o Firestore avalia como "update", o OPERADOR recebe permission-denied
  // (update de histórico só ADMIN) e o ADMIN recebe not-found.
  const codigo = async (uid) => { try { await updateDoc(doc(db(uid), 'movimentacoes', 'nao-existe-' + uid), mov()); return 'ok'; } catch (e) { return e.code; } };
  const op = await codigo('op'), adm = await codigo('adm');
  console.log('# DIAGNOSTICO operador=' + op + ' admin=' + adm);
  // e a criação real pelo operador continua permitida:
  await assertSucceeds(addDoc(collection(db('op'), 'movimentacoes'), mov()));
});
