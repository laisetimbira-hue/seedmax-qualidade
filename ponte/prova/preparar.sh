#!/usr/bin/env bash
# SEEDMAX — prova técnica da ponte: contas de serviço e permissões (seção 12).
# Rodar no Cloud Shell, logada como dona dos projetos. NÃO cria chave JSON. NÃO liga Blaze.
set -euo pipefail
SEED=seedmax-4c755; TSI=estoquetsi; RAS=rastreabilidade-a511a
EU=$(gcloud config get-value account 2>/dev/null)
PL=ponte-login@$SEED.iam.gserviceaccount.com
AT=ponte-assina-tsi@$TSI.iam.gserviceaccount.com
AR=ponte-assina-rastrel@$RAS.iam.gserviceaccount.com
echo "Conta usada: $EU"

echo "== APIs (assinatura IAM)"
for P in $SEED $TSI $RAS; do gcloud services enable iamcredentials.googleapis.com --project=$P; done

crie() {  # conta  projeto  descrição
  if gcloud iam service-accounts describe "$1@$2.iam.gserviceaccount.com" --project="$2" >/dev/null 2>&1; then
    echo "já existe: $1@$2"
  else
    gcloud iam service-accounts create "$1" --project="$2" --display-name="$3"
  fi
}
echo "== Contas de serviço (sem chave)"
crie ponte-login          $SEED "SEEDMAX ponte de login (executa a funcao)"
crie ponte-assina-tsi     $TSI  "SEEDMAX ponte - assina login do TSI (sem permissoes no projeto)"
crie ponte-assina-rastrel $RAS  "SEEDMAX ponte - assina login do RASTREL (sem permissoes no projeto)"

echo "== Permissões definitivas da ponte-login (só no projeto seedmax)"
for R in roles/datastore.viewer roles/firebaseauth.viewer roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding $SEED --member="serviceAccount:$PL" --role="$R" --condition=None --quiet >/dev/null
  echo "ok $R"
done
echo "== ponte-login pode pedir assinatura SÓ das duas contas de assinatura"
gcloud iam service-accounts add-iam-policy-binding $AT --project=$TSI --member="serviceAccount:$PL" --role=roles/iam.serviceAccountTokenCreator --quiet >/dev/null && echo "ok TokenCreator sobre $AT"
gcloud iam service-accounts add-iam-policy-binding $AR --project=$RAS --member="serviceAccount:$PL" --role=roles/iam.serviceAccountTokenCreator --quiet >/dev/null && echo "ok TokenCreator sobre $AR"

echo "== TEMPORÁRIO (só durante a prova): você age como ponte-login"
gcloud iam service-accounts add-iam-policy-binding $PL --project=$SEED --member="user:$EU" --role=roles/iam.serviceAccountTokenCreator --quiet >/dev/null && echo "ok $EU -> TokenCreator sobre $PL"

echo "== Chaves das contas (devem ser só SYSTEM_MANAGED, nenhuma USER_MANAGED)"
for PAR in "$PL $SEED" "$AT $TSI" "$AR $RAS"; do
  set -- $PAR
  gcloud iam service-accounts keys list --iam-account="$1" --project="$2" --format="table[no-heading](name.basename(),keyType)" | sed "s#^#$1  #"
done
echo
echo "Pronto. Aguarde ~2 minutos (propagação do IAM) e rode:  npm install && PROVA_EMAIL=<e-mail do usuário de teste> node prova.mjs"
