// Firebase compat FALSO (Auth + Firestore em memória) para testar o TSI e o
// RASTREL no navegador sem tocar em nenhum banco real.
// Estado inicial: window.__MOCK = { user:{uid,email}, db:{colecao:{id:{...}}} }
// Registro de gravações: window.__WRITES = [{op, path, data}]
(function () {
  const M = window.__MOCK || { db: {} };
  const DB = M.db;
  window.__DB = DB;
  window.__WRITES = [];
  let seq = 1;
  const novoId = () => 'mock' + (seq++).toString(36) + Math.random().toString(36).slice(2, 6);
  const clone = v => v === undefined ? undefined : JSON.parse(JSON.stringify(v));
  function ts(ms) { const s = Math.floor(ms / 1000); return { seconds: s, nanoseconds: 0, toDate() { return new Date(ms); }, toMillis() { return ms; }, __ts: true }; }
  const SERVER_TS = { __serverTs: true };
  function resolver(v) {
    if (v && v.__serverTs) return ts(Date.now());
    if (Array.isArray(v)) return v.map(resolver);
    if (v && typeof v === 'object' && !v.__ts) { const o = {}; for (const k in v) o[k] = resolver(v[k]); return o; }
    return v;
  }
  function reviver(v) {   // depois do clone JSON, devolve os métodos dos timestamps
    if (Array.isArray(v)) return v.map(reviver);
    if (v && typeof v === 'object') {
      if (v.__ts) return ts(v.seconds * 1000);
      const o = {}; for (const k in v) o[k] = reviver(v[k]); return o;
    }
    return v;
  }
  const col = name => (DB[name] = DB[name] || {});
  const ouvintes = new Set();
  function notificar() { setTimeout(() => ouvintes.forEach(f => { try { f(); } catch (e) { console.error(e); } }), 0); }
  function getCampo(o, campo) { return campo.split('.').reduce((a, k) => a == null ? undefined : a[k], o); }
  function snapDoc(colName, id) {
    const d = col(colName)[id];
    return { id, exists: !!d, ref: docRef(colName, id), data: () => d ? reviver(clone(d)) : undefined, get: k => d ? reviver(clone(getCampo(d, k))) : undefined };
  }
  function docRef(colName, id) {
    id = id || novoId();
    return {
      id, path: colName + '/' + id,
      collection: sub => colRef(colName + '/' + id + '/' + sub),
      get: () => Promise.resolve(snapDoc(colName, id)),
      set(data, opt) {
        const atual = col(colName)[id];
        const novo = resolver(clone(data));
        col(colName)[id] = (opt && opt.merge && atual) ? Object.assign({}, atual, novo) : novo;
        window.__WRITES.push({ op: 'set', path: colName + '/' + id, data: clone(novo) });
        notificar(); return Promise.resolve();
      },
      update(data) {
        const atual = col(colName)[id];
        if (!atual) return Promise.reject(Object.assign(new Error('not-found'), { code: 'not-found' }));
        const novo = resolver(clone(data));
        col(colName)[id] = Object.assign({}, atual, novo);
        window.__WRITES.push({ op: 'update', path: colName + '/' + id, data: clone(novo) });
        notificar(); return Promise.resolve();
      },
      delete() { delete col(colName)[id]; window.__WRITES.push({ op: 'delete', path: colName + '/' + id }); notificar(); return Promise.resolve(); },
      onSnapshot(cb) { const f = () => cb(snapDoc(colName, id)); ouvintes.add(f); setTimeout(f, 5); return () => ouvintes.delete(f); },
    };
  }
  function colRef(name, filtros = [], ordem = null, lim = null) {
    function rodar() {
      let ids = Object.keys(col(name));
      for (const [c, op, v] of filtros) {
        ids = ids.filter(id => {
          const x = getCampo(col(name)[id], c);
          if (op === '==') return x === v;
          if (op === 'in') return v.includes(x);
          if (op === '!=') return x !== v;
          if (op === 'array-contains') return Array.isArray(x) && x.includes(v);
          if (op === '>=') return x >= v; if (op === '<=') return x <= v;
          if (op === '>') return x > v; if (op === '<') return x < v;
          return true;
        });
      }
      if (ordem) {
        const [c, dir] = ordem;
        const val = id => { const x = getCampo(col(name)[id], c); return x && x.seconds != null ? x.seconds : x; };
        ids.sort((a, b) => { const va = val(a), vb = val(b); const r = va == null ? 1 : vb == null ? -1 : (va > vb ? 1 : va < vb ? -1 : 0); return dir === 'desc' ? -r : r; });
      }
      if (lim != null) ids = ids.slice(0, lim);
      const docs = ids.map(id => snapDoc(name, id));
      return { docs, empty: !docs.length, size: docs.length, forEach: f => docs.forEach(f) };
    }
    return {
      path: name,
      doc: id => docRef(name, id),
      add(data) { const r = docRef(name); return r.set(data).then(() => r); },
      where: (c, op, v) => colRef(name, filtros.concat([[c, op, v]]), ordem, lim),
      orderBy: (c, dir) => colRef(name, filtros, [c, dir || 'asc'], lim),
      limit: n => colRef(name, filtros, ordem, n),
      select: () => colRef(name, filtros, ordem, lim),
      get: () => Promise.resolve(rodar()),
      onSnapshot(cb) { const f = () => cb(rodar()); ouvintes.add(f); setTimeout(f, 5); return () => ouvintes.delete(f); },
    };
  }
  const firestoreInst = {
    collection: n => colRef(n), doc: p => { const [c, id] = p.split('/'); return docRef(c, id); },
    batch() {
      const ops = [];
      return {
        set: (r, d, o) => ops.push(() => r.set(d, o)), update: (r, d) => ops.push(() => r.update(d)),
        delete: r => ops.push(() => r.delete()),
        commit: () => { ops.forEach(f => f()); return Promise.resolve(); },
      };
    },
    runTransaction: fn => fn({ get: r => r.get(), set: (r, d, o) => r.set(d, o), update: (r, d) => r.update(d), delete: r => r.delete() }),
    enablePersistence: () => Promise.resolve(), settings() {}, useEmulator() {},
    enableNetwork: () => Promise.resolve(), disableNetwork: () => Promise.resolve(),
  };
  let usuario = M.user || null;
  const ouvAuth = [];
  const authInst = {
    get currentUser() { return usuario; },
    onAuthStateChanged(cb) { ouvAuth.push(cb); setTimeout(() => cb(usuario), 10); return () => {}; },
    signInWithEmailAndPassword(email) { usuario = { uid: 'u1', email }; ouvAuth.forEach(f => f(usuario)); return Promise.resolve({ user: usuario }); },
    signOut() { usuario = null; ouvAuth.forEach(f => f(null)); return Promise.resolve(); },
    setPersistence: () => Promise.resolve(), useEmulator() {},
  };
  const app = { name: '[DEFAULT]', options: {}, firestore: () => firestoreInst, auth: () => authInst, storage: () => ({ ref: () => ({}) }) };
  const firestoreFn = () => firestoreInst;
  firestoreFn.FieldValue = { serverTimestamp: () => SERVER_TS, delete: () => undefined, increment: n => n, arrayUnion: (...a) => a };
  firestoreFn.Timestamp = { fromDate: d => ts(d.getTime()), now: () => ts(Date.now()), fromMillis: ms => ts(ms) };
  const authFn = () => authInst; authFn.Auth = { Persistence: { LOCAL: 'local', SESSION: 'session', NONE: 'none' } };
  window.firebase = {
    apps: [],
    initializeApp(cfg, name) { const a = Object.assign({}, app, { name: name || '[DEFAULT]', options: cfg }); this.apps.push(a); return a; },
    app: () => app, firestore: firestoreFn, auth: authFn, storage: () => ({ ref: () => ({}) }),
  };
})();
