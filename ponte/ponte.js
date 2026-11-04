'use strict';
// Núcleo da ponte, sem dependência de Firebase: recebe as funções reais
// (verificar token, ler cadastro, assinar, registrar) por injeção. Assim os
// testes provam o fluxo, e a Cloud Function só liga as peças.
const { decidir } = require('./decisao');

class ErroPonte extends Error {
  constructor(codigo, motivo) { super(motivo); this.codigo = codigo; this.motivo = motivo; }
}

function extrairBearer(cabecalho) {
  const m = /^Bearer\s+([A-Za-z0-9._-]+)$/.exec(String(cabecalho || '').trim());
  return m ? m[1] : null;
}

/**
 * deps: { verificar(idToken) -> {uid}, lerCadastro(uid) -> cadastro|null,
 *         assinar(modulo, uid, claims) -> customToken, registrar(evento) }
 * Nunca registra tokens: o evento leva só uid, módulo, decisão e motivo.
 */
function criarPonte(deps) {
  return async function ponte({ idToken, modulo }) {
    const inicio = Date.now();
    let uid = null;
    const fim = (permitido, motivo) => deps.registrar({ uid, modulo: String(modulo || ''), permitido, motivo, ms: Date.now() - inicio });
    if (!idToken) { fim(false, 'sem-token'); throw new ErroPonte('unauthenticated', 'sem-token'); }
    try {
      const v = await deps.verificar(idToken);
      uid = v && v.uid;
    } catch (e) {
      fim(false, 'token-invalido');
      throw new ErroPonte('unauthenticated', 'token-invalido');
    }
    if (!uid) { fim(false, 'token-sem-uid'); throw new ErroPonte('unauthenticated', 'token-sem-uid'); }
    const cadastro = await deps.lerCadastro(uid);
    const d = decidir(cadastro, modulo);
    if (!d.permitido) { fim(false, d.motivo); throw new ErroPonte('permission-denied', d.motivo); }
    const token = await deps.assinar(modulo, uid, { ponte: true, modulo, papelModulo: d.papel });
    fim(true, 'ok');
    return { token, modulo, papel: d.papel };
  };
}

module.exports = { criarPonte, extrairBearer, ErroPonte };
