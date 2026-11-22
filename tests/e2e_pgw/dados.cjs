// Dados 100% FICTÍCIOS do teste da PGW (prestação de serviço). Nenhum dado real aqui.
const cenario = 'teste';
const pgwReais = [   // "base" PGW fictícia: 5 lotes, 106 bags, 63.600 kg
  ['PGW-T-01', 25, 15000], ['PGW-T-02', 25, 15000], ['PGW-T-03', 25, 15000],
  ['PGW-T-04', 14, 8400], ['PGW-T-05', 17, 10200],
].map(([lote, bags, kg]) => ({ empresa: 'PGW', origem: 'Prestação de serviço', cultura: '', fonte_cultura: null,
  cultivar: 'CV PGW FICTICIA', categoria: 'S2', lote, data: null, bags, kg, peso_bag: 600, germinacao: null, status: null,
  observacao: null, pendencia: 'cultura a confirmar (sem coluna CULTURA nem cadastro único)' }));
// dois lotes PGW fictícios: só no cenário de teste automatizado (72.600 kg)
const pgwFicticios = [['PGW-FIC-01', 10, 6000], ['PGW-FIC-02', 5, 3000]].map(([lote, bags, kg]) => ({
  empresa: 'PGW', origem: 'Prestação de serviço', cultura: 'Aveia Preta', cultivar: 'FICTICIA PRETA', categoria: 'S1',
  lote, bags, kg, peso_bag: 600, germinacao: 92, status: 'Aprovado', observacao: 'lote fictício de teste', pendencia: null }));
const LOTS_SERVICO_INVERNO = cenario === 'teste' ? pgwReais.concat(pgwFicticios) : pgwReais;

// produção própria FICTÍCIA (soma 108.000 kg no Beneficiamento)
const proprios = [
  ['Trigo', 'TBIO FICTICIO', '26T001', 50, 30000, 95, 'Aprovado'],
  ['Trigo', 'TBIO FICTICIO', '26T002', 50, 30000, null, null],
  ['Aveia Branca', 'URS FICTICIA', '26AB001', 40, 24000, 88, 'Reprovado'],
  ['Aveia Branca', 'URS FICTICIA', '26AB002', 40, 24000, 91, 'Aprovado'],
];
const LOTS_INVERNO = proprios.map(([cultura, cultivar, lote, bags, kg, germinacao, status]) =>
  ({ cultura, cultivar, lote, bags, kg, germinacao, status, categoria: 'C1', peneira: 'S/P', lotId: 'INV2626_' + cultura.toUpperCase().replace(/ /g, '') + '_' + lote }));
const CV_META_INVERNO = { 'TBIO FICTICIO': { cultura: 'Trigo' }, 'URS FICTICIA': { cultura: 'Aveia Branca' },
  'CV PGW FICTICIA': { cultura: 'Aveia Branca' }, 'FICTICIA PRETA': { cultura: 'Aveia Preta' } };
const linha = (cultura, cultivar, lote, bags, kg, local, obs) => ({ lotId: 'x', lote, cultivar, cultura, categoria: 'C1', peneira: 'S/P',
  embalagem: 'BAG 600', bags, peso_bag: 600, kg, localizacao: local, observacoes: obs || null });
const det = [
  ...proprios.map(([c, cv, l, b, kg]) => linha(c, cv, l, b, kg, 'UBS 1')),
  ...pgwReais.map(p => linha('Aveia Branca', 'CV PGW FICTICIA', p.lote, p.bags, p.kg, 'UBS 2', 'PGW')),
  ...(cenario === 'teste' ? pgwFicticios.map(p => linha('Aveia Preta', p.cultivar, p.lote, p.bags, p.kg, 'UBS 2')) : []),
  // FICTÍCIO: linha sem análise em lugar nenhum → "Origem a conferir"
  linha('Trigo', 'TBIO FICTICIO', '26T099', 10, 6000, 'UBS 1', 'linha fictícia: origem a conferir'),
];
const porCv = {};
det.forEach(d => { (porCv[d.cultivar] = porCv[d.cultivar] || { cultivar: d.cultivar, cultura: d.cultura, detail: [] }).detail.push(d); });
const BENEF_INVERNO = Object.values(porCv).map(c => Object.assign(c, {
  bags: c.detail.reduce((s, d) => s + d.bags, 0), kg: c.detail.reduce((s, d) => s + d.kg, 0),
  lotes: c.detail.length, localizacoes: [...new Set(c.detail.map(d => d.localizacao))] }));

const vazios = { LOTS: [], SUMMARY: [], SUMMARY_PREV: [], PMS_CV: {}, LOTES_COMPRADOS: [], NOSSO_PLANTIO: [],
  NOSSO_PLANTIO_INVERNO: [], LOTES_COMPRADOS_INVERNO: [], HISTORICO_APROVACAO: [], MUDANCAS_RECENTES: {},
  BENEF: [], DIAG_DATA: {}, TZ_DATA: {}, CAMPOS_SIGEF: [], CV_META: {}, CV_UBS: {} };
const conjuntos = Object.assign({}, vazios, { LOTS_INVERNO, CV_META_INVERNO, BENEF_INVERNO, LOTS_SERVICO_INVERNO });
const qualidade = { _meta: { versao: 1, atualizado: '22/11/2026 13:00', datasets: {} } };
for (const [nome, v] of Object.entries(conjuntos)) {
  qualidade._meta.datasets[nome] = { partes: 1, hash: 'h' };
  qualidade[nome + '__0'] = { hash: 'h', json: JSON.stringify(v) };
}
// Central de Lotes (lots/): só os lotes próprios fictícios — a PGW NÃO está aqui
const lots = {};
LOTS_INVERNO.forEach(l => { lots[l.lotId] = { lotId: l.lotId, lotCode: l.lote, crop: 'INV2626', cultura: l.cultura, cultivar: l.cultivar,
  categoria: 'C1', peneira: 'S/P', qualidadeStatus: l.status ? l.status.toUpperCase() : 'PENDENTE', tsiStatus: 'NÃO CONECTADO',
  rastrelStatus: 'NÃO CONECTADO', situacao: 'INDETERMINADO', motivo: '', modulos: ['qualidade'], divergencias: [], presente: true,
  qualidade: { rotulo: l.status || 'sem status', fonte: 'producao', germ: l.germinacao, kg: l.kg, bags: l.bags } }; });
module.exports = { qualidade, lots, LOTS_SERVICO_INVERNO };
