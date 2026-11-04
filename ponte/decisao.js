'use strict';
// SEEDMAX — ponte de login: QUEM recebe login em QUAL módulo.
// Função pura (sem rede): a mesma regra roda na Cloud Function e na prova técnica.
// A proteção final continua sendo a regra do Firestore de cada módulo
// (users/{uid} ativo no próprio módulo).

const MODULOS = Object.freeze(['tsi', 'rastrel']);
const PAPEIS_MODULO = Object.freeze(['ADMIN', 'OPERADOR', 'VISUALIZADOR']);

// Perfil central -> módulos operacionais que ele PODE pedir.
// VISUALIZACAO e QUALIDADE: nenhum por padrão (política aprovada em 04/11/2026);
// liberar um módulo operacional exige mudar esta tabela explicitamente.
const PERFIL_MODULOS = Object.freeze({
  ADMIN: ['tsi', 'rastrel'],
  TSI: ['tsi'],
  RASTREL: ['rastrel'],
  QUALIDADE: [],
  VISUALIZACAO: []
});

/**
 * @param {object|null} cadastro  users/{uid} do projeto seedmax ({active, role, modulos?})
 * @param {string} modulo         'tsi' | 'rastrel'
 * @returns {{permitido: boolean, motivo: string, papel?: string}}
 */
function decidir(cadastro, modulo) {
  if (!MODULOS.includes(modulo)) return { permitido: false, motivo: 'modulo-invalido' };
  if (!cadastro) return { permitido: false, motivo: 'sem-cadastro' };
  if (cadastro.active !== true) return { permitido: false, motivo: 'inativo' };
  const permitidos = PERFIL_MODULOS[cadastro.role];
  if (!permitidos) return { permitido: false, motivo: 'perfil-desconhecido' };
  if (!permitidos.includes(modulo)) return { permitido: false, motivo: 'perfil-sem-modulo' };
  const doCadastro = (cadastro.modulos && typeof cadastro.modulos === 'object') ? cadastro.modulos[modulo] : undefined;
  // ADMIN central sem nível explícito: o nível real é o do users/{uid} no módulo (normalmente ADMIN)
  const papel = doCadastro || (cadastro.role === 'ADMIN' ? 'ADMIN' : undefined);
  if (!PAPEIS_MODULO.includes(papel)) return { permitido: false, motivo: 'modulo-nao-liberado' };
  return { permitido: true, motivo: 'ok', papel };
}

module.exports = { decidir, MODULOS, PAPEIS_MODULO, PERFIL_MODULOS };
