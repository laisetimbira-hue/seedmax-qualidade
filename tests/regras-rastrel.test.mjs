// Proposta de regras do RASTREL (integracao/rastrel.rules) contra o emulador.
import { test, before, after } from 'node:test';
import { readFileSync } from 'node:fs';
import { initializeTestEnvironment, assertFails, assertSucceeds } from '@firebase/rules-unit-testing';
import { doc, setDoc, updateDoc, deleteDoc, collection, getDocs, addDoc, runTransaction, serverTimestamp } from 'firebase/firestore';

let env;
const U = {
  adm: { nome: 'Adm', email: 'a@x', perfil: 'administrador', ativo: true },
  op:  { nome: 'Op',  email: 'o@x', perfil: 'operador',      ativo: true },
  vis: { nome: 'Vis', email: 'v@x', perfil: 'visualizador',  ativo: true },
  ina: { nome: 'Ina', email: 'i@x', perfil: 'operador',      ativo: false },
};
before(async () => {
  env = await initializeTestEnvironment({ projectId: 'demo-rastrel', firestore: { rules: readFileSync('../integracao/rastrel.rules', 'utf8') } });
  await env.withSecurityRulesDisabled(async (c) => {
    const db = c.firestore();
    for (const [uid, u] of Object.entries(U)) await setDoc(doc(db, 'usuarios', uid), u);
    await setDoc(doc(db, 'bags', 'b1'), { lote: '26S481G', numero_bag: '26S481G-01', status: 'aguardando_tag', epc: null });
    await setDoc(doc(db, 'epcs', 'E1'), { epc: 'E1', bag_id: 'bx', numero_bag: '26S481G-02' });
    await setDoc(doc(db, 'movimentacoes', 'm1'), { tipo_evento: 'vinculacao' });
    await setDoc(doc(db, 'pedidos_carga', 'oc1'), { numero_pedido: '10', status: 'aguardando' });
    await setDoc(doc(db, 'mapa', 'estado'), { a2: [] });
  });
});
after(async () => { await env.cleanup(); });
const db = (uid) => uid ? env.authenticatedContext(uid).firestore() : env.unauthenticatedContext().firestore();

test('sem login, sem cadastro ou desativado: nada', async () => {
  for (const uid of [null, 'estranho', 'ina']) {
    await assertFails(getDocs(collection(db(uid), 'bags')));
    await assertFails(updateDoc(doc(db(uid), 'bags', 'b1'), { status: 'expedido' }));
  }
});
test('visualizador: consulta tudo, não grava', async () => {
  const d = db('vis');
  for (const c of ['bags', 'epcs', 'movimentacoes', 'pedidos_carga', 'mapa']) await assertSucceeds(getDocs(collection(d, c)));
  await assertFails(addDoc(collection(d, 'bags'), { lote: '26S1A' }));
  await assertFails(setDoc(doc(d, 'mapa', 'estado'), { a2: [1] }));
});
test('operador: criar bags, vincular tag (transação), movimentar, conferir carga', async () => {
  const d = db('op');
  await assertSucceeds(addDoc(collection(d, 'bags'), { lote: '26S999A', numero_bag: '26S999A-01', status: 'aguardando_tag' }));
  await assertSucceeds(runTransaction(d, async (tx) => {
    tx.set(doc(d, 'epcs', 'E2'), { epc: 'E2', bag_id: 'b1', numero_bag: '26S481G-01', vinculado_em: serverTimestamp() });
    tx.update(doc(d, 'bags', 'b1'), { epc: 'E2', status: 'em_estoque' });
  }));
  await assertSucceeds(addDoc(collection(d, 'movimentacoes'), { tipo_evento: 'entrada_armazem' }));
  await assertSucceeds(setDoc(doc(d, 'epcs', 'E1'), { epc: 'E1', status: 'substituido' }, { merge: true }));
  await assertSucceeds(addDoc(collection(d, 'pedidos_carga'), { numero_pedido: '11', status: 'aguardando' }));
  await assertSucceeds(setDoc(doc(d, 'pedidos_carga', 'oc1', 'itens', 'b1'), { bag_id: 'b1', lote: '26S481G' }));
  await assertSucceeds(updateDoc(doc(d, 'pedidos_carga', 'oc1'), { status: 'expedido' }));
  await assertSucceeds(setDoc(doc(d, 'mapa', 'estado'), { a2: [1] }));
});
test('operador: não apaga dados nem histórico ("apagar tudo" bloqueado)', async () => {
  const d = db('op');
  await assertFails(deleteDoc(doc(d, 'bags', 'b1')));
  await assertFails(deleteDoc(doc(d, 'movimentacoes', 'm1')));
  await assertFails(updateDoc(doc(d, 'movimentacoes', 'm1'), { tipo_evento: 'x' }));
  await assertFails(deleteDoc(doc(d, 'pedidos_carga', 'oc1')));
  await assertFails(deleteDoc(doc(d, 'epcs', 'E1')));
  await assertFails(setDoc(doc(d, 'epcs', 'E9'), { epc: 'OUTRO' }));
  await assertFails(updateDoc(doc(d, 'usuarios', 'op'), { perfil: 'administrador' }));
});
test('administrador: pode apagar e gerenciar usuários', async () => {
  const d = db('adm');
  await assertSucceeds(deleteDoc(doc(d, 'movimentacoes', 'm1')));
  await assertSucceeds(setDoc(doc(d, 'usuarios', 'novo'), { nome: 'N', email: 'n@x', perfil: 'operador', ativo: true }));
  await assertFails(setDoc(doc(d, 'outra', 'x'), { a: 1 }));
});
