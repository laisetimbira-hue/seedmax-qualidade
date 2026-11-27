#!/usr/bin/env bash
# Backup verificado do SEEDMAX antes da publicação do PR #33 — roda NO CLOUD SHELL.
#
#   bash executar.sh backup    -> cópia JSON de todo o Firestore + verificação + totais (pasta privada)
#   bash executar.sh guardar   -> envia a cópia para o bucket privado e confere baixando de volta
#   bash executar.sh exportar  -> exportação OFICIAL do Firestore para o bucket privado e confere
#   bash executar.sh funcao    -> registra a versão publicada de sincronizarBenefInverno e guarda o código
#   bash executar.sh totais    -> totais e lotes atuais, logo antes do merge
#   bash executar.sh resumo    -> mostra o que já foi feito
#   bash executar.sh depois    -> (após a publicação) totais atuais comparados com os de antes
#
# Nada aqui grava, altera ou apaga dados do Firestore nem mexe na função.
# Só cria: a pasta ~/seedmax-backups (privada), o bucket privado de backup (se não existir)
# e objetos novos dentro dele. Nada é enviado ao GitHub.
set -euo pipefail
umask 077
PROJ=seedmax-4c755
FUNCAO=sincronizarBenefInverno
BUCKET=gs://${PROJ}-backups
AQUI="$(cd "$(dirname "$0")" && pwd)"
JS="$AQUI/seedmax-backup.cjs"
BASE="$HOME/seedmax-backups"
export GOOGLE_CLOUD_PROJECT=$PROJ GOOGLE_CLOUD_QUOTA_PROJECT=$PROJ
ok()   { echo "✔ $*"; }
erro() { echo "✘ $*" >&2; exit 1; }
atual() { [ -s "$BASE/ATUAL" ] || erro "rode primeiro: bash executar.sh backup"; cat "$BASE/ATUAL"; }

[ "$(gcloud config get-value project 2>/dev/null)" = "$PROJ" ] || gcloud config set project $PROJ >/dev/null

case "${1:-}" in
backup)
  D="$BASE/pr33-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$D/firestore"; chmod 700 "$BASE" "$D"
  node "$JS" backup "$D/firestore" | tee "$D/backup.log" | tail -3
  node "$JS" verificar "$D/firestore" | tee "$D/verificacao.log"
  grep -qx BACKUP_OK "$D/verificacao.log" || erro "verificação falhou"
  node "$JS" totais "$D/firestore" "$D/totais-antes.json" | tee "$D/totais-antes.txt"
  node "$JS" totais firestore "$D/totais-vivo.json" >/dev/null
  if node "$JS" comparar "$D/totais-vivo.json" "$D/totais-antes.json" >"$D/vivo-x-copia.txt"; then
    ok "cópia idêntica ao banco no ar"
  else
    echo "⚠ o banco mudou durante a cópia (robô rodou?):"; cat "$D/vivo-x-copia.txt"; erro "repita: bash executar.sh backup"
  fi
  tar -czf "$D/firestore.tgz" -C "$D" firestore
  (cd "$D" && sha256sum firestore.tgz firestore/MANIFESTO.json > SHA256SUMS)
  echo "$D" > "$BASE/ATUAL"
  ok "backup local verificado em $D ($(du -sh "$D/firestore" | cut -f1))"
  ;;
guardar)
  D=$(atual); N=$(basename "$D")
  LOC=$(gcloud firestore databases describe --database='(default)' --format='value(locationId)')
  if ! gcloud storage buckets describe $BUCKET >/dev/null 2>&1; then
    gcloud storage buckets create $BUCKET --location="$LOC" --uniform-bucket-level-access \
      --public-access-prevention --soft-delete-duration=30d
    ok "bucket privado criado: $BUCKET ($LOC)"
  fi
  gcloud storage buckets describe $BUCKET --format='value(public_access_prevention,uniform_bucket_level_access)' | tee "$D/bucket.txt"
  grep -q enforced "$D/bucket.txt" || erro "bucket sem bloqueio de acesso público"
  gcloud storage cp "$D/firestore.tgz" "$D/SHA256SUMS" "$D/totais-antes.json" "$BUCKET/json/$N/"
  T=$(mktemp -d); gcloud storage cp "$BUCKET/json/$N/firestore.tgz" "$T/" >/dev/null
  [ "$(sha256sum <"$T/firestore.tgz")" = "$(sha256sum <"$D/firestore.tgz")" ] || erro "cópia no bucket diferente da local"
  tar -xzf "$T/firestore.tgz" -C "$T" && node "$JS" verificar "$T/firestore" | tail -1 | grep -qx BACKUP_OK || erro "cópia baixada do bucket não passou na verificação"
  rm -rf "$T"
  echo "$BUCKET/json/$N/" > "$D/guardado.txt"
  ok "cópia no bucket conferida (baixada de volta e verificada): $BUCKET/json/$N/"
  ;;
exportar)
  # Exportação oficial: inicia em modo assíncrono e acompanha a operação até o estado final.
  # Limite de espera: EXPORT_LIMITE_MIN (padrão 60). Ao estourar, NÃO cancela: a operação segue no
  # Google e "bash executar.sh exportar" retoma o acompanhamento da mesma operação.
  # Se a operação anterior falhou: NOVA=1 bash executar.sh exportar (inicia outra, em pasta nova).
  D=$(atual); N=$(basename "$D")
  gcloud storage buckets describe $BUCKET >/dev/null 2>&1 || erro "rode antes: bash executar.sh guardar"
  [ -s "$D/guardado.txt" ] || erro "rode antes: bash executar.sh guardar"
  LIMITE=${EXPORT_LIMITE_MIN:-60}
  if [ -s "$D/exportado.txt" ] && [ -z "${NOVA:-}" ]; then ok "exportação já concluída: $(cat "$D/exportado.txt")"; exit 0; fi
  if [ -s "$D/export-op.txt" ] && [ -z "${NOVA:-}" ]; then
    OP=$(cat "$D/export-op.txt"); DEST=$(cat "$D/export-destino.txt"); echo "retomando a operação já iniciada: $OP"
  else
    DEST="$BUCKET/export/$N-$(date +%H%M%S)"
    gcloud firestore export "$DEST" --database='(default)' --async --format=json > "$D/export-inicio.json"
    OP=$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print((d[0] if isinstance(d,list) else d)["name"])' "$D/export-inicio.json")
    [ -n "$OP" ] || erro "não consegui o nome da operação de exportação"
    echo "$OP" > "$D/export-op.txt"; echo "$DEST" > "$D/export-destino.txt"; rm -f "$D/exportado.txt"
    ok "exportação iniciada: $OP"
  fi
  FIM=$(( $(date +%s) + LIMITE * 60 )); FALHAS=0
  while :; do
    if ! gcloud firestore operations describe "$OP" --format=json > "$D/export-final.json" 2>"$D/export-erro.log"; then
      FALHAS=$((FALHAS + 1)); [ $FALHAS -ge 6 ] && erro "não consigo consultar a operação ($(tail -1 "$D/export-erro.log")); retome com: bash executar.sh exportar"
      sleep "${EXPORT_INTERVALO_S:-20}"; continue
    fi
    FALHAS=0
    ESTADO=$(python3 - "$D/export-final.json" <<'P'
import json, sys
o = json.load(open(sys.argv[1])); m = o.get("metadata", {}); e = m.get("operationState", "?")
if o.get("error"): e = "FAILED"
done = "1" if o.get("done") else "0"
docs = (m.get("progressDocuments") or {}).get("completedWork", "0")
print(e, done, docs, (o.get("error") or {}).get("message", "").replace(" ", "_")[:200])
P
)
    read -r E DONE DOCS MSG <<<"$ESTADO"
    case "$E" in
      SUCCESSFUL) [ "$DONE" = 1 ] && break ;;
      FAILED|CANCELLED|CANCELLING) erro "exportação terminou em $E ${MSG//_/ } — nada foi alterado; para tentar de novo: NOVA=1 bash executar.sh exportar" ;;
    esac
    [ "$(date +%s)" -ge $FIM ] && { echo "⏱ limite de $LIMITE min atingido (estado $E, $DOCS docs). A operação NÃO foi cancelada."; echo "  retome com: bash executar.sh exportar"; exit 4; }
    echo "  … $E, $DOCS documentos exportados"; sleep "${EXPORT_INTERVALO_S:-20}"
  done
  PREFIXO=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["metadata"].get("outputUriPrefix",""))' "$D/export-final.json")
  [ "$PREFIXO" = "$DEST" ] || erro "destino da exportação inesperado: $PREFIXO"
  gcloud storage ls -r "$DEST" > "$D/export-arquivos.txt"
  grep -q 'overall_export_metadata$' "$D/export-arquivos.txt" || erro "exportação sem arquivo de metadados"
  grep -q 'output-' "$D/export-arquivos.txt" || erro "exportação sem arquivos de dados"
  echo "$DEST" > "$D/exportado.txt"
  ok "exportação oficial concluída ($DOCS documentos): $DEST"
  echo "  restaurar (SÓ em emergência e com aprovação): gcloud firestore import $DEST"
  ;;
funcao)
  # Registra a versão publicada de sincronizarBenefInverno e guarda o necessário para voltar a ela.
  D=$(atual); F="$D/funcao"; mkdir -p "$F"
  NOME=$(gcloud functions list --filter="name~/functions/$FUNCAO\$" --format='value(name)' | head -1)
  [ -n "$NOME" ] || erro "função $FUNCAO não encontrada"
  REG=$(echo "$NOME" | cut -d/ -f4)
  gcloud functions describe $FUNCAO --region="$REG" --format=json > "$F/funcao.json"
  python3 - "$F/funcao.json" > "$F/campos.env" <<'P'
import json, sys, shlex
f = json.load(open(sys.argv[1])); s = f.get("serviceConfig", {}); b = f.get("buildConfig", {}); src = (b.get("source") or {}).get("storageSource") or {}
if f.get("environment") != "GEN_2": sys.exit("função não é de 2ª geração: " + str(f.get("environment")))
v = {"ESTADO": f.get("state"), "ATUALIZADA": f.get("updateTime"), "REVISAO": s.get("revision"),
     "SERVICO": (s.get("service") or "").split("/")[-1], "RUNTIME": b.get("runtime"), "ENTRADA": b.get("entryPoint"),
     "CONTA": s.get("serviceAccountEmail"), "FONTE": "gs://%s/%s#%s" % (src.get("bucket"), src.get("object"), src.get("generation"))}
for k, x in v.items(): print(f"{k}={shlex.quote(str(x))}")
P
  # shellcheck disable=SC1091
  . "$F/campos.env"
  [ "$ESTADO" = ACTIVE ] || erro "função não está ACTIVE ($ESTADO)"
  gcloud run services describe "$SERVICO" --region="$REG" --format=json > "$F/servico-run.json"
  gcloud run revisions describe "$REVISAO" --region="$REG" --format=json > "$F/revisao-run.json"
  IMAGEM=$(python3 -c 'import json,sys;r=json.load(open(sys.argv[1]));c=r["spec"]["containers"][0]["image"];d=r.get("status",{}).get("imageDigest","");print(d or c)' "$F/revisao-run.json")
  if gcloud artifacts docker images describe "$IMAGEM" >/dev/null 2>&1; then IMG_OK=sim; else IMG_OK=nao; fi
  gcloud storage cp "$FONTE" "$F/fonte-publicada.zip" >/dev/null
  unzip -tq "$F/fonte-publicada.zip" >/dev/null || erro "zip do código publicado corrompido"
  unzip -l "$F/fonte-publicada.zip" | grep -q 'package.json' || erro "zip do código publicado sem package.json"
  if [ -d "$HOME/seedmax-ponte" ]; then
    tar -czf "$F/seedmax-ponte-antes.tgz" --exclude=node_modules --exclude=.git -C "$HOME" seedmax-ponte
    tar -tzf "$F/seedmax-ponte-antes.tgz" | grep -q 'seedmax-ponte/firebase.json' || erro "cópia da pasta da ponte sem firebase.json"
  else
    erro "pasta ~/seedmax-ponte não encontrada (é dela que a função é publicada)"
  fi
  cat > "$F/ROLLBACK.txt" <<R
Função: $NOME
Versão publicada antes do PR #33: revisão $REVISAO (atualizada em $ATUALIZADA)
Imagem: $IMAGEM  (ainda existe no Artifact Registry: $IMG_OK)
Código publicado: $FONTE  -> cópia em fonte-publicada.zip

Voltar RÁPIDO (só se a imagem ainda existir):
  gcloud run services update-traffic $SERVICO --region=$REG --to-revisions=$REVISAO=100

Voltar DEFINITIVO (recompila a versão anterior a partir da cópia da pasta da ponte):
  T=\$(mktemp -d) && tar -xzf $F/seedmax-ponte-antes.tgz -C \$T && cd \$T/seedmax-ponte/functions && npm ci --omit=dev && cd .. \\
    && firebase deploy --only functions:ponte:$FUNCAO --project $PROJ
R
  (cd "$F" && sha256sum ./* > SHA256SUMS)
  if gcloud storage buckets describe $BUCKET >/dev/null 2>&1; then
    gcloud storage cp -r "$F" "$BUCKET/json/$(basename "$D")/" >/dev/null
    gcloud storage ls "$BUCKET/json/$(basename "$D")/funcao/" | grep -q ROLLBACK.txt || erro "cópia da função não chegou ao bucket"
    ok "registro e código da função também no bucket"
  fi
  head -3 "$F/ROLLBACK.txt" | tee "$D/funcao-antes.txt"
  ok "função registrada; imagem disponível para volta rápida: $IMG_OK; volta definitiva garantida pela cópia da pasta"
  ;;
totais)
  # Totais atuais imediatamente antes do merge (referência para a conferência depois)
  D=$(atual)
  node "$JS" totais firestore "$D/totais-pre-merge.json" | tee "$D/totais-pre-merge.txt"
  ok "totais antes do merge registrados"
  ;;
resumo)
  D=$(atual); echo "pasta: $D"
  for f in verificacao.log guardado.txt exportado.txt funcao-antes.txt totais-pre-merge.txt; do [ -s "$D/$f" ] && echo "— $f: $(tail -1 "$D/$f")" || echo "— $f: (pendente)"; done
  ;;
depois)
  D=$(atual); A="$D/totais-depois-$(date +%H%M%S).json"
  node "$JS" totais firestore "$A" | tee "${A%.json}.txt"
  REF="$D/totais-pre-merge.json"; [ -s "$REF" ] || REF="$D/totais-antes.json"
  echo "comparando com: $(basename "$REF")"
  node "$JS" comparar "$REF" "$A" || true
  ;;
*) sed -n '2,13p' "$0"; exit 64 ;;
esac
