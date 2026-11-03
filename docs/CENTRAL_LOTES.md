# Central de Lotes — fase 1 (somente leitura)

Integra Qualidade → TSI → RASTREL → Expedição usando o **lote** como elo.
Nesta fase a Central **só consulta e resume**. Nenhum módulo escreve no outro
e nada é gravado no TSI nem no RASTREL.

```
 Qualidade (seedmax)         TSI (estoquetsi)            RASTREL (rastreabilidade-a511a)
 qualidade/* (robô)          lotesTratamento             bags
        │ leitura                    │ leitura (WIF, só leitura)  │ leitura (WIF, só leitura)
        └──────────────┬─────────────┴──────────────┬─────────────┘
                       ▼                            
        GitHub Actions: "Central de Lotes" (scripts/central_lotes.py), de hora em hora
                       │ grava SÓ o resumo
                       ▼
        seedmax: lots/{lotId}   ──►  app.seedmax.com.br → aba "Central de Lotes" (somente leitura)
```

## Identificador

* `lotId = SAFRA_LOTE` — ex.: `SOJA2526_26S133C`
* `lotCode` = `26S133C` (maiúsculas, sem espaços nem ponto no fim), `crop` = `SOJA2526`
* Lote que não está na Qualidade: `SEMSAFRA_<lote>` (a safra não é inventada).
* TSI: `sourceLotId` (lote que entrou) e `treatedLotId` (lote que saiu); iguais quando o
  código não muda. Gravados pelo próprio TSI em cada linha de lote das ordens novas. `parentLotIds` fica vazio — só para mistura/divisão no futuro.
* Os registros atuais dos módulos **não são alterados**.

## Modelo `lots/{lotId}`

| Campo | Origem | Observação |
|---|---|---|
| `lotId`, `lotCode`, `crop`/`safra` | calculado | |
| `cultivar`, `cultivarNome`, `categoria`, `peneira`, `pms` | Qualidade | fonte oficial |
| `qualidadeStatus` | Qualidade | APROVADO (A, B) · CONDICIONAL (C, BV) · REPROVADO (D) · PENDENTE (X / comprado sem "APROVADO") · NÃO ENCONTRADO |
| `qualidadeClasse` | Qualidade | A, B, C, BV, D, X |
| `qualidade{}` | Qualidade | rótulo, germ., vigor, PMS, bags, kg |
| `tsiStatus` | TSI | CONCLUÍDO · EM ANDAMENTO · SEM ORDEM COM LOTE · NÃO CONECTADO |
| `sourceLotId`, `treatedLotId`, `tsi{ordens[]}` | TSI | só ordens que informam o lote de semente |
| `rastrelStatus` | RASTREL | COMPLETO · PARCIAL · COM BAGS · SEM BAGS · NÃO CONECTADO |
| `totalBags` | Qualidade | bags previstos |
| `taggedBags`, `rastrel{}` | RASTREL | bags com tag, expedidos, em estoque, tratamento |
| `situacao`, `motivo` | calculado | ver abaixo |
| `divergencias[]` | calculado | `{campo, tipo: divergencia/aviso, texto, qualidade, tsi, rastrel}` |
| `modulos[]`, `presente`, `hash`, `lastUpdate` | robô | `presente=false` quando o lote sumiu da origem (nunca apaga) |

## Situação do lote

| Situação | Regra |
|---|---|
| QUALIDADE PENDENTE | Qualidade não aprovada (condicional, reprovada ou pendente) e o lote não aparece no TSI nem no RASTREL |
| LIBERADO PARA TSI | Aprovado; nenhuma ordem do TSI registra o lote; nenhum bag no RASTREL |
| EM TSI | Aprovado; há ordem **aberta** no TSI com este lote |
| AGUARDANDO RASTREL | Aprovado; TSI concluído; nenhum bag com tag |
| RASTREANDO | Aprovado; TSI concluído; parte dos bags previstos com tag |
| PRONTO | Aprovado; TSI concluído; todos os bags previstos com tag |
| INDETERMINADO | Os dados não permitem decidir: lote fora da Qualidade; lote não aprovado mas já tratado/rastreado; bags no RASTREL sem ordem com lote no TSI; módulo não conectado |

Limitação conhecida: das 255 ordens antigas do TSI, só as importadas do PDF (22) informam o
lote de semente. Por isso "LIBERADO PARA TSI" quer dizer "o TSI não tem ordem com este
lote", e lotes com bags no RASTREL mas sem ordem com lote ficam INDETERMINADO.

### Lote obrigatório no TSI (desde nov/2026)

* O lote de semente é obrigatório para **fechar** uma ordem (e para "Tratar novo lote", que já
  fecha na hora):
  * "Tratar novo lote": bloco *Lotes de semente* (origem, lote tratado se o código mudar, kg);
  * "Importar PDF": o fluxo continua igual. PDF **sem lote entra normalmente**, marcado
    `LOTE PENDENTE` (`lotePendente: true`, `lotesDetalhe: []`); o botão "Informar lote" grava o
    lote depois (sem mexer no estoque) e "Fechar ordem" fica bloqueado até isso;
  * "Fechar ordem": usa os lotes já gravados na ordem (do PDF ou informados).
* Cada linha de `lotesDetalhe` passa a ter `sourceLotCode`, `sourceLotId`, `treatedLotCode`,
  `treatedLotId` (mesma regra de `codigo_lote`/`montar_lot_id`). A ordem guarda também `safra`,
  `sourceLotIds[]`, `treatedLotIds[]`. Linhas digitadas à mão têm `fonteLote: "manual"` e já
  gravam o código no formato padrão.
* O robô usa `sourceLotCode`/`treatedLotCode` quando existem (senão, `origem`/`destino`).
  Se o `sourceLotId` gravado pelo TSI for diferente do `lotId` da Central (ex.: lote fora da
  Qualidade → `SEMSAFRA_`), o lote recebe o **aviso** `lotId`. Ordens abertas com lote pendente
  não entram no vínculo e são contadas no log.
* Ordens antigas não são alteradas e nenhum lote histórico é preenchido automaticamente.
  As regras do Firestore do TSI ainda **não** exigem o lote (a exigência está na tela);
  exigir também nas regras é uma etapa futura, a propor e testar.

### Safra ativa (um lugar por sistema)

| Sistema | Onde | Valor atual |
|---|---|---|
| TSI | `estoquetsi/index.html` → `const SAFRA_ATIVA` (bloco "SAFRA ATIVA", logo antes do `firebaseConfig`) | `SOJA2526` |
| Central | `scripts/central_lotes.py` → `SAFRA_ATIVA` | `SOJA2526` |

Os dois sistemas estão em projetos/domínios separados e o TSI grava o identificador no
momento em que a ordem é salva; por isso a safra **não** é buscada de outro site em tempo real
(se a busca falhasse, ordens poderiam sair com a safra errada). Na virada, trocar os dois
juntos. O robô avisa no log quando encontra ordens do TSI com safra diferente da ativa, e cada
lote nessa situação recebe o aviso `lotId`.

## Sincronização

* Workflow `.github/workflows/central-lotes.yml`, de hora em hora (07h–19h, seg–sáb) e manual.
* Lê a Qualidade do próprio `seedmax`, o TSI (`lotesTratamento`, só os campos necessários)
  e o RASTREL (`bags`, só os campos necessários).
* Regrava só os lotes cujo resumo mudou (`hash`). Nunca apaga.
* Cada módulo só é lido quando a variável do repositório estiver ligada:
  `CENTRAL_TSI = sim`, `CENTRAL_RASTREL = sim`. Desligado → "NÃO CONECTADO".
* Antes de ler, o robô tenta **uma escrita impossível** (documento inexistente, pré-condição
  de 2000) em cada módulo e exige que ela seja **recusada por permissão**. Se não for, para
  sem gravar nada.

## Credenciais (sem chave JSON permanente)

* **TSI e RASTREL:** Workload Identity Federation. O GitHub prova a identidade por OIDC e o
  Google entrega um token de ~1 hora da conta `central-lotes-leitura@<projeto>`, que só tem
  `roles/datastore.viewer` (Leitor do Cloud Datastore). Nenhuma chave é criada.
* O pool `github` (no projeto `seedmax-4c755`) só aceita o repositório
  `laisetimbira-hue/seedmax-qualidade` (pelo **ID numérico** do repositório e do dono, que
  não podem ser reaproveitados por outra conta) e só a branch `main`.
* **seedmax (gravar `lots/`):** a mesma credencial que o robô da Qualidade já usa.
* As chaves do repositório `seedmax-backups` **não** são usadas aqui.
* Limitação do Firestore: o papel de leitor vale para o banco inteiro do projeto (não dá
  para restringir por coleção via IAM). O robô lê apenas `lotesTratamento` e `bags`.

### Configuração (uma vez, no Cloud Shell, logado como dona dos projetos)

```bash
REPO_ID=1444336147; OWNER_ID=286724932; CENTRAL=seedmax-4c755; CENTRAL_NUM=261583026851

gcloud services enable iam.googleapis.com sts.googleapis.com iamcredentials.googleapis.com --project=$CENTRAL
gcloud iam workload-identity-pools create github --project=$CENTRAL --location=global \
  --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc seedmax-qualidade --project=$CENTRAL \
  --location=global --workload-identity-pool=github --display-name="seedmax-qualidade" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository_id=assertion.repository_id,attribute.repository_owner_id=assertion.repository_owner_id,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository_id=='$REPO_ID' && assertion.repository_owner_id=='$OWNER_ID' && assertion.ref=='refs/heads/main'"

for P in estoquetsi rastreabilidade-a511a; do
  gcloud services enable iamcredentials.googleapis.com --project=$P
  gcloud iam service-accounts create central-lotes-leitura --project=$P \
    --display-name="Central de Lotes (somente leitura)"
  gcloud projects add-iam-policy-binding $P --condition=None \
    --member="serviceAccount:central-lotes-leitura@$P.iam.gserviceaccount.com" \
    --role="roles/datastore.viewer"
  gcloud iam service-accounts add-iam-policy-binding central-lotes-leitura@$P.iam.gserviceaccount.com \
    --project=$P --role="roles/iam.workloadIdentityUser" \
    --member="principalSet://iam.googleapis.com/projects/$CENTRAL_NUM/locations/global/workloadIdentityPools/github/attribute.repository_id/$REPO_ID"
done
```

Depois: GitHub → `seedmax-qualidade` → Settings → Secrets and variables → Actions →
**Variables** → `CENTRAL_TSI = sim` e `CENTRAL_RASTREL = sim` → Actions → "Central de
Lotes" → Run workflow. O passo "Provar que TSI/RASTREL estão somente leitura" tem de
mostrar "escrita RECUSADA" nos dois.

### Desligar / voltar atrás

* Parar a leitura: apagar as variáveis `CENTRAL_TSI` / `CENTRAL_RASTREL`.
* Revogar o acesso: `gcloud iam service-accounts delete central-lotes-leitura@<projeto>.iam.gserviceaccount.com --project=<projeto>`
  (só remove o acesso da Central; não toca nos dados).
* A Central não grava nos módulos, então não há o que desfazer neles.
