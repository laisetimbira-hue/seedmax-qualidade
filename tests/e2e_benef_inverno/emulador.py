"""Ponta a ponta com os EMULADORES oficiais do Firebase (Auth + Firestore + Functions).

Projeto de demonstração "demo-seedmax": nada sai da máquina, nada toca a produção.
Roda dentro de:  firebase emulators:exec --only auth,firestore,functions --project demo-seedmax \
                   "python3 tests/e2e_benef_inverno/emulador.py [planilha_real.xlsx]"

Exercita o caminho inteiro: planilha → sincronizar_benef_inverno.py (login da
conta técnica, consulta, consolidação, envio) → Cloud Function real
(sincronizarBenefInverno, firebase-functions v2) → Firestore (transação) →
leitura pelo mesmo código do robô/dashboard (seedmax_dados.ler_conjuntos), e o
robô (seedmax_dados.publicar) gravando AO MESMO TEMPO que a função.
"""
import json
import os
import pathlib
import sys
import tempfile
import threading
import urllib.request

AQUI = pathlib.Path(__file__).resolve().parent
RAIZ = AQUI.parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ / "tests"))

PROJETO = "demo-seedmax"
AUTH = os.environ.get("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")
FS = os.environ.get("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
FUNC = os.environ.get("FUNCOES_EMULADOR", "127.0.0.1:5001")
URL_FUNCAO = f"http://{FUNC}/{PROJETO}/southamerica-east1/sincronizarBenefInverno"
URL_LOGIN = f"http://{AUTH}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key="

RESULTADOS = []


def ok(nome, cond, extra=""):
    RESULTADOS.append((nome, bool(cond)))
    print(("  OK   " if cond else "  FALHOU ") + nome + (f" — {extra}" if extra else ""), flush=True)


def credencial_falsa():
    """O emulador não confere a credencial; o firebase-admin só exige o formato."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption()).decode()
    return json.dumps({"type": "service_account", "project_id": PROJETO, "private_key_id": "x",
                       "private_key": pem, "client_email": f"teste@{PROJETO}.iam.gserviceaccount.com",
                       "client_id": "1", "token_uri": "https://oauth2.googleapis.com/token"})


def post(url, corpo, token=None):
    req = urllib.request.Request(url, data=json.dumps(corpo).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def criar_conta(email, senha):
    st, r = post(f"http://{AUTH}/identitytoolkit.googleapis.com/v1/accounts:signUp?key=x",
                 {"email": email, "password": senha, "returnSecureToken": True})
    assert st == 200, r
    return r["localId"]


def main():
    os.environ["FIREBASE_SERVICE_ACCOUNT"] = credencial_falsa()
    os.environ["SEEDMAX_DESTINO"] = "firestore"
    os.environ["GOOGLE_CLOUD_PROJECT"] = PROJETO
    import seedmax_dados as store
    import sincronizar_benef_inverno as sync
    import benef_inverno as bi
    from test_benef_inverno import planilha

    d = store.conectar()
    db = d.db
    # ---- banco inicial: conjuntos da Qualidade + usuários
    store.publicar(d, {
        "LOTS": [{"lote": "26S1", "cultivar": "X"}], "LOTS_INVERNO": [{"lote": "99XX01", "cultura": "Trigo"}],
        "CV_META_INVERNO": {"CVTESTE1": {"cultura": "Trigo", "obtentor": None},
                            "CVTESTE2": {"cultura": "Aveia Branca", "obtentor": None},
                            **json.loads(os.environ.get("CULTURAS_EXTRAS", "{}"))},
        "BENEF_INVERNO": [], "TZ_DATA": {"a": 1},
    }, "inicial", meta_atual={})
    uid_sync = criar_conta("sinc@teste.local", "senha-sinc-123")
    uid_adm = criar_conta("admin@teste.local", "senha-adm-123")
    db.document(f"users/{uid_sync}").set({"name": "Sync", "email": "sinc@teste.local", "role": "SINC_BENEF_INVERNO", "active": True})
    db.document(f"users/{uid_adm}").set({"name": "Adm", "email": "admin@teste.local", "role": "ADMIN", "active": True})

    def estado_banco():
        meta, dados = store.ler_conjuntos(d)
        return meta, dados, {k: v["hash"] for k, v in meta["datasets"].items()}

    def rodar(plan, *extra, email="sinc@teste.local", senha="senha-sinc-123"):
        os.environ["SEEDMAX_SYNC_SENHA"] = senha
        try:
            return sync.main(["--planilha", str(plan), "--email", email, "--url", URL_FUNCAO,
                              "--url-login", URL_LOGIN, *extra])
        except SystemExit as e:
            return 1 if isinstance(e.code, str) else e.code

    tmp = pathlib.Path(tempfile.mkdtemp())
    os.environ["BENEF_INVERNO_LOGS"] = str(tmp / "logs")
    plan = planilha(tmp / "p.xlsx")
    meta0, dados0, h0 = estado_banco()

    print("\n== 1. simulação, depois primeira sincronização")
    ok("simulação não grava", rodar(plan, "--simular") == 0 and estado_banco()[2] == h0)
    ok("sincronização termina com sucesso", rodar(plan) == 0)
    meta1, dados1, h1 = estado_banco()
    ok("só BENEF_INVERNO mudou no índice", sorted(k for k in h1 if h1[k] != h0.get(k)) == ["BENEF_INVERNO"],
       str(sorted(k for k in h1 if h1[k] != h0.get(k))))
    ok("demais conjuntos intactos", all(dados1[k] == dados0[k] for k in dados0 if k != "BENEF_INVERNO"))
    ok("totais publicados", bi.totais(dados1["BENEF_INVERNO"]) == {"cultivares": 2, "lotes": 5, "bags": 102, "kg": 61200},
       json.dumps(bi.totais(dados1["BENEF_INVERNO"])))
    ok("cultura veio do CV_META_INVERNO", dados1["BENEF_INVERNO"][0]["cultura"] == "Trigo")
    ok("lotId = INV2626_CULTURA_LOTE", dados1["BENEF_INVERNO"][0]["detail"][0]["lotId"] == "INV2626_TRIGO_99XX01")
    reg = db.document("sincronizacoes/BENEF_INVERNO").get().to_dict() or {}
    ok("sincronização registrada (data/hora, conta, resultado)",
       reg.get("resultado") == "PUBLICADO" and reg.get("uid") == uid_sync and reg.get("em") and reg.get("carimbo"),
       f"{reg.get('resultado')} {reg.get('carimbo')}")
    ok("data da sincronização no índice", bool(meta1["datasets"]["BENEF_INVERNO"].get("sincronizadoEm")))

    print("\n== 2. sem mudança / linha repetida (conflito)")
    v = meta1["versao"]
    ok("segunda execução não envia nada", rodar(plan) == 0 and estado_banco()[0]["versao"] == v)
    ok("linha 100% idêntica repetida: conflito, para antes de enviar (código 3) e nada muda",
       rodar(planilha(tmp / "rep.xlsx", repetir=True)) == 3 and estado_banco()[0]["versao"] == v)

    print("\n== 3. conflito / contas erradas / envios inválidos direto na função")
    ok("conflito na planilha: para antes de enviar (código 3)",
       rodar(planilha(tmp / "conf.xlsx", conflito=True)) == 3 and estado_banco()[0]["versao"] == v)
    ok("senha errada: recusado", rodar(plan, senha="errada") == 1)
    ok("conta ADMIN não usa esta porta (403)", rodar(plan, email="admin@teste.local", senha="senha-adm-123") == 2)
    token = sync.entrar("sinc@teste.local", "senha-sinc-123", URL_LOGIN)
    base = {"acao": "publicar", "formato": 1, "planilha": {"nome": "x.xlsx"}}
    lin = lambda lote, **e: dict({"aba": "A", "linha": 3, "cultivar": "CVTESTE1", "cultura_planilha": None, "data": None,
                                  "safra": "26/26", "categoria": "S2", "lote": lote, "peneira": "S/P", "embalagem": "BB600",
                                  "bags": 20, "peso_bag": 600, "total_kg": 12000, "localizacao": "U", "observacoes": None}, **e)
    st, r = post(URL_FUNCAO, dict(base, linhas=[]), token)
    ok("payload vazio → 400", st == 400 and r.get("erro") == "payload_invalido", f"{st} {r.get('erro')}")
    st, r = post(URL_FUNCAO, dict(base, linhas=[lin("99XX01"), lin("99XX01", linha=4, categoria="C2")]), token)
    ok("mesmo lote com dados conflitantes → 409", st == 409 and r.get("erro") == "conflito", f"{st} {r.get('erro')}")
    st, r = post(URL_FUNCAO, dict(base, linhas=[lin("99XX01"), lin("99XX01", linha=4)]), token)
    ok("linha idêntica repetida enviada direto → 409 linha_duplicada",
       st == 409 and (r.get("detalhes") or [{}])[0].get("tipo") == "linha_duplicada", f"{st}")
    st, r = post(URL_FUNCAO, dict(base, conjunto="LOTS_INVERNO", linhas=[lin("99XX01")]), token)
    ok("outro conjunto → 400", st == 400, f"{st} {r.get('erro')}")
    st, r = post(URL_FUNCAO, dict(base, linhas=[lin("99XX01", germinacao=99)]), token)
    ok("campo estranho → 400", st == 400, f"{st} {r.get('erro')}")
    st, r = post(URL_FUNCAO, dict(base, linhas=[lin("99XX01")]), None)
    ok("sem token → 401", st == 401, str(st))
    ok("nada disso mudou o banco", estado_banco()[0]["versao"] == v)

    print("\n== 4. robô do GitHub e função gravando AO MESMO TEMPO")
    erros = []

    def robo():
        try:
            for i in range(8):
                meta_velho, _ = store.ler_conjuntos(store.conectar())
                store.publicar(store.conectar(), {"LOTS": [{"lote": f"26S{i}", "cultivar": "X"}]}, f"robo {i}",
                               meta_atual=meta_velho)
        except Exception as e:  # noqa: BLE001
            erros.append(e)

    def funcao():
        for i in range(4):
            p = planilha(tmp / f"c{i}.xlsx")
            wb = __import__("openpyxl").load_workbook(p)
            wb["INVERNO 2026"]["H3"] = 20 - i
            wb["INVERNO 2026"]["J3"] = (20 - i) * 600
            wb.save(p)
            if rodar(p) != 0:
                erros.append(f"sync {i}")

    t1, t2 = threading.Thread(target=robo), threading.Thread(target=funcao)
    t1.start(); t2.start(); t1.join(); t2.join()
    try:
        meta4, dados4, _ = estado_banco()
        consistente = True
    except SystemExit as e:
        consistente, meta4, dados4 = False, {}, {}
        erros.append(str(e))
    ok("índice consistente depois da concorrência (nenhum 'inconsistente')", consistente and not erros, str(erros[:3]))
    if consistente:
        ok("LOTS ficou com a última gravação do robô", dados4["LOTS"] == [{"lote": "26S7", "cultivar": "X"}])
        ok("BENEF_INVERNO ficou com a última gravação da função", dados4["BENEF_INVERNO"][0]["detail"][0]["bags"] == 17)

    real = sys.argv[1] if len(sys.argv) > 1 else None
    if real and pathlib.Path(real).exists():
        print("\n== 5. planilha REAL da empresa")
        ok("planilha real sincroniza", rodar(real) == 0)
        _, dados5, _ = estado_banco()
        t = bi.totais(dados5["BENEF_INVERNO"])
        ok("totais da planilha real (15 lotes · 294 bags · 176.400 kg)",
           t == {"cultivares": 2, "lotes": 15, "bags": 294, "kg": 176400}, json.dumps(t))
        print(json.dumps([{"cultivar": c["cultivar"], "cultura": c["cultura"], "lotes": c["lotes"], "bags": c["bags_total"],
                           "kg": c["kg_total"], "lotIds": [x["lotId"] for x in c["detail"]][:3] + ["..."]}
                          for c in dados5["BENEF_INVERNO"]], ensure_ascii=False, indent=1))

    falhas = [n for n, c in RESULTADOS if not c]
    print(f"\nRESULTADO: {len(RESULTADOS) - len(falhas)}/{len(RESULTADOS)} verificações OK")
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
