'use strict';
const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');
const fs = require('node:fs');
const bi = require('../benef-inverno');

const CASOS = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'tests', 'casos_benef_inverno.json'), 'utf8'));

// ------------------------------------------------------------ casos compartilhados com o Python
for (const c of CASOS) {
  test(`consolidação: ${c.nome}`, () => {
    const { benef, conflitos, avisos } = bi.consolidar(c.linhas, c.culturas);
    const lotIds = benef.flatMap(x => x.detail.map(d => d.lotId)).sort();
    assert.deepStrictEqual(lotIds, [...c.espera.lotIds].sort());
    assert.deepStrictEqual(conflitos.map(x => x.tipo), c.espera.conflitos);
    if (c.espera.bags !== undefined) assert.strictEqual(bi.totais(benef).bags, c.espera.bags);
    if (c.espera.kg !== undefined) assert.strictEqual(bi.totais(benef).kg, c.espera.kg);
    if (c.espera.avisos !== undefined) assert.strictEqual(avisos.length, c.espera.avisos);
    if (c.espera.localizacao) assert.strictEqual(benef[0].detail[0].localizacao, c.espera.localizacao);
    if (c.espera.empresas) {                     // Prestação de Serviço: empresa pela aba
      const emp = {};
      for (const x of benef) for (const d of x.detail) emp[d.lotId] = d.empresa === undefined ? null : d.empresa;
      assert.deepStrictEqual(emp, c.espera.empresas);
    }
    // identidade única: nunca dois detalhes com o mesmo lotId
    assert.strictEqual(new Set(lotIds).size, lotIds.length);
  });
}

test('lotId igual ao contrato da Central (tests/test_regra_id_lote.py)', () => {
  assert.strictEqual(bi.montarIdLote('Aveia Branca', '99QQ01'), 'INV2626_AVEIA_BRANCA_99QQ01');
  assert.strictEqual(bi.montarIdLote(' trigo ', '99qq001'), 'INV2626_TRIGO_99QQ001');
  assert.strictEqual(bi.montarIdLote('Trigo Mourisco', 'TM 01'), 'INV2626_TRIGO_MOURISCO_TM01');
  assert.strictEqual(bi.montarIdLote('Ervilhaca', 'E/7'), 'INV2626_ERVILHACA_E-7');
  assert.strictEqual(bi.montarIdLote('Feijão', 'F1'), 'INV2626_FEIJAO_F1');
  assert.strictEqual(bi.montarIdLote('', 'X1'), 'INV2626_SEMCULTURA_X1');
  assert.strictEqual(bi.montarIdLote('Trigo', '   '), null);
});

// ------------------------------------------------------------ banco falso (Firestore mínimo)
function bancoFalso(inicial) {
  const docs = JSON.parse(JSON.stringify(inicial || {}));
  const registros = [];
  return {
    docs, registros,
    deps: (extra = {}) => Object.assign({
      verificar: async t => { if (t === 'tok-sync') return { uid: 'u-sync' }; if (t === 'tok-adm') return { uid: 'u-adm' }; if (t === 'tok-off') return { uid: 'u-off' }; throw new Error('x'); },
      lerCadastro: async uid => ({ 'u-sync': { role: 'SINC_BENEF_INVERNO', active: true }, 'u-adm': { role: 'ADMIN', active: true },
        'u-off': { role: 'SINC_BENEF_INVERNO', active: false } })[uid] || null,
      lerQualidade: async () => JSON.parse(JSON.stringify(docs)),
      publicar: async (partes, entrada, carimbo) => {          // = transação: relê o _meta AGORA
        const [novo, apagar] = bi.mesclarMeta(docs._meta || {}, bi.CONJUNTO, entrada, carimbo);
        for (const [id, c] of Object.entries(partes)) docs[id] = c;
        for (const id of apagar) delete docs[id];
        docs._meta = novo;
      },
      registrar: async r => { registros.push(JSON.parse(JSON.stringify(r))); },
      agora: () => new Date('2026-11-18T17:00:00Z'),
      log: () => {}
    }, extra)
  };
}

function semear(conjuntos) {
  const docs = { _meta: { versao: 1, atualizadoEm: 'x', datasets: {} } };
  for (const [nome, dados] of Object.entries(conjuntos)) {
    const t = bi.js(dados), h = bi.hash(t);
    docs[`${nome}__0`] = { nome, parte: 0, hash: h, json: t };
    docs._meta.datasets[nome] = { hash: h, partes: 1, bytes: t.length, itens: 1 };
  }
  return docs;
}

const L = (lote, extra) => Object.assign({ aba: 'INVERNO 2026', linha: 3, cultivar: 'CVTESTE9', cultura_planilha: null, data: null,
  safra: '26/26', categoria: 'S2', lote, peneira: 'S/P', embalagem: 'BB600', bags: 20, peso_bag: 600, total_kg: 12000,
  localizacao: 'UBS TESTE', observacoes: null }, extra);
const corpo = (linhas, extra) => Object.assign({ acao: 'publicar', formato: 1, planilha: { nome: 'LOTES BENEFICIADOS INVERNO 26-26.xlsx' }, linhas }, extra);
const BASE = () => semear({
  CV_META_INVERNO: { CVTESTE9: { cultura: 'Aveia Branca', obtentor: null }, TBIO: { cultura: 'Trigo', obtentor: null } },
  LOTS_INVERNO: [{ lote: '99QQ01', cultura: 'Aveia Branca' }], LOTS: [1, 2, 3], BENEF_INVERNO: []
});

async function rejeita(p, status, erro) {
  await assert.rejects(p, e => { assert.ok(e instanceof bi.ErroSync, e.message); assert.strictEqual(e.status, status); assert.strictEqual(e.erro, erro); return true; });
}

// ------------------------------------------------------------ autenticação
test('sem token / token inválido / outro perfil / inativo: recusa e não grava', async () => {
  const b = bancoFalso(BASE()); const s = bi.criarSincronizador(b.deps()); const antes = JSON.stringify(b.docs);
  await rejeita(s({ idToken: null, corpo: corpo([L('99QQ01')]) }), 401, 'sem_token');
  await rejeita(s({ idToken: 'lixo', corpo: corpo([L('99QQ01')]) }), 401, 'token_invalido');
  await rejeita(s({ idToken: 'tok-adm', corpo: corpo([L('99QQ01')]) }), 403, 'sem_permissao');   // nem ADMIN usa esta porta
  await rejeita(s({ idToken: 'tok-off', corpo: corpo([L('99QQ01')]) }), 403, 'sem_permissao');
  assert.strictEqual(JSON.stringify(b.docs), antes);
});

// ------------------------------------------------------------ só BENEF_INVERNO
test('publica e grava SOMENTE BENEF_INVERNO (+ entrada dele no _meta)', async () => {
  const b = bancoFalso(BASE()); const s = bi.criarSincronizador(b.deps());
  const antes = JSON.parse(JSON.stringify(b.docs));
  const r = await s({ idToken: 'tok-sync', corpo: corpo([L('99QQ01'), L('99QQ02', { linha: 4, bags: 8, total_kg: 4800 })]) });
  assert.deepStrictEqual([r.ok, r.mudou, r.totais], [true, true, { cultivares: 1, lotes: 2, bags: 28, kg: 16800 }]);
  const mudaram = Object.keys(b.docs).filter(k => JSON.stringify(b.docs[k]) !== JSON.stringify(antes[k])).sort();
  assert.deepStrictEqual(mudaram, ['BENEF_INVERNO__0', '_meta']);
  for (const k of Object.keys(antes._meta.datasets)) if (k !== 'BENEF_INVERNO')
    assert.deepStrictEqual(b.docs._meta.datasets[k], antes._meta.datasets[k]);
  assert.deepStrictEqual(b.docs._meta.mudaramNaUltima, ['BENEF_INVERNO']);
  assert.strictEqual(b.docs._meta.datasets.BENEF_INVERNO.sincronizadoEm, '18/11/2026 14:00');
  const gravado = JSON.parse(b.docs.BENEF_INVERNO__0.json);
  assert.deepStrictEqual(gravado[0].detail.map(d => d.lotId), ['INV2626_AVEIA_BRANCA_99QQ01', 'INV2626_AVEIA_BRANCA_99QQ02']);
  assert.strictEqual(b.registros.at(-1).resultado, 'PUBLICADO');
  assert.strictEqual(b.registros.at(-1).carimbo, '18/11/2026 14:00');
  // reenvio igual: nada muda
  const r2 = await s({ idToken: 'tok-sync', corpo: corpo([L('99QQ01'), L('99QQ02', { linha: 4, bags: 8, total_kg: 4800 })]) });
  assert.strictEqual(r2.mudou, false);
  assert.strictEqual(b.registros.at(-1).resultado, 'SEM_MUDANCA');
});

test('não aceita outro conjunto nem campos extras', async () => {
  const b = bancoFalso(BASE()); const s = bi.criarSincronizador(b.deps()); const antes = JSON.stringify(b.docs);
  await rejeita(s({ idToken: 'tok-sync', corpo: corpo([L('99QQ01')], { conjunto: 'LOTS_INVERNO' }) }), 400, 'payload_invalido');
  await rejeita(s({ idToken: 'tok-sync', corpo: corpo([L('99QQ01')], { LOTS: [] }) }), 400, 'payload_invalido');
  await rejeita(s({ idToken: 'tok-sync', corpo: corpo([L('99QQ01', { germinacao: 99 })]) }), 400, 'payload_invalido');
  assert.strictEqual(JSON.stringify(b.docs), antes);
});

test('payload vazio ou inconsistente: recusa com motivo claro', async () => {
  const b = bancoFalso(BASE()); const s = bi.criarSincronizador(b.deps()); const antes = JSON.stringify(b.docs);
  await rejeita(s({ idToken: 'tok-sync', corpo: corpo([]) }), 400, 'payload_invalido');
  await rejeita(s({ idToken: 'tok-sync', corpo: { acao: 'publicar' } }), 400, 'payload_invalido');
  await rejeita(s({ idToken: 'tok-sync', corpo: corpo([L('99QQ01', { bags: -3 })]) }), 400, 'payload_invalido');
  await rejeita(s({ idToken: 'tok-sync', corpo: corpo([L('99QQ01', { bags: 2.5 })]) }), 400, 'payload_invalido');
  await rejeita(s({ idToken: 'tok-sync', corpo: corpo([L('99QQ01', { lote: '' })]) }), 400, 'payload_invalido');
  await rejeita(s({ idToken: 'tok-sync', corpo: corpo([L('99QQ01', { total_kg: 99999 })]) }), 409, 'conflito');
  await rejeita(s({ idToken: 'tok-sync', corpo: { acao: 'apagar' } }), 400, 'acao_invalida');
  assert.strictEqual(JSON.stringify(b.docs), antes);
  assert.ok(b.registros.every(r => r.resultado !== 'PUBLICADO'));
});

test('conflito no mesmo lote: para tudo, nada publicado, conflito registrado', async () => {
  const b = bancoFalso(BASE()); const s = bi.criarSincronizador(b.deps()); const antes = JSON.stringify(b.docs);
  await rejeita(s({ idToken: 'tok-sync', corpo: corpo([L('99QQ01'), L('99QQ01', { linha: 4, categoria: 'C2' }), L('99QQ02', { linha: 5 })]) }), 409, 'conflito');
  assert.strictEqual(JSON.stringify(b.docs), antes);
  const reg = b.registros.at(-1);
  assert.strictEqual(reg.resultado, 'CONFLITO');
  assert.strictEqual(reg.conflitos[0].tipo, 'categoria_divergente');
});

test('linha 100% idêntica repetida: 409 linha_duplicada, nada publicado, lote e linhas informados', async () => {
  const b = bancoFalso(BASE()); const s = bi.criarSincronizador(b.deps()); const antes = JSON.stringify(b.docs);
  await assert.rejects(s({ idToken: 'tok-sync', corpo: corpo([L('99QQ01'), L('99QQ01', { linha: 9 })]) }), e => {
    assert.strictEqual(e.status, 409);
    assert.strictEqual(e.detalhes[0].tipo, 'linha_duplicada');
    assert.strictEqual(e.detalhes[0].lotId, 'INV2626_AVEIA_BRANCA_99QQ01');
    assert.deepStrictEqual(e.detalhes[0].onde, ["aba 'INVERNO 2026' linha 3", "aba 'INVERNO 2026' linha 9"]);
    return true;
  });
  assert.strictEqual(JSON.stringify(b.docs), antes);
  assert.strictEqual(b.registros.at(-1).resultado, 'CONFLITO');
});

test('queda brusca de lotes exige confirmação', async () => {
  const atual = [{ cultivar: 'CVTESTE9', cultura: 'Aveia Branca', lotes: 20, bags_total: 1, kg_total: 1, detail: [] }];
  const docs = BASE(); const t = bi.js(atual), h = bi.hash(t);
  docs.BENEF_INVERNO__0 = { nome: 'BENEF_INVERNO', parte: 0, hash: h, json: t }; docs._meta.datasets.BENEF_INVERNO = { hash: h, partes: 1 };
  const b = bancoFalso(docs); const s = bi.criarSincronizador(b.deps());
  await rejeita(s({ idToken: 'tok-sync', corpo: corpo([L('99QQ01')]) }), 422, 'queda_suspeita');
  const r = await s({ idToken: 'tok-sync', corpo: corpo([L('99QQ01')], { confirmarQueda: true }) });
  assert.strictEqual(r.mudou, true);
});

test('robô e função gravando ao mesmo tempo não apagam o índice um do outro', async () => {
  const b = bancoFalso(BASE());
  // a função leu o banco ANTES de o robô publicar LOTS...
  const s = bi.criarSincronizador(b.deps({
    lerQualidade: async () => {
      const copia = JSON.parse(JSON.stringify(b.docs));
      // ...e o robô publica LOTS no meio do caminho (como seedmax_dados.gravar_mesclando)
      const t = bi.js([9, 9]), h = bi.hash(t);
      b.docs.LOTS__0 = { nome: 'LOTS', parte: 0, hash: h, json: t };
      b.docs._meta = Object.assign({}, b.docs._meta, { datasets: Object.assign({}, b.docs._meta.datasets, { LOTS: { hash: h, partes: 1 } }) });
      return copia;
    }
  }));
  await s({ idToken: 'tok-sync', corpo: corpo([L('99QQ01')]) });
  // os dois conjuntos continuam consistentes (hash do índice = hash das partes)
  for (const nome of ['LOTS', 'BENEF_INVERNO']) assert.strictEqual(b.docs._meta.datasets[nome].hash, b.docs[`${nome}__0`].hash, nome);
  assert.deepStrictEqual(JSON.parse(b.docs.LOTS__0.json), [9, 9]);
});

test('estado: devolve só culturas por cultivar e o hash publicado (sem dados de lotes)', async () => {
  const b = bancoFalso(BASE()); const s = bi.criarSincronizador(b.deps());
  const r = await s({ idToken: 'tok-sync', corpo: { acao: 'estado' } });
  assert.deepStrictEqual(r.culturas, { CVTESTE9: 'Aveia Branca', TBIO: 'Trigo' });
  assert.deepStrictEqual(Object.keys(r).sort(), ['acao', 'culturas', 'ok', 'publicado']);
  await rejeita(s({ idToken: 'tok-adm', corpo: { acao: 'estado' } }), 403, 'sem_permissao');
});

// ------------------------------------------------------------ Prestação de Serviço (PGW / AMBEV)
const LINHAS_EMPRESAS = () => [
  L('PR01'), L('PR02', { linha: 4, bags: 10, total_kg: 6000 }),
  L('PG01', { aba: 'PGW', bags: 15, total_kg: 9000 }),
  L('AM01', { aba: 'AMBEV', cultivar: 'TBIO', bags: 8, total_kg: 4800 })
];

test('versão nova sobre conjunto publicado pela versão antiga: PGW antiga preservada, AMBEV separada, própria intacta', async () => {
  // conjunto como a função ANTIGA gravava (sem o campo empresa)
  const antigo = JSON.parse(JSON.stringify(bi.consolidar(LINHAS_EMPRESAS(), { CVTESTE9: 'Aveia Branca', TBIO: 'Trigo' }).benef));
  for (const c of antigo) for (const d of c.detail) delete d.empresa;
  const docs = semear({
    CV_META_INVERNO: { CVTESTE9: { cultura: 'Aveia Branca', obtentor: null }, TBIO: { cultura: 'Trigo', obtentor: null } },
    LOTS_INVERNO: [{ lote: 'PR01', cultura: 'Aveia Branca' }], LOTS_SERVICO_INVERNO: [{ lote: 'PG01', cultura: 'Aveia Branca' }],
    BENEF_INVERNO: antigo
  });
  const b = bancoFalso(docs); const s = bi.criarSincronizador(b.deps());
  const antes = JSON.parse(JSON.stringify(b.docs));

  const r = await s({ idToken: 'tok-sync', corpo: corpo(LINHAS_EMPRESAS()) });
  assert.strictEqual(r.mudou, true);                                        // só ganhou o campo empresa
  assert.deepStrictEqual(r.totais, { cultivares: 2, lotes: 4, bags: 53, kg: 31800 });

  // só BENEF_INVERNO e _meta mudam; LOTS_SERVICO_INVERNO (registros da PGW) e demais intactos
  const mudaram = Object.keys(b.docs).filter(k => JSON.stringify(b.docs[k]) !== JSON.stringify(antes[k])).sort();
  assert.deepStrictEqual(mudaram, ['BENEF_INVERNO__0', '_meta']);

  const novo = JSON.parse(b.docs.BENEF_INVERNO__0.json);
  const porLote = d => Object.fromEntries(d.flatMap(c => c.detail).map(x => [x.lote, x]));
  const velho = porLote(antigo), atual = porLote(novo);
  assert.deepStrictEqual(Object.keys(atual).sort(), Object.keys(velho).sort());   // nenhum lote some
  assert.deepStrictEqual(atual.PR01, velho.PR01);                                  // própria: idêntica, sem campo novo
  assert.deepStrictEqual(atual.PR02, velho.PR02);
  assert.strictEqual(atual.PG01.empresa, 'PGW');
  assert.strictEqual(atual.AM01.empresa, 'AMBEV');
  const { empresa: _e1, ...pg } = atual.PG01; assert.deepStrictEqual(pg, velho.PG01);  // só o campo novo foi acrescentado
  const { empresa: _e2, ...am } = atual.AM01; assert.deepStrictEqual(am, velho.AM01);

  // reenvio igual: nada muda
  const r2 = await s({ idToken: 'tok-sync', corpo: corpo(LINHAS_EMPRESAS()) });
  assert.strictEqual(r2.mudou, false);
});

test('mesmo lote na PGW e na AMBEV: conflito e nada é gravado', async () => {
  const b = bancoFalso(BASE()); const s = bi.criarSincronizador(b.deps()); const antes = JSON.stringify(b.docs);
  await rejeita(s({ idToken: 'tok-sync', corpo: corpo([L('IG01', { aba: 'PGW' }), L('IG01', { aba: 'AMBEV', linha: 9 })]) }), 409, 'conflito');
  assert.strictEqual(JSON.stringify(b.docs), antes);
  assert.strictEqual(b.registros.at(-1).resultado, 'CONFLITO');
  assert.strictEqual(b.registros.at(-1).conflitos[0].tipo, 'empresa_divergente');
});
