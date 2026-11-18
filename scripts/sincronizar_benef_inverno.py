#!/usr/bin/env python3
"""
SEEDMAX — sincronizador do Beneficiamento de Inverno (roda no Windows da empresa).

  Excel no servidor da empresa
    → lê "LOTES BENEFICIADOS INVERNO 26-26.xlsx" (uma cópia local)
    → interpreta e consolida por lote (Safra + Cultura + Lote)
    → valida: lote repetido/conflitante PARA a sincronização (nada é enviado)
    → compara com o que está publicado (só o hash)
    → se mudou, envia as linhas para a função segura sincronizarBenefInverno,
      que valida de novo e grava SOMENTE o BENEF_INVERNO.

Este computador NÃO tem credencial administrativa do Firebase. Ele entra com a
conta técnica de perfil SINC_BENEF_INVERNO (e-mail + senha guardada no
Gerenciador de Credenciais do Windows); recebe um token que vale 1 hora e que
só serve para chamar essa função — essa conta não lê nenhum dado do SEEDMAX.

Uso (prompt do Windows):
  python sincronizar_benef_inverno.py --simular   # lê, valida e compara; não envia
  python sincronizar_benef_inverno.py             # envia se mudou (Agendador de Tarefas)
  python sincronizar_benef_inverno.py --guardar-senha   # grava a senha no Windows (uma vez)

Configuração (variáveis de ambiente — ver windows/config_benef_inverno.exemplo.bat):
  BENEF_INVERNO_PLANILHA   caminho UNC do .xlsx (\\\\SERVIDOR\\...)
  SEEDMAX_SYNC_EMAIL       e-mail da conta técnica SINC_BENEF_INVERNO
  SEEDMAX_SYNC_URL         (opcional) endereço da função
  BENEF_INVERNO_LOGS       (opcional) pasta dos logs

Saída: 0 ok (enviou ou nada mudou) · 1 erro · 2 recusado pela função ·
3 conflito na planilha (nada enviado).
"""

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

AQUI = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import benef_inverno  # noqa: E402

CONJUNTO = "BENEF_INVERNO"
URL_PADRAO = "https://southamerica-east1-seedmax-4c755.cloudfunctions.net/sincronizarBenefInverno"
# chave PÚBLICA do app web do SEEDMAX (a mesma do index.html; não é segredo)
API_KEY = "AIzaSyAVW7rA87T3S_AdrP83gCGIFl6jgcWehCE"
URL_LOGIN = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key="
SERVICO_SENHA = "SEEDMAX-sincronizador-benef-inverno"
BRT = timezone(timedelta(hours=-3))

_ARQ_LOG = None


def _agora():
    return datetime.now(BRT)


def log(msg=""):
    linha = f"[{_agora():%d/%m/%Y %H:%M:%S}] {msg}"
    print(linha, flush=True)
    if _ARQ_LOG:
        try:
            with open(_ARQ_LOG, "a", encoding="utf-8") as f:
                f.write(linha + "\n")
        except OSError:
            pass


def _preparar_log():
    global _ARQ_LOG
    pasta = pathlib.Path(os.environ.get("BENEF_INVERNO_LOGS", AQUI.parent / "logs"))
    try:
        pasta.mkdir(parents=True, exist_ok=True)
        _ARQ_LOG = pasta / f"benef_inverno_{_agora():%Y-%m}.log"
        for antigo in sorted(pasta.glob("benef_inverno_*.log"))[:-6]:
            antigo.unlink(missing_ok=True)
    except OSError:
        _ARQ_LOG = None


class Trava:
    """Impede duas execuções ao mesmo tempo (Agendador + manual)."""

    def __init__(self):
        self.caminho = pathlib.Path(tempfile.gettempdir()) / "seedmax_benef_inverno.lock"

    def __enter__(self):
        if self.caminho.exists() and time.time() - self.caminho.stat().st_mtime < 15 * 60:
            raise SystemExit("outra sincronização já está rodando (trava com menos de 15 min) — saindo")
        self.caminho.write_text(str(os.getpid()))
        return self

    def __exit__(self, *a):
        self.caminho.unlink(missing_ok=True)


# ---------------------------------------------------------------- planilha

def copiar_planilha(origem):
    """Lê uma CÓPIA: o arquivo do servidor nunca fica preso pelo script."""
    origem = pathlib.Path(origem)
    if not origem.exists():
        raise SystemExit(f"planilha não encontrada: {origem} (servidor fora do ar, caminho errado ou sem permissão?)")
    destino = pathlib.Path(tempfile.gettempdir()) / "seedmax_benef_inverno_copia.xlsx"
    for tentativa in range(1, 6):
        try:
            shutil.copy2(origem, destino)
            return destino, datetime.fromtimestamp(origem.stat().st_mtime, BRT)
        except PermissionError:
            log(f"  planilha ocupada no servidor (tentativa {tentativa}/5) — aguardando 20 s")
            time.sleep(20)
    raise SystemExit("não consegui copiar a planilha (arquivo bloqueado) — tento de novo na próxima execução")


def hash_conjunto(benef):
    """Mesmo hash que a função grava no índice (JSON compacto, sha256, 16 caracteres)."""
    texto = json.dumps(benef, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- rede

def _post(url, corpo, token=None, timeout=60):
    dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=dados, method="POST",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            return e.code, {"ok": False, "erro": "http", "mensagem": f"HTTP {e.code}"}
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SystemExit(f"sem conexão com o SEEDMAX ({e}) — tento de novo na próxima execução")


def senha_da_conta(email):
    s = os.environ.get("SEEDMAX_SYNC_SENHA")
    if s:
        return s
    try:
        import keyring
        s = keyring.get_password(SERVICO_SENHA, email)
    except Exception:  # noqa: BLE001
        s = None
    if not s:
        raise SystemExit("senha da conta técnica não encontrada — rode uma vez: "
                         "sincronizar_benef_inverno.bat --guardar-senha")
    return s


def entrar(email, senha, url_login=None):
    """ID token (1 h) da conta técnica SINC_BENEF_INVERNO."""
    st, r = _post((url_login or URL_LOGIN) + API_KEY, {"email": email, "password": senha, "returnSecureToken": True})
    if st != 200 or not r.get("idToken"):
        motivo = (r.get("error") or {}).get("message") or r.get("mensagem") or f"HTTP {st}"
        raise SystemExit(f"login da conta técnica recusado ({motivo}) — confira e-mail/senha ou se a conta está ativa")
    return r["idToken"]


# ---------------------------------------------------------------- principal

def main(argv=None):
    ap = argparse.ArgumentParser(description="Sincroniza a planilha de Beneficiados do Inverno com o SEEDMAX")
    ap.add_argument("--planilha", default=os.environ.get("BENEF_INVERNO_PLANILHA"))
    ap.add_argument("--email", default=os.environ.get("SEEDMAX_SYNC_EMAIL"))
    ap.add_argument("--url", default=os.environ.get("SEEDMAX_SYNC_URL", URL_PADRAO))
    ap.add_argument("--url-login", default=os.environ.get("SEEDMAX_SYNC_URL_LOGIN"))  # testes/emulador
    ap.add_argument("--simular", action="store_true", help="lê, valida e compara; não envia")
    ap.add_argument("--confirmar-queda", action="store_true",
                    help="envia mesmo se o número de lotes cair mais da metade (de propósito)")
    ap.add_argument("--guardar-senha", action="store_true",
                    help="guarda a senha da conta técnica no Gerenciador de Credenciais do Windows")
    a = ap.parse_args(argv)
    _preparar_log()

    if not a.email:
        raise SystemExit("informe a conta técnica: --email ou variável SEEDMAX_SYNC_EMAIL")
    if a.guardar_senha:
        import getpass
        import keyring
        keyring.set_password(SERVICO_SENHA, a.email, getpass.getpass(f"Senha de {a.email}: "))
        log("senha guardada no Gerenciador de Credenciais do Windows")
        return 0
    if not a.planilha:
        raise SystemExit("informe a planilha: --planilha ou variável BENEF_INVERNO_PLANILHA")

    with Trava():
        log(f"Sincronização Beneficiamento Inverno {'(SIMULAÇÃO) ' if a.simular else ''}— {a.planilha}")
        copia, modificada = copiar_planilha(a.planilha)
        log(f"  planilha salva no servidor em {modificada:%d/%m/%Y %H:%M}")
        try:
            linhas, avisos_leitura = benef_inverno.ler_planilha(copia)
        finally:
            copia.unlink(missing_ok=True)
        for av in avisos_leitura:
            log(f"  aviso: {av}")
        if not linhas:
            log("  RECUSADO: nenhuma linha de lote na planilha — nada enviado")
            return 2

        token = entrar(a.email, senha_da_conta(a.email), a.url_login)
        st, estado = _post(a.url, {"acao": "estado"}, token)
        if st != 200 or not estado.get("ok"):
            log(f"  ERRO ao consultar o SEEDMAX: {estado.get('mensagem') or st}")
            return 2 if 400 <= st < 500 else 1

        benef, conflitos, avisos = benef_inverno.consolidar(linhas, estado.get("culturas") or {})
        for av in avisos:
            log(f"  aviso: {av}")
        if conflitos:
            log(f"  CONFLITO: {len(conflitos)} problema(s) na planilha — NADA foi enviado. Corrija e salve a planilha:")
            for c in conflitos:
                log(f"    [{c['tipo']}] lote {c.get('lote')}: {c['texto']} ({'; '.join(c.get('onde') or [])})")
            return 3

        t = benef_inverno.totais(benef)
        log(f"  lido: {t['cultivares']} cultivar(es) · {t['lotes']} lotes · {t['bags']:,} bags · {t['kg']:,} kg"
            .replace(",", "."))
        for c in benef:
            log(f"    {c['cultivar']:<14} {c['cultura']:<14} {c['lotes']:>3} lotes {c['bags_total']:>5} bags "
                f"{c['kg_total']:>9,} kg".replace(",", "."))

        publicado = (estado.get("publicado") or {})
        if hash_conjunto(benef) == publicado.get("hash"):
            log("  nada mudou desde a última publicação — nada enviado")
            return 0
        log(f"  mudou (publicado hoje: {publicado.get('lotes', 0)} lotes)")
        if a.simular:
            log("  SIMULAÇÃO: enviaria para o SEEDMAX (só BENEF_INVERNO)")
            return 0

        corpo = {"acao": "publicar", "formato": benef_inverno.FORMATO, "conjunto": CONJUNTO,
                 "planilha": {"nome": pathlib.Path(a.planilha).name, "modificadaEm": modificada.strftime("%d/%m/%Y %H:%M")},
                 "linhas": linhas}
        if a.confirmar_queda:
            corpo["confirmarQueda"] = True
        st, r = _post(a.url, corpo, token, timeout=120)
        if st == 200 and r.get("ok"):
            rt = r.get("totais") or {}
            log(f"  {'PUBLICADO' if r.get('mudou') else 'sem mudança'} em {r.get('carimbo')}: "
                f"{rt.get('lotes')} lotes · {rt.get('bags')} bags · {rt.get('kg')} kg")
            return 0
        log(f"  RECUSADO pela função ({st} {r.get('erro')}): {r.get('mensagem')}")
        for d in (r.get("detalhes") or [])[:30]:
            log(f"    - {d.get('texto') if isinstance(d, dict) else d}")
        return 3 if r.get("erro") == "conflito" else (2 if 400 <= st < 500 else 1)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as e:
        if isinstance(e.code, str):
            log(f"ERRO: {e.code}")
            sys.exit(1)
        raise
    except Exception as e:  # noqa: BLE001
        log(f"FALHOU: {type(e).__name__}: {e}")
        sys.exit(1)
