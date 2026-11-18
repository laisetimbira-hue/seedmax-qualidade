'use strict';
// SEEDMAX — Beneficiamento de Inverno: núcleo da função segura de sincronização.
//
// Sem dependência de Firebase: o acesso ao banco e à autenticação chega por
// injeção (deps). A Cloud Function (index.js) só liga as peças; os testes
// provam o fluxo com um banco falso.
//
// O que a função ACEITA: as linhas da planilha "LOTES BENEFICIADOS INVERNO"
// (lidas pelo computador da empresa). O que ela GRAVA: SOMENTE o conjunto
// qualidade/BENEF_INVERNO (+ a entrada dele no índice qualidade/_meta) e o
// registro da sincronização em sincronizacoes/BENEF_INVERNO. Nada mais.
//
// Identidade do lote (regra única do SEEDMAX): Safra + Cultura + Lote,
// INV2626_<CULTURA>_<LOTE> — igual a central_lotes.montar_id_lote (Python)
// e montarIdLote (TSI/RASTREL). Consolidação idêntica a
// scripts/benef_inverno.py (casos em tests/casos_benef_inverno.json).

const crypto = require('node:crypto');

const CONJUNTO = 'BENEF_INVERNO';
const SAFRA = 'INV2626';
const FORMATO = 1;
const PERFIL = 'SINC_BENEF_INVERNO';         // users/{uid}.role da conta do computador da empresa
const COLECAO = 'qualidade';
const TAMANHO_PARTE = 900000;
const ESQUEMA = 1;
const TOLERANCIA_KG = 0.5;
const LIMITES = Object.freeze({ linhas: 5000, texto: 200, bags: 100000, peso: 5000, kg: 50000000 });

const CAMPOS_LINHA = ['aba', 'linha', 'cultivar', 'cultura_planilha', 'data', 'safra', 'categoria', 'lote',
  'peneira', 'embalagem', 'bags', 'peso_bag', 'total_kg', 'localizacao', 'observacoes'];
const CAMPOS_DO_LOTE = ['cultivar', 'categoria', 'peneira', 'embalagem', 'peso_bag'];
const CAMPOS_DA_LINHA = ['cultivar', 'categoria', 'peneira', 'embalagem', 'bags', 'peso_bag', 'kg',
  'localizacao', 'observacoes', 'data', 'safra'];

class ErroSync extends Error {
  constructor(status, erro, mensagem, detalhes) {
    super(mensagem); this.status = status; this.erro = erro; this.mensagem = mensagem; this.detalhes = detalhes;
  }
}

// ------------------------------------------------------------ normalização

const semAcento = s => String(s).normalize('NFD').replace(/[̀-ͯ]/g, '');
const norm = t => semAcento(String(t == null ? '' : t).normalize('NFKD')).replace(/[^A-Za-z0-9]+/g, ' ').trim().toUpperCase();
const cmp = v => (typeof v === 'string' ? norm(v) : v);
const n = x => (x == null ? null : (Math.abs(x - Math.round(x)) < 1e-6 ? Math.round(x) : Math.round(x * 100) / 100));

function codigoLote(bruto) {
  let s = String(bruto == null ? '' : bruto).trim().toUpperCase();
  s = s.replace(/\s+/g, '');
  s = s.replace(/[^A-Z0-9/_-]+$/, '');
  s = s.replace(/^[^A-Z0-9]+/, '');
  return s;
}

function normalizarCultura(c) {
  return semAcento(String(c == null ? '' : c).trim().toUpperCase()).replace(/[^A-Z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

function montarIdLote(cultura, lote) {
  const seguro = codigoLote(lote).replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '');
  if (!seguro) return null;
  return `${SAFRA}_${normalizarCultura(cultura) || 'SEMCULTURA'}_${seguro}`;
}

function culturaDoCultivar(cultivar, culturas) {
  if (!culturas) return null;
  const alvo = norm(cultivar);
  for (const k of Object.keys(culturas).sort()) {
    if (norm(k) === alvo) {
      const v = culturas[k];
      return (v && typeof v === 'object' ? v.cultura : v) || null;
    }
  }
  return null;
}

// ------------------------------------------------------------ validação

function validarPayload(corpo) {
  const erros = [];
  if (!corpo || typeof corpo !== 'object' || Array.isArray(corpo)) throw new ErroSync(400, 'payload_invalido', 'corpo da requisição não é um objeto JSON');
  const extras = Object.keys(corpo).filter(k => !['acao', 'formato', 'conjunto', 'planilha', 'linhas', 'confirmarQueda'].includes(k));
  if (extras.length) erros.push(`campos não aceitos: ${extras.join(', ')}`);
  if (corpo.conjunto !== undefined && corpo.conjunto !== CONJUNTO) erros.push(`só o conjunto ${CONJUNTO} é aceito`);
  if (corpo.formato !== FORMATO) erros.push(`formato deve ser ${FORMATO}`);
  const p = corpo.planilha;
  if (!p || typeof p !== 'object' || typeof p.nome !== 'string' || !p.nome.trim() || p.nome.length > LIMITES.texto) erros.push('planilha.nome obrigatório');
  if (p && p.modificadaEm != null && (typeof p.modificadaEm !== 'string' || p.modificadaEm.length > 40)) erros.push('planilha.modificadaEm inválido');
  if (corpo.confirmarQueda !== undefined && typeof corpo.confirmarQueda !== 'boolean') erros.push('confirmarQueda deve ser true/false');
  const ls = corpo.linhas;
  if (!Array.isArray(ls)) erros.push('linhas deve ser uma lista');
  else if (ls.length === 0) erros.push('nenhuma linha de lote — payload vazio não é aceito');
  else if (ls.length > LIMITES.linhas) erros.push(`mais de ${LIMITES.linhas} linhas`);
  if (erros.length) throw new ErroSync(400, 'payload_invalido', 'estrutura recebida inválida', erros);

  const linhas = ls.map((l, i) => {
    const onde = `linha ${i + 1} do envio`;
    if (!l || typeof l !== 'object' || Array.isArray(l)) { erros.push(`${onde}: não é um objeto`); return null; }
    const fora = Object.keys(l).filter(k => !CAMPOS_LINHA.includes(k));
    if (fora.length) erros.push(`${onde}: campos não aceitos: ${fora.join(', ')}`);
    const out = {};
    for (const c of ['aba', 'cultivar', 'cultura_planilha', 'data', 'safra', 'categoria', 'lote', 'peneira', 'embalagem', 'localizacao', 'observacoes']) {
      const v = l[c];
      if (v == null) { out[c] = null; continue; }
      if (typeof v !== 'string') { erros.push(`${onde}: ${c} deve ser texto`); continue; }
      if (v.length > LIMITES.texto) { erros.push(`${onde}: ${c} longo demais`); continue; }
      out[c] = v.replace(/\s+/g, ' ').trim() || null;
    }
    if (!out.lote) erros.push(`${onde}: lote obrigatório`);
    if (!out.cultivar) erros.push(`${onde}: cultivar obrigatório`);
    if (!out.aba) erros.push(`${onde}: aba obrigatória`);
    const inteiro = (v, nome, max, obrig) => {
      if (v == null) { if (obrig) erros.push(`${onde}: ${nome} obrigatório`); return null; }
      if (typeof v !== 'number' || !Number.isFinite(v) || v <= 0 || v > max) { erros.push(`${onde}: ${nome} fora do intervalo`); return null; }
      return v;
    };
    out.linha = Number.isInteger(l.linha) && l.linha > 0 && l.linha < 1e6 ? l.linha : (erros.push(`${onde}: linha inválida`), null);
    out.bags = inteiro(l.bags, 'bags', LIMITES.bags, true);
    if (out.bags != null && !Number.isInteger(out.bags)) erros.push(`${onde}: bags deve ser inteiro`);
    out.peso_bag = inteiro(l.peso_bag, 'peso_bag', LIMITES.peso, false);
    out.total_kg = inteiro(l.total_kg, 'total_kg', LIMITES.kg, false);
    return out;
  });
  if (erros.length) throw new ErroSync(400, 'payload_invalido', 'estrutura recebida inválida', erros.slice(0, 50));
  return { planilha: { nome: p.nome.trim(), modificadaEm: p.modificadaEm || null }, linhas, confirmarQueda: corpo.confirmarQueda === true };
}

// ------------------------------------------------------------ consolidação (= benef_inverno.consolidar)

function kgDaLinha(l) {
  const { bags, peso_bag: peso, total_kg: total } = l;
  if (total != null && peso != null && Math.abs(total - bags * peso) > TOLERANCIA_KG)
    return [null, `Total ${n(total)} kg diferente de N° BB × PESO (${n(bags)} × ${n(peso)} = ${n(bags * peso)} kg)`];
  if (total != null) return [total, null];
  if (peso != null) return [bags * peso, null];
  return [null, 'sem PESO e sem Total'];
}

const onde = l => `aba '${l.aba}' linha ${l.linha}`;

function consolidar(linhas, culturas) {
  const conflitos = [], avisos = [];
  const posAba = new Map();
  linhas.forEach(l => { if (!posAba.has(l.aba)) posAba.set(l.aba, posAba.size); });
  const ordem = linhas.map((l, i) => i).sort((a, b) =>
    (posAba.get(linhas[a].aba) - posAba.get(linhas[b].aba)) || ((linhas[a].linha || 0) - (linhas[b].linha || 0)) || (a - b));

  const grupos = new Map();
  for (const i of ordem) {
    const l = Object.assign({}, linhas[i]);
    const codigo = codigoLote(l.lote);
    if (!codigo) { conflitos.push({ tipo: 'lote_invalido', lote: l.lote, onde: [onde(l)], texto: 'código de lote vazio ou inválido' }); continue; }
    const cultura = culturaDoCultivar(l.cultivar, culturas) || l.cultura_planilha;
    if (!cultura) {
      conflitos.push({ tipo: 'sem_cultura', lote: codigo, onde: [onde(l)],
        texto: `cultivar ${l.cultivar} sem cultura no CV_META_INVERNO nem na planilha — não dá para montar a identidade do lote` });
      continue;
    }
    const [kg, problema] = kgDaLinha(l);
    if (problema) { conflitos.push({ tipo: 'quantidade_incompativel', lote: codigo, onde: [onde(l)], texto: problema }); continue; }
    Object.assign(l, { cultura, kg: n(kg), codigo, lotId: montarIdLote(cultura, codigo) });
    if (!grupos.has(l.lotId)) grupos.set(l.lotId, []);
    grupos.get(l.lotId).push(l);
  }

  const lotes = [];
  for (const [lotId, ls] of grupos) {
    const unicas = [], vistas = new Set();
    for (const l of ls) {
      const chave = JSON.stringify(CAMPOS_DA_LINHA.map(c => cmp(l[c])));
      if (vistas.has(chave)) { avisos.push(`lote ${l.codigo}: ${onde(l)} repete exatamente outra linha — contada uma vez`); continue; }
      vistas.add(chave); unicas.push(l);
    }
    let conflito = false;
    for (const campo of CAMPOS_DO_LOTE) {
      const vals = new Map();
      for (const l of unicas) {
        const k = JSON.stringify(cmp(l[campo]));
        if (!vals.has(k)) vals.set(k, [l[campo], []]);
        vals.get(k)[1].push(onde(l));
      }
      if (vals.size > 1) {
        conflito = true;
        conflitos.push({ tipo: `${campo}_divergente`, lote: unicas[0].codigo, lotId,
          onde: [...vals.values()].flatMap(v => v[1]),
          texto: `${campo} diferente entre linhas do mesmo lote: ` + [...vals.values()].map(v => String(v[0])).join(' × ') });
      }
    }
    if (conflito) continue;
    const b = unicas[0];
    if (unicas.length > 1) avisos.push(`lote ${b.codigo}: ${unicas.length} linhas do mesmo lote somadas (${unicas.map(onde).join(', ')})`);
    const juntar = campo => [...new Set(unicas.map(l => l[campo]).filter(Boolean))].join(' · ') || null;
    lotes.push({
      lotId, lote: b.codigo, cultivar: b.cultivar, cultura: b.cultura,
      data: juntar('data'), safra: juntar('safra'), categoria: b.categoria,
      peneira: b.peneira, embalagem: b.embalagem,
      bags: n(unicas.reduce((s, l) => s + l.bags, 0)), peso_bag: b.peso_bag,
      kg: n(unicas.reduce((s, l) => s + l.kg, 0)),
      localizacao: juntar('localizacao'), observacoes: juntar('observacoes'),
      linhas: unicas.map(l => ({ aba: l.aba, linha: l.linha }))
    });
  }
  if (conflitos.length) return { benef: [], conflitos, avisos };

  const porCv = new Map();
  for (const d of lotes) {
    const k = JSON.stringify([d.cultivar, d.cultura]);
    if (!porCv.has(k)) porCv.set(k, []);
    porCv.get(k).push(d);
  }
  const benef = [...porCv.values()].map(ds => ({
    cultivar: ds[0].cultivar,
    cultura: ds[0].cultura,
    bags_total: n(ds.reduce((s, d) => s + d.bags, 0)),
    kg_total: n(ds.reduce((s, d) => s + d.kg, 0)),
    lotes: ds.length,
    localizacoes: [...new Set(ds.map(d => d.localizacao).filter(Boolean))],
    abas: [...new Set(ds.flatMap(d => d.linhas.map(x => x.aba)))],
    detail: ds
  }));
  return { benef, conflitos: [], avisos };
}

function totais(benef) {
  return {
    cultivares: benef.length,
    lotes: benef.reduce((s, c) => s + c.lotes, 0),
    bags: n(benef.reduce((s, c) => s + c.bags_total, 0)),
    kg: n(benef.reduce((s, c) => s + c.kg_total, 0))
  };
}

// ------------------------------------------------------------ conjuntos (= seedmax_dados.py)

const js = d => JSON.stringify(d);                        // mesmo formato compacto do Python
const hash = t => crypto.createHash('sha256').update(t, 'utf8').digest('hex').slice(0, 16);

function lerConjunto(docs, meta, nome) {
  const info = meta && meta.datasets && meta.datasets[nome];
  if (!info) return null;
  let t = '';
  for (let i = 0; i < info.partes; i++) {
    const p = docs[`${nome}__${i}`];
    if (!p || p.hash !== info.hash) throw new ErroSync(503, 'banco_inconsistente', `conjunto ${nome} inconsistente no banco`);
    t += p.json;
  }
  return JSON.parse(t);
}

// mesma regra de seedmax_dados._mesclar_meta: troca SÓ a entrada do próprio conjunto
function mesclarMeta(atual, nome, entrada, carimbo) {
  const base = Object.assign({}, atual || {});
  delete base.atualizadoEmServidor;
  const indice = Object.assign({}, base.datasets || {});
  const anterior = indice[nome] || {};
  const apagar = [];
  for (let i = entrada.partes; i < (anterior.partes || 0); i++) apagar.push(`${nome}__${i}`);
  indice[nome] = entrada;
  return [{
    esquema: ESQUEMA, versao: (parseInt(base.versao, 10) || 0) + 1,
    atualizadoEm: carimbo, verificadoEm: carimbo, datasets: indice, mudaramNaUltima: [nome]
  }, apagar];
}

const carimboBRT = agora => {
  const d = new Date(agora.getTime() - 3 * 3600 * 1000);
  const p = x => String(x).padStart(2, '0');
  return `${p(d.getUTCDate())}/${p(d.getUTCMonth() + 1)}/${d.getUTCFullYear()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
};

// ------------------------------------------------------------ fluxo

/**
 * deps: {
 *   verificar(idToken) -> {uid},                 // verifyIdToken(token, true)
 *   lerCadastro(uid) -> users/{uid} | null,
 *   lerQualidade() -> {docId: dados},            // coleção qualidade inteira (leitura)
 *   publicar(partes, apagar, meta, registro),    // transação: relê _meta e só então grava (ver index.js)
 *   registrar(registro),                         // sincronizacoes/BENEF_INVERNO (+ histórico)
 *   agora() -> Date,
 *   log(evento)                                  // nunca recebe token nem a planilha inteira
 * }
 */
function criarSincronizador(deps) {
  async function autenticar(idToken) {
    if (!idToken) throw new ErroSync(401, 'sem_token', 'falta o cabeçalho Authorization: Bearer <token>');
    let uid;
    try { uid = (await deps.verificar(idToken)).uid; } catch (e) { throw new ErroSync(401, 'token_invalido', 'token inválido, vencido ou revogado'); }
    if (!uid) throw new ErroSync(401, 'token_invalido', 'token sem usuário');
    const c = await deps.lerCadastro(uid);
    if (!c || c.active !== true) throw new ErroSync(403, 'sem_permissao', 'conta inativa ou sem cadastro');
    if (c.role !== PERFIL) throw new ErroSync(403, 'sem_permissao', `esta função só aceita a conta de sincronização (${PERFIL})`);
    return uid;
  }

  return async function sincronizar({ idToken, corpo }) {
    const inicio = deps.agora();
    const uid = await autenticar(idToken);
    const acao = corpo && corpo.acao;

    const docs = await deps.lerQualidade();
    const meta = docs._meta || {};
    const cvMeta = lerConjunto(docs, meta, 'CV_META_INVERNO') || {};
    const culturas = {};
    for (const [cv, m] of Object.entries(cvMeta)) if (m && m.cultura) culturas[cv] = m.cultura;
    const atual = lerConjunto(docs, meta, CONJUNTO) || [];
    const lotesAntes = atual.reduce((s, c) => s + (c.lotes || 0), 0);

    if (acao === 'estado') {
      return { ok: true, acao, culturas, publicado: { lotes: lotesAntes, hash: (meta.datasets && meta.datasets[CONJUNTO] || {}).hash || null } };
    }
    if (acao !== 'publicar') throw new ErroSync(400, 'acao_invalida', 'acao deve ser "estado" ou "publicar"');

    const base = { uid, carimbo: carimboBRT(inicio), conjunto: CONJUNTO };
    let entrada;
    try { entrada = validarPayload(corpo); } catch (e) {
      if (e instanceof ErroSync) await deps.registrar(Object.assign({}, base, { resultado: 'RECUSADO', erro: e.erro, detalhes: (e.detalhes || []).slice(0, 20) }));
      throw e;
    }
    const reg = Object.assign(base, { planilha: entrada.planilha, linhasRecebidas: entrada.linhas.length });

    const { benef, conflitos, avisos } = consolidar(entrada.linhas, culturas);
    if (conflitos.length) {
      await deps.registrar(Object.assign(reg, { resultado: 'CONFLITO', conflitos: conflitos.slice(0, 50) }));
      throw new ErroSync(409, 'conflito', `${conflitos.length} conflito(s) na planilha — nada foi publicado`, conflitos);
    }
    const t = totais(benef);
    if (!entrada.confirmarQueda && lotesAntes >= 10 && t.lotes < lotesAntes * 0.5) {
      await deps.registrar(Object.assign(reg, { resultado: 'RECUSADO', erro: 'queda_suspeita', totais: t, lotesAntes }));
      throw new ErroSync(422, 'queda_suspeita', `lotes caíram de ${lotesAntes} para ${t.lotes} — envie confirmarQueda=true se for de propósito`);
    }

    const texto = js(benef);
    const h = hash(texto);
    const anterior = meta.datasets && meta.datasets[CONJUNTO];
    if (anterior && anterior.hash === h) {
      await deps.registrar(Object.assign(reg, { resultado: 'SEM_MUDANCA', totais: t, avisos: avisos.slice(0, 50) }));
      return { ok: true, mudou: false, totais: t, avisos, carimbo: reg.carimbo };
    }
    const pedacos = [];
    for (let i = 0; i < texto.length; i += TAMANHO_PARTE) pedacos.push(texto.slice(i, i + TAMANHO_PARTE));
    if (!pedacos.length) pedacos.push('');
    const partes = {};
    pedacos.forEach((p, i) => { partes[`${CONJUNTO}__${i}`] = { nome: CONJUNTO, parte: i, hash: h, json: p }; });
    const entradaIndice = { hash: h, partes: pedacos.length, bytes: Buffer.byteLength(texto, 'utf8'), itens: benef.length,
      sincronizadoEm: reg.carimbo };
    await deps.publicar(partes, entradaIndice, reg.carimbo);
    await deps.registrar(Object.assign(reg, { resultado: 'PUBLICADO', totais: t, hash: h, avisos: avisos.slice(0, 50) }));
    deps.log({ evento: 'publicado', uid, totais: t });
    return { ok: true, mudou: true, totais: t, avisos, carimbo: reg.carimbo };
  };
}

module.exports = {
  criarSincronizador, consolidar, validarPayload, mesclarMeta, montarIdLote, codigoLote, normalizarCultura,
  totais, hash, js, ErroSync, CONJUNTO, PERFIL, COLECAO
};
