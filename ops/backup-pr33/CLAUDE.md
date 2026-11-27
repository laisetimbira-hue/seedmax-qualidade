# Publicação do PR #33 (SEEDMAX) — roteiro para o Claude Code no Cloud Shell

Você está no Cloud Shell da Laise (dona e única ADMIN do SEEDMAX), projeto Firebase `seedmax-4c755`,
repositório `laisetimbira-hue/seedmax-qualidade`. Responda em português, direto e em linguagem simples.
Trabalhe sozinho, com comandos curtos, e confira o resultado de cada um antes de seguir.

## Regras que não mudam
- **Ordem obrigatória.** Não pule etapas e não avance se a anterior não terminou com ✔.
- **Nunca altere nem apague registros existentes** do Firestore, nem usuários, regras ou `firebase.json`.
  Nada de `gcloud firestore import` (restauração é decisão dela, fora deste roteiro).
- **Peça aprovação explícita da Laise antes de:** merge (etapa 5), deploy da função (etapa 6),
  disparo do workflow de publicação (etapa 7). Mostre o que vai rodar e espere um "sim".
- Não envie backups, totais nem dados ao GitHub. Não exponha senhas, tokens ou chaves.
- Se algo falhar ou fugir do esperado: pare, explique em 2–3 linhas e proponha o próximo passo.
- Ao final de cada etapa, diga em uma linha o que foi comprovado.

## Etapas
1. **Backup local verificado** — `bash executar.sh backup` → precisa de `BACKUP_OK` e "cópia idêntica ao banco no ar".
   Se o robô gravar no meio, rode de novo.
2. **Cópia no bucket privado verificada** — `bash executar.sh guardar` → bucket com acesso público bloqueado;
   a cópia é baixada de volta e verificada.
3. **Exportação oficial do Firestore** — `bash executar.sh exportar` → acompanha até `SUCCESSFUL`.
   Se estourar o tempo (código 4), rode o mesmo comando para retomar; não inicie outra exportação.
   Se falhar, `NOVA=1 bash executar.sh exportar` só depois de entender o erro.
4. **Totais e função** — `bash executar.sh funcao` e depois `bash executar.sh totais`.
   Mostre a revisão publicada da função e o resumo dos totais (itens/kg/lotes de Qualidade,
   Beneficiamento e Prestação de Serviço). Rode `bash executar.sh resumo`: tudo precisa estar preenchido.
5. **Merge do PR #33** (com aprovação) — confira antes: `main` ainda em `a950094`, PR em `f1e0f17`,
   checks verdes, sem conflito. Merge **sem squash** (`gh pr merge 33 --merge`). Se o `gh` não estiver
   autenticado, peça à Laise para rodar `gh auth login` ou fazer o merge pela página do GitHub.
   Atenção: o robô "Atualizar dados" roda a cada 15 min a partir da `main`; depois do merge ele passa a
   gravar `LOTS_SERVICO_INVERNO` com o campo `empresa`.
6. **Atualizar só a função de Beneficiamento** (com aprovação) — a função é publicada a partir de
   `~/seedmax-ponte`. Compare `ponte/benef-inverno.js` e `ponte/benef-inverno-funcao.js` da `main` nova
   com `~/seedmax-ponte/functions/src/`; mostre o diff (só o que o PR mudou). Rode
   `node --test ponte/test/*.test.js` no clone. Com aprovação, copie só esses arquivos e publique
   **só** `firebase deploy --only functions:ponte:sincronizarBenefInverno --project seedmax-4c755`.
   Confira com `gcloud functions describe` que a revisão mudou e o estado é ACTIVE.
   Volta: `~/seedmax-backups/<pasta>/funcao/ROLLBACK.txt`.
7. **Publicar o site pelo workflow oficial** (com aprovação) —
   `gh workflow run publicar-seedmax-firebase.yml --ref main -f confirmar=PUBLICAR` e acompanhe com
   `gh run watch`. O ambiente `producao-seedmax` pode pedir aprovação na página do GitHub: avise a Laise.
8. **Conferência depois da publicação** — `bash executar.sh depois` logo após publicar e de novo depois da
   primeira execução do robô. Nenhum lote pode ter sumido de Qualidade, Beneficiamento ou PGW;
   diferenças esperadas: só o campo `empresa` e eventuais lotes novos da AMBEV. Confira que
   https://app.seedmax.com.br responde (`curl -sI`). Termine com um resumo: backups (onde estão),
   revisão antiga e nova da função, commit publicado, resultado da conferência.
