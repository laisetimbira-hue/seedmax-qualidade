#!/usr/bin/env python3
"""
SEEDMAX — sincronizador do Beneficiamento de Inverno (roda no Windows da empresa).

  Excel no servidor da empresa
    → lê "LOTES BENEFICIADOS INVERNO 26-26.xlsx"
    → transforma no formato BENEF_INVERNO
    → compara com o que já está no Firestore
    → grava SOMENTE se mudou (e somente o conjunto BENEF_INVERNO)
    → o SEEDMAX mostra o aviso "Dados atualizados" para quem estiver com ele aberto

Não usa Google Drive. Não altera LOTS_INVERNO, análises, lotes comprados,
nosso plantio, dados de verão, TSI nem RASTREL: o único conjunto entregue
para gravação é BENEF_INVERNO (ver CONJUNTO abaixo e a trava em _gravar).

Uso (prompt do Windows):

  python sincronizar_benef_inverno.py --simular
      lê a planilha e mostra o que mudaria, sem gravar nada

  python sincronizar_benef_inverno.py
      grava se houver mudança (é o comando que o Agendador de Tarefas roda)

Configuração (variáveis de ambiente ou parâmetros):

  BENEF_INVERNO_PLANILHA   caminho do .xlsx, de preferência UNC
                           (ex.: \\\\SERVIDOR\\Qualidade\\LOTES BENEFICIADOS INVERNO 26-26.xlsx)
  SEEDMAX_CREDENCIAL       caminho do arquivo .json da conta de serviço
                           (fica só neste computador, nunca no repositório)

Para testar sem o Firebase: --pasta-teste C:\\algum\\lugar grava/lê JSON local.

Códigos de saída: 0 ok (gravou ou nada mudou) · 1 erro · 2 recusou gravar
(planilha parece incompleta — ver log).
"""

import argparse
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta

AQUI = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import benef_inverno  # noqa: E402

CONJUNTO = "BENEF_INVERNO"          # o ÚNICO conjunto que este script grava
BRT = timezone(timedelta(hours=-3))
PASTA_LOG = pathlib.Path(os.environ.get("BENEF_INVERNO_LOGS", AQUI.parent / "logs"))


# ---------------------------------------------------------------- log

def _agora():
    return datetime.now(BRT)


_ARQ_LOG = None


def log(msg=""):
    linha = f"[{_agora():%d/%m/%Y %H:%M:%S}] {msg}"
    print(linha, flush=True)
    if _ARQ_LOG:
        with open(_ARQ_LOG, "a", encoding="utf-8") as f:
            f.write(linha + "\n")


def _preparar_log():
    global _ARQ_LOG
    try:
        PASTA_LOG.mkdir(parents=True, exist_ok=True)
        _ARQ_LOG = PASTA_LOG / f"benef_inverno_{_agora():%Y-%m}.log"
        # guarda só os últimos 6 meses de log
        for antigo in sorted(PASTA_LOG.glob("benef_inverno_*.log"))[:-6]:
            antigo.unlink(missing_ok=True)
    except OSError:
        _ARQ_LOG = None


# ---------------------------------------------------------------- trava

class Trava:
    """Impede duas execuções ao mesmo tempo (ex.: Agendador + manual)."""

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
    """Lê uma CÓPIA local: assim o arquivo do servidor nunca fica preso
    pelo script, e a equipe pode continuar com ele aberto no Excel."""
    origem = pathlib.Path(origem)
    if not origem.exists():
        raise SystemExit(f"planilha não encontrada: {origem} "
                         "(servidor fora do ar, caminho errado ou sem permissão de leitura?)")
    destino = pathlib.Path(tempfile.gettempdir()) / "seedmax_benef_inverno_copia.xlsx"
    for tentativa in range(1, 6):
        try:
            shutil.copy2(origem, destino)
            return destino, datetime.fromtimestamp(origem.stat().st_mtime, BRT)
        except PermissionError:
            log(f"  planilha ocupada no servidor (tentativa {tentativa}/5) — aguardando 20 s")
            time.sleep(20)
    raise SystemExit("não consegui copiar a planilha (arquivo bloqueado) — tento de novo na próxima execução")


# ---------------------------------------------------------------- comparação

def resumo_diferencas(antes, depois):
    def por_lote(benef):
        return {(d["lote"]): (c["cultivar"], d) for c in benef or [] for d in c["detail"]}
    a, d = por_lote(antes), por_lote(depois)
    novos = sorted(set(d) - set(a))
    saiu = sorted(set(a) - set(d))
    alterados = sorted(k for k in set(a) & set(d)
                       if {x: v for x, v in a[k][1].items() if x != "linha"} !=
                          {x: v for x, v in d[k][1].items() if x != "linha"})
    return novos, saiu, alterados


# ---------------------------------------------------------------- principal

def main(argv=None):
    ap = argparse.ArgumentParser(description="Sincroniza a planilha de Beneficiados do Inverno com o SEEDMAX")
    ap.add_argument("--planilha", default=os.environ.get("BENEF_INVERNO_PLANILHA"))
    ap.add_argument("--credencial", default=os.environ.get("SEEDMAX_CREDENCIAL"))
    ap.add_argument("--simular", action="store_true", help="só mostra o que mudaria, não grava")
    ap.add_argument("--pasta-teste", help="usa uma pasta local no lugar do Firestore (teste)")
    ap.add_argument("--forcar", action="store_true",
                    help="grava mesmo se a planilha parecer incompleta (ex.: zerou de propósito)")
    a = ap.parse_args(argv)
    _preparar_log()

    if not a.planilha:
        raise SystemExit("informe a planilha: --planilha \"\\\\SERVIDOR\\...\\LOTES BENEFICIADOS INVERNO 26-26.xlsx\" "
                         "ou a variável BENEF_INVERNO_PLANILHA")

    # destino: Firestore (credencial em arquivo local) ou pasta de teste
    if a.pasta_teste:
        os.environ["SEEDMAX_DESTINO"] = "pasta:" + a.pasta_teste
    else:
        os.environ["SEEDMAX_DESTINO"] = "firestore"
        if not os.environ.get("FIREBASE_SERVICE_ACCOUNT"):
            if not a.credencial or not pathlib.Path(a.credencial).exists():
                raise SystemExit("credencial não encontrada: informe --credencial C:\\...\\seedmax-benef-inverno.json "
                                 "ou a variável SEEDMAX_CREDENCIAL")
            os.environ["FIREBASE_SERVICE_ACCOUNT"] = pathlib.Path(a.credencial).read_text(encoding="utf-8")

    import seedmax_dados as store  # depois de configurar o destino

    with Trava():
        log(f"Sincronização Beneficiamento Inverno {'(SIMULAÇÃO) ' if a.simular else ''}— {a.planilha}")
        copia, modificada = copiar_planilha(a.planilha)
        log(f"  planilha salva no servidor em {modificada:%d/%m/%Y %H:%M}")

        destino = store.conectar()
        meta, publicado = store.ler_conjuntos(destino)       # leitura
        cv_meta = publicado.get("CV_META_INVERNO") or {}
        atual = publicado.get(CONJUNTO) or []

        try:
            benef, avisos = benef_inverno.ler(copia, cv_meta)
        finally:
            copia.unlink(missing_ok=True)
        for av in avisos:
            log(f"  aviso: {av}")
        t = benef_inverno.totais(benef)
        log(f"  lido: {t['cultivares']} cultivar(es) · {t['lotes']} lotes · {t['bags']:,} bags · "
            f"{t['kg']:,} kg".replace(",", "."))
        for c in benef:
            log(f"    {c['cultivar']:<14} {c['cultura'] or '(sem cultura)':<14} {c['lotes']:>3} lotes "
                f"{c['bags_total']:>5} bags {c['kg_total']:>9,} kg".replace(",", "."))
        sem_cultura = [c["cultivar"] for c in benef if not c["cultura"]]
        if sem_cultura:
            log(f"  aviso: sem cultura no CV_META_INVERNO nem na planilha: {', '.join(sem_cultura)}")

        # travas de segurança: não apaga o que está publicado por engano
        lotes_antes = sum(c.get("lotes", 0) for c in atual)
        if not a.forcar:
            if t["lotes"] == 0 and lotes_antes > 0:
                log(f"  RECUSADO: a planilha ficou sem nenhum lote (publicado hoje: {lotes_antes}). "
                    "Pode ser arquivo errado ou em edição. Nada foi gravado. (--forcar para gravar assim)")
                return 2
            if lotes_antes >= 10 and t["lotes"] < lotes_antes * 0.5:
                log(f"  RECUSADO: o número de lotes caiu de {lotes_antes} para {t['lotes']} (mais da metade). "
                    "Nada foi gravado. Confira a planilha (ou rode com --forcar).")
                return 2

        novos, saiu, alterados = resumo_diferencas(atual, benef)
        if novos:
            log(f"  lotes novos: {', '.join(novos)}")
        if saiu:
            log(f"  lotes que saíram da planilha: {', '.join(saiu)}")
        if alterados:
            log(f"  lotes alterados: {', '.join(alterados)}")

        if a.simular:
            igual = store._js(atual) == store._js(benef)
            log("  SIMULAÇÃO: " + ("nada mudou — não gravaria nada" if igual else
                                   f"gravaria {CONJUNTO} (só este conjunto)"))
            return 0

        mudaram = _gravar(store, destino, benef, meta)
        if not mudaram:
            log("  nada mudou — nada foi gravado")
            return 0

        # confere o que ficou gravado
        _, relido = store.ler_conjuntos(destino)
        if store._js(relido.get(CONJUNTO)) != store._js(benef):
            log("  ERRO: o que foi relido do banco não bate com o que foi gravado")
            return 1
        log(f"  gravado e conferido: {CONJUNTO}")
        return 0


def _gravar(store, destino, benef, meta):
    novos = {CONJUNTO: benef}
    assert list(novos) == [CONJUNTO], "este script só pode gravar BENEF_INVERNO"
    carimbo = _agora().strftime("%d/%m/%Y %H:%M")
    return store.publicar(destino, novos, carimbo, meta_atual=meta, renovar_verificacao=False)


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
