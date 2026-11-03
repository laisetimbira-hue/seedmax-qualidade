// Firebase compat FALSO, só para teste local (substitui os scripts do
// gstatic via interceptação do Playwright). Simula Auth + Firestore e
// aplica no "servidor" a mesma lógica de firestore.rules para leituras.
(function () {
  const E = window.__MOCK_ESTADO; // {contas:{email:{senha,uid,disabled}}, users:{uid:{...}}, qualidade:{docId:{...}}}
  window.__MOCK_LEITURAS = [];
  const KEY = 'mockAuthUid';
  let atual = null;
  try { const u = localStorage.getItem(KEY); if (u) atual = { uid: u, email: Object.keys(E.contas).find(e => E.contas[e].uid === u) }; } catch (e) {}
  const ouvintesAuth = [];
  const ouvintesMeta = [];
  const notificar = () => ouvintesAuth.forEach(cb => setTimeout(() => cb(atual), 0));
  const erro = (code) => Object.assign(new Error(code), { code });
  const PERFIS_Q = ['ADMIN', 'QUALIDADE', 'VISUALIZACAO'];

  function pode(col, id) {
    if (!atual) return false;
    const cad = E.users[atual.uid];
    if (col === 'users') return id === atual.uid || (cad && cad.active === true && cad.role === 'ADMIN');
    if (col === 'qualidade') return !!(cad && cad.active === true && PERFIS_Q.includes(cad.role));
    return false;
  }
  const atraso = (v) => new Promise(r => setTimeout(() => r(v), 20));
  const snapDoc = (col, id) => { const d = (E[col] || {})[id]; return { id, exists: !!d, data: () => d && JSON.parse(JSON.stringify(d)) }; };

  const auth = {
    useEmulator() {}, setPersistence() { return Promise.resolve(); },
    signInWithEmailAndPassword(email, senha) {
      const c = E.contas[email];
      if (!c || c.senha !== senha) return Promise.reject(erro('auth/invalid-credential'));
      if (c.disabled) return Promise.reject(erro('auth/user-disabled'));
      atual = { uid: c.uid, email }; localStorage.setItem(KEY, c.uid); notificar();
      return atraso({ user: atual });
    },
    signOut() { atual = null; localStorage.removeItem(KEY); notificar(); return atraso(); },
    onAuthStateChanged(cb) { ouvintesAuth.push(cb); setTimeout(() => cb(atual), 30); return () => {}; },
  };
  const fs = {
    useEmulator() {},
    collection(col) {
      return {
        get() {
          window.__MOCK_LEITURAS.push({ col, uid: atual && atual.uid, ok: pode(col, null) });
          if (col === 'users' || !pode(col, null)) return Promise.reject(erro('permission-denied'));
          return atraso({ docs: Object.keys(E[col] || {}).map(id => snapDoc(col, id)) });
        },
        doc(id) {
          return {
            get() {
              window.__MOCK_LEITURAS.push({ col, id, uid: atual && atual.uid, ok: pode(col, id) });
              if (!pode(col, id)) return Promise.reject(erro('permission-denied'));
              return atraso(snapDoc(col, id));
            },
            onSnapshot(cb, errCb) {
              if (!pode(col, id)) { errCb && errCb(erro('permission-denied')); return () => {}; }
              const f = () => cb(snapDoc(col, id));
              ouvintesMeta.push(f); setTimeout(f, 10);
              return () => { const i = ouvintesMeta.indexOf(f); if (i >= 0) ouvintesMeta.splice(i, 1); };
            },
          };
        },
      };
    },
  };
  window.__mockNovaVersao = () => { E.qualidade._meta.versao += 1; ouvintesMeta.forEach(f => f()); };
  const authFn = () => auth;
  authFn.Auth = { Persistence: { LOCAL: 'local' } };
  window.firebase = { initializeApp() { return {}; }, auth: authFn, firestore: () => fs };
})();
