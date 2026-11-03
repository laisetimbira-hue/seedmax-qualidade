"""
SEEDMAX — leitura e gravação dos conjuntos de dados protegidos.

Os dados da Gestão de Qualidade ficam na coleção "qualidade" do Firestore:

  qualidade/_meta          versão, data da atualização e índice dos conjuntos
  qualidade/LOTS__0        {"nome","parte","hash","json"}  (pedaço 0 do LOTS)
  qualidade/SUMMARY__0     ...

Cada conjunto (LOTS, SUMMARY, BENEF...) tem o MESMO nome da constante que
antes ficava escrita no index.html — o código do dashboard continua igual.
Conjuntos maiores que ~900 KB são divididos em várias partes (limite do
Firestore é 1 MiB por documento). Tudo é gravado num único lote atômico,
então o navegador nunca vê uma mistura de versão antiga com nova.

Credencial: variável de ambiente FIREBASE_SERVICE_ACCOUNT com o JSON da
conta de serviço (no GitHub: Settings → Secrets → Actions). NUNCA coloque
esse JSON no repositório nem no HTML.

Para testes sem Firebase: SEEDMAX_DESTINO=pasta:/caminho grava/lê arquivos
JSON locais com a mesma estrutura.
"""

import hashlib
import json
import os
import pathlib
import re

COLECAO = "qualidade"
TAMANHO_PARTE = 900_000  # caracteres por documento (folga abaixo de 1 MiB)
ESQUEMA = 1

# Identificador da safra usado para montar o lotId estável
SAFRA_VERAO = "SOJA2526"
SAFRA_INVERNO = "INV2626"


# Os dados da safra têm alguns valores NaN (ex.: média sem amostra). No
# HTML antigo eles eram escritos como JavaScript (NaN), mas JSON não aceita
# NaN — então viajam como texto-marcador e o navegador os converte de volta.
_MARCADORES = {"__NaN__": float("nan"), "__Infinity__": float("inf"), "__-Infinity__": float("-inf")}


def _sem_nan(v):
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
        return "__NaN__" if v != v else ("__Infinity__" if v > 0 else "__-Infinity__")
    if isinstance(v, dict):
        return {k: _sem_nan(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_sem_nan(x) for x in v]
    return v


def _com_nan(v):
    if isinstance(v, str) and v in _MARCADORES:
        return _MARCADORES[v]
    if isinstance(v, dict):
        return {k: _com_nan(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_com_nan(x) for x in v]
    return v


def _js(dados):
    return json.dumps(_sem_nan(dados), ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _ler_json(texto):
    return _com_nan(json.loads(texto))


def _hash(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


def montar_lot_id(safra, lote):
    """lotId estável: safra + código do lote, só letras/números/_/-.
    Ex.: SOJA2526_26S01F. Nunca usa posição no array."""
    lote = re.sub(r"[^A-Za-z0-9_-]+", "-", str(lote or "").strip().upper()).strip("-")
    return f"{safra}_{lote}" if lote else None


def aplicar_lot_ids(lista, safra):
    for item in lista or []:
        if isinstance(item, dict) and item.get("lote") and not item.get("lotId"):
            item["lotId"] = montar_lot_id(safra, item["lote"])
    return lista


# ------------------------------------------------------------- destinos

class _DestinoFirestore:
    def __init__(self):
        import firebase_admin
        from firebase_admin import credentials, firestore

        bruto = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "").strip()
        if not bruto:
            raise SystemExit("ERRO: secret FIREBASE_SERVICE_ACCOUNT não configurado.")
        try:
            info = json.loads(bruto)
        except json.JSONDecodeError:
            raise SystemExit("ERRO: FIREBASE_SERVICE_ACCOUNT não é um JSON válido.")
        if not firebase_admin._apps:
            firebase_admin.initialize_app(credentials.Certificate(info))
        self._fs = firestore
        self.db = firestore.client()

    def ler_todos(self):
        return {d.id: d.to_dict() for d in self.db.collection(COLECAO).stream()}

    def gravar(self, gravar, apagar):
        batch = self.db.batch()
        col = self.db.collection(COLECAO)
        for doc_id, conteudo in gravar.items():
            if doc_id == "_meta":
                conteudo = dict(conteudo, atualizadoEmServidor=self._fs.SERVER_TIMESTAMP)
            batch.set(col.document(doc_id), conteudo)
        for doc_id in apagar:
            batch.delete(col.document(doc_id))
        batch.commit()


class _DestinoPasta:
    def __init__(self, pasta):
        self.pasta = pathlib.Path(pasta)
        self.pasta.mkdir(parents=True, exist_ok=True)

    def ler_todos(self):
        return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in self.pasta.glob("*.json")}

    def gravar(self, gravar, apagar):
        for doc_id, conteudo in gravar.items():
            (self.pasta / f"{doc_id}.json").write_text(_js(conteudo), encoding="utf-8")
        for doc_id in apagar:
            (self.pasta / f"{doc_id}.json").unlink(missing_ok=True)


def conectar():
    destino = os.environ.get("SEEDMAX_DESTINO", "firestore").strip()
    if destino.startswith("pasta:"):
        return _DestinoPasta(destino[len("pasta:"):])
    return _DestinoFirestore()


# ------------------------------------------------------------- API

def ler_conjuntos(destino):
    """Devolve (meta, {nome: dados}) com o que está publicado agora."""
    docs = destino.ler_todos()
    meta = docs.get("_meta") or {}
    dados = {}
    for nome, info in (meta.get("datasets") or {}).items():
        partes = [docs.get(f"{nome}__{i}") for i in range(info["partes"])]
        if any(p is None or p.get("hash") != info["hash"] for p in partes):
            raise SystemExit(f"ERRO: conjunto {nome} está inconsistente no banco.")
        dados[nome] = _ler_json("".join(p["json"] for p in partes))
    return meta, dados


def publicar(destino, novos, carimbo, meta_atual=None, docs_atuais=None):
    """Grava os conjuntos que mudaram (comparando o hash) e atualiza o _meta.
    `novos` = {nome: dados}. Conjuntos não informados ficam como estão.
    Devolve a lista de nomes que realmente mudaram."""
    if meta_atual is None:
        meta_atual, _ = ler_conjuntos(destino)
    indice = dict(meta_atual.get("datasets") or {})
    gravar, apagar, mudaram = {}, [], []

    for nome, dados in novos.items():
        texto = _js(dados)
        h = _hash(texto)
        anterior = indice.get(nome)
        if anterior and anterior.get("hash") == h:
            continue
        pedacos = [texto[i:i + TAMANHO_PARTE] for i in range(0, len(texto), TAMANHO_PARTE)] or [""]
        for i, pedaco in enumerate(pedacos):
            gravar[f"{nome}__{i}"] = {"nome": nome, "parte": i, "hash": h, "json": pedaco}
        if anterior:
            for i in range(len(pedacos), anterior.get("partes", 0)):
                apagar.append(f"{nome}__{i}")
        indice[nome] = {
            "hash": h,
            "partes": len(pedacos),
            "bytes": len(texto.encode("utf-8")),
            "itens": len(dados) if isinstance(dados, (list, dict)) else None,
        }
        mudaram.append(nome)

    if not mudaram and meta_atual.get("atualizadoEm"):
        # nada mudou nos dados: só renova a data da última verificação
        gravar["_meta"] = dict(meta_atual, verificadoEm=carimbo)
        gravar["_meta"].pop("atualizadoEmServidor", None)
        destino.gravar(gravar, [])
        return []

    gravar["_meta"] = {
        "esquema": ESQUEMA,
        "versao": int(meta_atual.get("versao") or 0) + 1,
        "atualizadoEm": carimbo,
        "verificadoEm": carimbo,
        "datasets": indice,
        "mudaramNaUltima": mudaram,
    }
    destino.gravar(gravar, apagar)
    return mudaram
