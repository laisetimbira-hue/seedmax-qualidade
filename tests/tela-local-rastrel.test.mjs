// Tela Inverno › Beneficiamento: localização atual do RASTREL × planilha (sem navegador).
// Rodar: node --test tests/tela-local-rastrel.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');

test('bloco do dashboard com a localização continua com sintaxe válida', () => {
  const blocos = [...html.matchAll(/<script type="text\/seedmax-app">([\s\S]*?)<\/script>/g)].map(m => m[1]);
  const bloco = blocos.find(b => b.includes('function invLocalHtml('));
  assert.ok(bloco, 'função invLocalHtml no bloco do dashboard');
  assert.doesNotThrow(() => new vm.Script(bloco));
});

test('conjunto LOCAL_RASTREL_INVERNO é opcional (sem ele a tela abre com a planilha)', () => {
  const m = /const SEEDMAX_DATASETS_OPCIONAIS = (\[[^\]]*\])/.exec(html);
  assert.ok(JSON.parse(m[1]).includes('LOCAL_RASTREL_INVERNO'));
  assert.match(html, /const SEEDMAX_DATASETS = \[[^\]]*"LOCAL_RASTREL_INVERNO"\]/);
});

function carregar(local) {
  const ini = html.indexOf('function invBenefEsc(v)');
  const fim = html.indexOf('// ---- Origem de cada linha do Beneficiamento');
  const ctx = { LOCAL_RASTREL_INVERNO: local };
  vm.createContext(ctx);
  vm.runInContext(html.slice(ini, fim) + '\nthis.f = { invLocalHtml, invLocaisDe, invLocalRastrel };', ctx);
  return ctx.f;
}

const LOCAL = {
  atualizadoEm: '27/11/2026 10:00',
  lotes: {
    INV2626_TRIGO_26T001: { posicoes: [
      { posicao: 'A3B12', bags: 3, fonte: 'tag' }, { posicao: 'A4B2', bags: 2, fonte: 'sem_tag' },
      { posicao: 'A3B11', fonte: 'mapa', qtd: '5BB', misto: true }], semPosicao: 1 },
    INV2626_AVEIA_BRANCA_26T001: { posicoes: [], expedidos: 4, avisos: ['Mapa: lote 26T001 homônimo'] },
  },
};

test('várias posições do RASTREL substituem a planilha', () => {
  const f = carregar(LOCAL);
  const d = { lotId: 'INV2626_TRIGO_26T001', lote: '26T001', localizacao: 'UBS <manual>' };
  assert.deepEqual([...f.invLocaisDe(d)], ['A3B12', 'A4B2', 'A3B11']);
  const h = f.invLocalHtml(d);
  for (const t of ['A3B12', '3 BB', 'tag NFC', 'A4B2', 'sem tag', 'A3B11', '5BB', 'mapa', 'célula com outros lotes',
                   '1 bag(s) sem posição', 'RASTREL', '27/11/2026 10:00']) assert.ok(h.includes(t), t);
  assert.ok(h.includes('UBS &lt;manual&gt;'), 'planilha só no título, escapada');
  assert.ok(!h.includes('<manual>'));
});

test('sem posição no RASTREL: usa a planilha (com aviso e expedidos)', () => {
  const f = carregar(LOCAL);
  const d = { lotId: 'INV2626_AVEIA_BRANCA_26T001', localizacao: 'UBS 2' };
  assert.deepEqual([...f.invLocaisDe(d)], ['UBS 2']);
  const h = f.invLocalHtml(d);
  assert.ok(h.startsWith('UBS 2') && h.includes('planilha') && h.includes('4 bag(s) expedido(s) no RASTREL') && h.includes('⚠'));
});

test('lote fora do conjunto, conjunto ausente (lista vazia) ou sem lotId: planilha', () => {
  for (const local of [LOCAL, [], undefined]) {
    const f = carregar(local);
    assert.deepEqual([...f.invLocaisDe({ lotId: 'INV2626_NABO_X', localizacao: 'UBS 1' })], ['UBS 1']);
    assert.ok(f.invLocalHtml({ localizacao: 'UBS 1' }).startsWith('UBS 1'));
    assert.equal(f.invLocalHtml({ lotId: 'INV2626_NABO_X' }), '—');
    assert.deepEqual([...f.invLocaisDe({ lotId: 'INV2626_NABO_X' })], []);
  }
});
