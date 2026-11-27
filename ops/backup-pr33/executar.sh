#!/usr/bin/env bash
# Backup verificado do SEEDMAX antes da publicação do PR #33 — roda NO CLOUD SHELL.
#
#   bash executar.sh backup    -> cópia JSON de todo o Firestore + verificação + totais (pasta privada)
#   bash executar.sh guardar   -> envia a cópia para o bucket privado e confere baixando de volta
#   bash executar.sh exportar  -> exportação OFICIAL do Firestore para o bucket privado e confere
#   bash executar.sh funcao    -> registra a versão publicada de sincronizarBenefInverno e guarda o código
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
  D=$(atual); N=$(basename "$D")
  gcloud storage buckets describe $BUCKET >/dev/null 2>&1 || erro "rode antes: bash executar.sh guardar"
  DEST="$BUCKET/export/$N"
  gcloud firestore export "$DEST" --database='(default)' --format=json > "$D/export-op.json"
  OP=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["name"])' "$D/export-op.json")
  gcloud firestore operations describe "$OP" --format=json > "$D/export-final.json"
  python3 - "$D/export-final.json" <<'P'
import json, sys
o = json.load(open(sys.argv[1])); m = o.get("metadata", {})
estado = m.get("operationState"); print("estado:", estado, "| docs:", m.get("progressDocuments", {}).get("completedWork"), "| fim:", m.get("endTime"))
sys.exit(0 if o.get("done") and estado == "SUCCESSFUL" and "error" not in o else 1)
P
  gcloud storage ls "$DEST/**" | grep -q 'overall_export_metadata' || erro "exportação sem arquivo de metadados"
  echo "$DEST" > "$D/exportado.txt"
  ok "exportação oficial concluída: $DEST"
  echo "  restaurar (só em emergência): gcloud firestore import $DEST"
  ;;
funcao)
  D=$(atual)
  NOME=$(gcloud functions list --filter="name~/functions/$FUNCAO\$" --format='value(name)' | head -1)
  [ -n "$NOME" ] || erro "função $FUNCAO não encontrada"
  REG=$(echo "$NOME" | cut -d/ -f4)
  gcloud functions describe $FUNCAO --region="$REG" --format=json > "$D/funcao-antes.json"
  python3 - "$D/funcao-antes.json" <<'P' | tee "$D/funcao-antes.txt"
import json, sys
f = json.load(open(sys.argv[1])); s = f.get("serviceConfig", {}); b = f.get("buildConfig", {}); src = b.get("source", {}).get("storageSource", {})
print("função:", f["name"]); print("estado:", f.get("state"), "| atualizada em:", f.get("updateTime"))
print("revisão no ar:", s.get("revision")); print("runtime:", b.get("runtime"), "| entrada:", b.get("entryPoint"))
print("código-fonte: gs://%s/%s#%s" % (src.get("bucket"), src.get("object"), src.get("generation")))
P
  SRC=$(python3 -c 'import json,sys;s=json.load(open(sys.argv[1]))["buildConfig"]["source"]["storageSource"];print("gs://%s/%s#%s"%(s["bucket"],s["object"],s["generation"]))' "$D/funcao-antes.json")
  gcloud storage cp "$SRC" "$D/funcao-fonte-antes.zip" && ok "código publicado da função copiado"
  [ -d "$HOME/seedmax-ponte/functions" ] && tar -czf "$D/seedmax-ponte-functions-antes.tgz" --exclude=node_modules -C "$HOME/seedmax-ponte" functions && ok "pasta ~/seedmax-ponte/functions copiada"
  if gcloud storage buckets describe $BUCKET >/dev/null 2>&1; then
    gcloud storage cp "$D"/funcao-* "$BUCKET/json/$(basename "$D")/" >/dev/null && ok "registro da função também no bucket"
  fi
  ;;
resumo)
  D=$(atual); echo "pasta: $D"
  for f in verificacao.log guardado.txt exportado.txt funcao-antes.txt; do [ -s "$D/$f" ] && echo "— $f: $(tail -1 "$D/$f")" || echo "— $f: (pendente)"; done
  ;;
depois)
  D=$(atual); A="$D/totais-depois-$(date +%H%M%S).json"
  node "$JS" totais firestore "$A" | tee "${A%.json}.txt"
  node "$JS" comparar "$D/totais-antes.json" "$A" || true
  ;;
*) sed -n '2,12p' "$0"; exit 64 ;;
esac
