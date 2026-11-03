// Regras do RASTREL (integracao/rastrel.rules) contra o emulador.
import { test, before, after } from 'node:test';
import { readFileSync } from 'node:fs';
import { initializeTestEnvironment, assertFails, assertSucceeds } from '@firebase/rules-unit-testing';
import { doc, setDoc, updateDoc, deleteDoc, collection, getDocs, getDoc, addDoc, runTransaction, writeBatch, serverTimestamp } from 'firebase/firestore';

let env;
const U = {
  adm: { name: 'Adm', email: 'a@x', role: 'ADMIN', active: true },
  op:  { name: 'Op',  email: 'o@x', role: 'OPERADOR', active: true },
  vis: { name: 'Vis', email: 'v@x', role: 'VISUALIZADOR', active: true },
  ina: { name: 'Ina', email: 'i@x', role: 'OPERADOR', active: false },
};
const ev = (x = {}) => { const o = { bag_id: 'b1', numero_bag: '26S481G-01', tipo_evento: 'entrada_armazem', operador: 'Op', dispositivo: 'App', criado_em: serverTimestamp(), ...x }; for (const k of Object.keys(o)) if (o[k] === undefined) delete o[k]; return o; };
before(async () => {
  env = await initializeTestEnvironment({ projectId: 'demo-rastrel', firestore: { rules: readFileSync('../integracao/rastrel.rules', 'utf8') } });
  await env.withSecurityRulesDisabled(async (c) => {
    const db = c.firestore();
    for (const [uid, u] of Object.entries(U)) await setDoc(doc(db, 'users', uid), u);
    await setDoc(doc(db, 'bags', 'b1'), { lote: '26S481G', numero_bag: '26S481G-01', status: 'aguardando_tag', epc: null });
    await setDoc(doc(db, 'bags', 'b2'), { lote: '26S481G', numero_bag: '26S481G-02', status: 'em_estoque', epc: 'E1' });
    await setDoc(doc(db, 'epcs', 'E1'), { epc: 'E1', bag_id: 'b2', numero_bag: '26S481G-02' });
    await setDoc(doc(db, 'movimentacoes', 'm1'), { tipo_evento: 'vinculacao', operador: 'X' });
    await setDoc(doc(db, 'pedidos_carga', 'oc1'), { numero_pedido: '10', status: 'aguardando' });
    await setDoc(doc(db, 'pedidos_carga', 'oc1', 'itens', 'b2'), { bag_id: 'b2' });
    await setDoc(doc(db, 'mapa', 'estado'), { a2: [] });
  });
});
after(async () => { await env.cleanup(); });
const db = (uid) => uid ? env.authenticatedContext(uid).firestore() : env.unauthenticatedContext().firestore();

test('sem login, não autorizado ou active=false: bloqueados', async () => {
  for (const uid of [null, 'estranho', 'ina']) {
    await assertFails(getDocs(collection(db(uid), 'bags')));
    await assertFails(updateDoc(doc(db(uid), 'bags', 'b1'), { status: 'expedido' }));
  }
  await assertFails(setDoc(doc(db('estranho'), 'users', 'estranho'), { name: 'E', email: 'e', role: 'ADMIN', active: true }));
});
test('VISUALIZADOR: consulta tudo, não altera', async () => {
  const d = db('vis');
  for (const c of ['bags', 'epcs', 'movimentacoes', 'pedidos_carga', 'mapa']) await assertSucceeds(getDocs(collection(d, c)));
  await assertFails(addDoc(collection(d, 'bags'), { lote: '26S1A' }));
  await assertFails(setDoc(doc(d, 'mapa', 'estado'), { a2: [1] }));
  await assertFails(addDoc(collection(d, 'movimentacoes'), ev()));
});
test('OPERADOR: criar bags, vincular e substituir tag, movimentar, conferir e expedir carga', async () => {
  const d = db('op');
  await assertSucceeds(addDoc(collection(d, 'bags'), { lote: '26S999A', numero_bag: '26S999A-01', status: 'aguardando_tag', criado_em: serverTimestamp() }));
  await assertSucceeds(runTransaction(d, async (tx) => {
    await tx.get(doc(d, 'epcs', 'E2'));
    tx.set(doc(d, 'epcs', 'E2'), { epc: 'E2', bag_id: 'b1', numero_bag: '26S481G-01', vinculado_em: serverTimestamp() });
    tx.update(doc(d, 'bags', 'b1'), { epc: 'E2', status: 'em_estoque' });
  }));
  await assertSucceeds(addDoc(collection(d, 'movimentacoes'), ev({ tipo_evento: 'vinculacao' })));
  await assertSucceeds(runTransaction(d, async (tx) => {
    tx.set(doc(d, 'epcs', 'E3'), { epc: 'E3', bag_id: 'b2', numero_bag: '26S481G-02' });
    tx.set(doc(d, 'epcs', 'E1'), { epc: 'E1', bag_id: 'b2', status: 'substituido', substituido_por: 'E3' }, { merge: true });
    tx.update(doc(d, 'bags', 'b2'), { epc: 'E3', epc_anterior: 'E1' });
  }));
  await assertSucceeds(addDoc(collection(d, 'pedidos_carga'), { numero_pedido: '11', status: 'aguardando' }));
  await assertSucceeds(setDoc(doc(d, 'pedidos_carga', 'oc1', 'itens', 'b1'), { bag_id: 'b1', lote: '26S481G' }));
  await assertSucceeds(updateDoc(doc(d, 'pedidos_carga', 'oc1'), { status: 'expedido' }));
  await assertSucceeds(updateDoc(doc(d, 'bags', 'b2'), { status: 'expedido', localizacao_atual: '' }));
  await assertSucceeds(setDoc(doc(d, 'mapa', 'estado'), { a2: [1], garagem: [], movs: [], notas: {}, updatedAt: 1 }));
});
test('histórico: só registros novos, com operador e data; antigos intocáveis', async () => {
  const d = db('op');
  await assertFails(addDoc(collection(d, 'movimentacoes'), ev({ operador: undefined })));
  await assertFails(addDoc(collection(d, 'movimentacoes'), ev({ criado_em: undefined })));
  await assertFails(updateDoc(doc(d, 'movimentacoes', 'm1'), { tipo_evento: 'x' }));
  await assertFails(deleteDoc(doc(d, 'movimentacoes', 'm1')));
  await assertFails(updateDoc(doc(d, 'pedidos_carga', 'oc1', 'itens', 'b2'), { bag_id: 'x' }));
});
test('"Apagar todos os dados" bloqueado para OPERADOR (camada do banco)', async () => {
  const d = db('op');
  const b = writeBatch(d);
  b.delete(doc(d, 'bags', 'b1')); b.delete(doc(d, 'movimentacoes', 'm1')); b.delete(doc(d, 'pedidos_carga', 'oc1'));
  await assertFails(b.commit());
  await assertFails(deleteDoc(doc(d, 'bags', 'b1')));
  await assertFails(deleteDoc(doc(d, 'pedidos_carga', 'oc1', 'itens', 'b2')));
  await assertFails(deleteDoc(doc(d, 'epcs', 'E1')));
  await assertFails(setDoc(doc(d, 'epcs', 'E9'), { epc: 'OUTRO' }));
  await assertFails(updateDoc(doc(d, 'users', 'op'), { role: 'ADMIN' }));
});
test('ADMIN: trabalha normalmente e pode apagar e gerenciar usuários', async () => {
  const d = db('adm');
  await assertSucceeds(addDoc(collection(d, 'movimentacoes'), ev({ operador: 'Adm' })));
  await assertSucceeds(getDocs(collection(d, 'users')));
  await assertSucceeds(setDoc(doc(d, 'users', 'novo'), { name: 'N', email: 'n@x', role: 'OPERADOR', active: true }));
  const b = writeBatch(d);
  b.delete(doc(d, 'movimentacoes', 'm1')); b.delete(doc(d, 'pedidos_carga', 'oc1', 'itens', 'b2'));
  await assertSucceeds(b.commit());
  await assertFails(setDoc(doc(d, 'outra', 'x'), { a: 1 }));
});
