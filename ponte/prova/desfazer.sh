#!/usr/bin/env bash
# Desfaz a prova. Padrão: só remove a permissão TEMPORÁRIA (você agir como ponte-login).
# Com --tudo: remove também as contas de serviço e as permissões da ponte.
set -euo pipefail
SEED=seedmax-4c755; TSI=estoquetsi; RAS=rastreabilidade-a511a
EU=$(gcloud config get-value account 2>/dev/null)
PL=ponte-login@$SEED.iam.gserviceaccount.com
AT=ponte-assina-tsi@$TSI.iam.gserviceaccount.com
AR=ponte-assina-rastrel@$RAS.iam.gserviceaccount.com
gcloud iam service-accounts remove-iam-policy-binding $PL --project=$SEED --member="user:$EU" --role=roles/iam.serviceAccountTokenCreator --quiet >/dev/null && echo "removido: $EU -> TokenCreator sobre $PL"
if [ "${1:-}" = "--tudo" ]; then
  for R in roles/datastore.viewer roles/firebaseauth.viewer roles/logging.logWriter; do
    gcloud projects remove-iam-policy-binding $SEED --member="serviceAccount:$PL" --role="$R" --condition=None --quiet >/dev/null || true
  done
  gcloud iam service-accounts delete $AT --project=$TSI --quiet || true
  gcloud iam service-accounts delete $AR --project=$RAS --quiet || true
  gcloud iam service-accounts delete $PL --project=$SEED --quiet || true
  echo "contas de serviço da ponte removidas"
fi
