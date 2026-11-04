'use strict';
const test = require('node:test');
const assert = require('node:assert');
const { decidir, PERFIL_MODULOS } = require('../decisao');
const { criarPonte, extrairBearer } = require('../ponte');

const cad = (role, extra) => Object.assign({ active: true, role, name: 'Teste', email: 't@x' }, extra);

test('matriz de perfis (política aprovada)', () => {
  const casos = [
    [cad('ADMIN'), 'tsi', true, 'ADMIN'], [cad('ADMIN'), 'rastrel', true, 'ADMIN'],
    [cad('ADMIN', { modulos: { tsi: 'OPERADOR' } }), 'tsi', true, 'OPERADOR'],
    [cad('TSI', { modulos: { tsi: 'OPERADOR' } }), 'tsi', true, 'OPERADOR'],
    [cad('TSI', { modulos: { tsi: 'VISUALIZADOR' } }), 'tsi', true, 'VISUALIZADOR'],
    [cad('TSI', { modulos: { tsi: 'OPERADOR', rastrel: 'OPERADOR' } }), 'rastrel', false],
    [cad('TSI'), 'tsi', false],                                   // sem modulos.tsi: não emite
    [cad('RASTREL', { modulos: { rastrel: 'OPERADOR' } }), 'rastrel', true, 'OPERADOR'],
    [cad('RASTREL', { modulos: { rastrel: 'OPERADOR' } }), 'tsi', false],
    [cad('QUALIDADE', { modulos: { tsi: 'ADMIN', rastrel: 'ADMIN' } }), 'tsi', false],
    [cad('QUALIDADE', { modulos: { tsi: 'ADMIN', rastrel: 'ADMIN' } }), 'rastrel', false],
    [cad('VISUALIZACAO', { modulos: { tsi: 'VISUALIZADOR' } }), 'tsi', false],   // VISUALIZACAO: nada por padrão
    [cad('TSI', { active: false, modulos: { tsi: 'OPERADOR' } }), 'tsi', false],
    [cad('TSI', { active: 'true', modulos: { tsi: 'OPERADOR' } }), 'tsi', false], // só booleano true
    [null, 'tsi', false],
    [cad('ADMIN'), 'qualidade', false], [cad('ADMIN'), '__proto__', false], [cad('ADMIN'), undefined, false],
    [cad('TSI', { modulos: { tsi: 'SUPERUSER' } }), 'tsi', false],
    [cad('ROOT', { modulos: { tsi: 'ADMIN' } }), 'tsi', false]
  ];
  for (const [c, m, ok, papel] of casos) {
    const d = decidir(c, m);
    assert.strictEqual(d.permitido, ok, JSON.stringify([c && c.role, c && c.modulos, m, d]));
    if (ok) assert.strictEqual(d.papel, papel);
  }
  assert.deepStrictEqual(PERFIL_MODULOS.VISUALIZACAO, []);
  assert.deepStrictEqual(PERFIL_MODULOS.QUALIDADE, []);
});

function deps(cadastros) {
  const eventos = [], assinados = [];
  return {
    eventos, assinados,
    verificar: async t => { if (!t.startsWith('id.')) throw new Error('inválido'); return { uid: t.slice(3) }; },
    lerCadastro: async uid => cadastros[uid] || null,
    assinar: async (m, uid, claims) => { const tok = 'custom.' + m + '.' + uid + '.SEGREDO'; assinados.push({ m, uid, claims }); return tok; },
    registrar: e => eventos.push(JSON.parse(JSON.stringify(e)))
  };
}

test('fluxo: autorizado recebe token; recusas não assinam nada; logs sem token', async () => {
  const d = deps({ uTsi: cad('TSI', { modulos: { tsi: 'VISUALIZADOR' } }), uQual: cad('QUALIDADE'), uOff: cad('TSI', { active: false, modulos: { tsi: 'OPERADOR' } }) });
  const ponte = criarPonte(d);
  const r = await ponte({ idToken: 'id.uTsi', modulo: 'tsi' });
  assert.ok(r.token.startsWith('custom.tsi.uTsi'));
  assert.deepStrictEqual(d.assinados[0].claims, { ponte: true, modulo: 'tsi', papelModulo: 'VISUALIZADOR' });
  for (const [tok, mod, codigo, motivo] of [
    ['id.uTsi', 'rastrel', 'permission-denied', 'perfil-sem-modulo'],
    ['id.uQual', 'tsi', 'permission-denied', 'perfil-sem-modulo'],
    ['id.uOff', 'tsi', 'permission-denied', 'inativo'],
    ['id.semCadastro', 'tsi', 'permission-denied', 'sem-cadastro'],
    ['forjado', 'tsi', 'unauthenticated', 'token-invalido'],
    [null, 'tsi', 'unauthenticated', 'sem-token']
  ]) {
    await assert.rejects(ponte({ idToken: tok, modulo: mod }), e => e.codigo === codigo && e.motivo === motivo);
  }
  assert.strictEqual(d.assinados.length, 1, 'só o pedido autorizado foi assinado');
  const log = JSON.stringify(d.eventos);
  assert.ok(!log.includes('SEGREDO') && !log.includes('id.uTsi') && !log.includes('forjado'), 'nenhum token no log');
  assert.ok(d.eventos.every(e => Object.keys(e).sort().join() === 'modulo,motivo,ms,permitido,uid'));
});

test('cabeçalho Authorization', () => {
  assert.strictEqual(extrairBearer('Bearer abc.def-_1'), 'abc.def-_1');
  assert.strictEqual(extrairBearer('Basic abc'), null);
  assert.strictEqual(extrairBearer('Bearer abc def'), null);
  assert.strictEqual(extrairBearer(undefined), null);
});
