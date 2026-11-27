# Beneficiamento de Inverno — sincronização a partir do servidor da empresa

A planilha oficial `LOTES BENEFICIADOS INVERNO 26-26.xlsx` continua no servidor
da empresa, preenchida normalmente pela equipe. Ela **não** vai para o Google
Drive, e o computador da empresa **não** tem credencial administrativa do Firebase.

```
Excel no servidor
  → computador da empresa (sincronizar_benef_inverno.py, Agendador de Tarefas)
      1. lê uma cópia da planilha
      2. interpreta e consolida por lote (Safra + Cultura + Lote)
      3. valida: repetição / conflito → PARA, nada é enviado
      4. compara com o publicado (hash) — igual: não envia nada
      5. envia as linhas para a função segura
  → Cloud Function sincronizarBenefInverno (ponte, southamerica-east1)
      valida de novo · consolida de novo · grava SÓ qualidade/BENEF_INVERNO
      (_meta mesclado em transação) · registra sincronizacoes/BENEF_INVERNO
  → SEEDMAX › Inverno › Beneficiamento
```

## Segurança

| Peça | Acesso |
|---|---|
| Computador da empresa | conta técnica do Firebase Auth, perfil `SINC_BENEF_INVERNO`; senha no Gerenciador de Credenciais do Windows; recebe um token de 1 h. As regras do Firestore **não liberam nada** para esse perfil: ele não lê nem grava dado nenhum direto. |
| Função `sincronizarBenefInverno` | roda como `sinc-benef-inverno@seedmax-4c755` (conta própria, **sem chave JSON**, papel *Cloud Datastore User*). Só aceita a conta `SINC_BENEF_INVERNO` (nem ADMIN usa essa porta). |
| O que a função grava | `qualidade/BENEF_INVERNO__N`, a entrada `BENEF_INVERNO` em `qualidade/_meta`, e `sincronizacoes/BENEF_INVERNO` (+ `historico`). Qualquer outro documento é recusado no código. |
| Revogar | desativar a conta técnica (`usuarios.py desativar`) ou trocar a senha: o próximo envio já é recusado. |

## Respostas da função (o script do Windows mostra no log)

| HTTP | `erro` | Quando |
|---|---|---|
| 200 | — | `mudou: true` (publicado) ou `mudou: false` (igual ao que já estava) |
| 400 | `payload_invalido` | vazio, campo desconhecido, outro conjunto, número fora do intervalo… |
| 401 / 403 | `token_invalido` / `sem_permissao` | sem login, senha errada, conta inativa, perfil errado |
| 409 | `conflito` | linha 100% idêntica repetida; mesmo lote com cultivar/categoria/peneira/embalagem/peso diferentes, Total ≠ N° BB × PESO, cultivar sem cultura |
| 422 | `queda_suspeita` | lotes caíram mais da metade (reenviar com `--confirmar-queda` se for de propósito) |

## Identidade do lote — não duplica

* Identidade única do Inverno: **Safra + Cultura + Lote** = `INV2626_<CULTURA>_<LOTE>`
  (mesma regra da Central de Lotes, TSI e RASTREL).
* Cultura: 1º `CV_META_INVERNO` pelo cultivar; senão a cultura escrita na planilha
  (ex.: título da aba "AVEIA BRANCA - …"); sem nenhuma das duas → conflito.
* Mesma cultura + mesmo lote → uma entrada só. Linhas do mesmo lote com os
  mesmos dados e quantidades diferentes → continuação: soma, na ordem aba/linha.
* Linha 100% idêntica repetida → CONFLITO (possível lançamento em dobro): a
  sincronização para, nada é publicado e o log aponta o lote e as duas linhas.
* Mesmo número de lote em culturas diferentes → lotes diferentes.
* Dados conflitantes no mesmo lote → a sincronização para e nada é publicado.
* Origem da identidade na Central = análises (`LOTS_INVERNO`/comprados). O
  beneficiamento é informação de uma etapa do lote.
* Central de Lotes: o beneficiamento é **vinculado** ao lote que já existe
  (`lots/{lotId}.beneficiamento`). Lote que só aparece no beneficiamento não
  vira documento novo na Central; aparece no relatório da sincronização da Central
  e se liga sozinho quando o lote entrar na planilha de análises.
* Os mesmos casos de teste rodam no Python e na função (`tests/casos_benef_inverno.json`).

## Instalação no computador da empresa (uma vez)

1. **Python 3.12** (python.org; marcar "Add python.exe to PATH"). Conferir: `py -3 --version`.
2. **Pasta** `C:\SEEDMAX\sincronizador\` com `sincronizar_benef_inverno.py`,
   `benef_inverno.py`, `central_lotes.py`, `requirements-benef-inverno.txt` e a
   subpasta `windows\` (cópia da pasta `scripts\` deste repositório).
3. **Bibliotecas**: `py -3 -m pip install -r C:\SEEDMAX\sincronizador\requirements-benef-inverno.txt`
   (só `openpyxl` e `keyring` — nada do Firebase).
4. **Configuração**: copiar `windows\config_benef_inverno.exemplo.bat` para
   `windows\config_benef_inverno.bat` e ajustar o caminho de rede da planilha e o
   e-mail da conta técnica.
5. **Senha da conta técnica** (uma vez, na conta do Windows que vai rodar a tarefa):
   `windows\sincronizar_benef_inverno.bat --guardar-senha`
6. **Teste sem enviar**: `windows\sincronizar_benef_inverno.bat --simular`
7. **Primeira sincronização**: o mesmo comando sem `--simular`; conferir a aba no SEEDMAX.
8. **Agendar**: `windows\agendar_tarefa.bat` como administrador (seg–sex, a cada
   15 min, 06:00–20:00; roda mesmo sem ninguém logado).

O computador precisa estar ligado, com acesso ao servidor e saída HTTPS para
`identitytoolkit.googleapis.com` e `southamerica-east1-seedmax-4c755.cloudfunctions.net`.

## Publicação (feita no Cloud Shell, quando aprovada)

1. Juntar a branch na `main` (inclui a correção do índice `_meta` no robô do GitHub).
2. Conta da função: `gcloud iam service-accounts create sinc-benef-inverno` +
   papel `roles/datastore.user` no projeto `seedmax-4c755`. Sem chave.
3. Copiar `ponte/benef-inverno.js` e `ponte/benef-inverno-funcao.js` para
   `~/seedmax-ponte/functions/src/` e acrescentar no fim do `index.js` da ponte:
   `Object.assign(exports, require('./src/benef-inverno-funcao'));`
4. Publicar **só** a função nova:
   `firebase deploy --only functions:ponte:sincronizarBenefInverno --project seedmax-4c755`
   (as quatro funções da ponte de login e o site não são tocados).
5. Conta técnica: `python scripts/usuarios.py adicionar --perfil SINC_BENEF_INVERNO ...`
6. Publicar o site (aba Beneficiamento) pelo caminho de sempre.

## Testes

* `python -m pytest tests/test_benef_inverno.py` — leitura, consolidação, os 4 casos
  de identidade, Central, índice concorrente e ponta a ponta local.
* `node --test ponte/test/*.test.js` — função (validação, autenticação, só BENEF_INVERNO).
* `tests/e2e_benef_inverno/emulador.py` — ponta a ponta nos emuladores oficiais
  (Auth + Firestore + Functions, projeto `demo-seedmax`).

## Localização atual do lote (RASTREL)

Na tabela **Inverno › Beneficiamento**, a coluna *Localização* mostra a posição
atual do lote no RASTREL; a localização digitada na planilha só aparece (marcada
"planilha") quando o RASTREL não tem informação confiável sobre o lote.

```
RASTREL (rastreabilidade-a511a) ── leitura, credencial federada somente leitura ──┐
  bags.localizacao_atual  (em_estoque com tag NFC + aguardando_tag, sem tag)      │
  mapa/fisico             (mapa do Excel + lotes cadastrados direto no mapa)      │
                                                                                  ▼
GitHub Actions "Central de Lotes" (scripts/central_lotes.py → localizacao_rastrel.py)
  grava SÓ qualidade/LOCAL_RASTREL_INVERNO__0 (+ entrada no _meta), e só quando muda
                                                                                  ▼
app.seedmax.com.br › Inverno › Beneficiamento (somente leitura)
```

* **Credencial:** a mesma da Central de Lotes — Workload Identity Federation, conta
  `central-lotes-leitura@rastreabilidade-a511a` com *Leitor do Cloud Datastore*, sem
  chave JSON, só a branch `main` deste repositório. O passo "Provar que TSI/RASTREL
  estão somente leitura" continua exigindo escrita recusada. Nenhuma regra do
  Firestore muda e nada é liberado para leitura pública: o navegador lê o conjunto
  em `qualidade/*`, com os mesmos perfis de sempre (ADMIN, QUALIDADE, VISUALIZACAO).
* **Nada é gravado no RASTREL** (bags, tags, movimentações, mapa) nem em outro
  conjunto do SEEDMAX.
* **Vínculo:** pelo `lotId` (Safra + Cultura + Lote, `INV2626_<CULTURA>_<LOTE>`).
  Bags usam a safra/cultura gravadas no próprio bag (bag antigo sem safra = Verão,
  nunca casa com o Inverno). Pilhas do mapa não têm lotId: casam pelo código do
  lote e, quando houver, safra, cultura/espécie e cultivar. Lote homônimo que
  continue ambíguo **não é vinculado** (aparece ⚠ com o motivo e vale a planilha).
* **Várias posições:** todas aparecem, com a quantidade de bags e a origem
  (`tag NFC`, `sem tag`, `mapa`). Mesma regra do mapa do RASTREL: se o lote tem bag
  com tag em estoque e posicionado, a pilha do Excel desse lote é ignorada; se
  todos os bags com tag já foram expedidos, também.
* **Sem o conjunto** (robô ainda não rodou, RASTREL desligado com
  `CENTRAL_RASTREL`, `mapa/fisico` ilegível) a tela continua igual, com a
  planilha. Falha nessa etapa não interrompe a sincronização da Central.
* Testes: `tests/test_localizacao_rastrel.py` e `tests/tela-local-rastrel.test.mjs`.
