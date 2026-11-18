# Beneficiamento de Inverno — sincronização a partir do servidor da empresa

A planilha oficial `LOTES BENEFICIADOS INVERNO 26-26.xlsx` continua no
servidor da empresa e continua sendo preenchida normalmente pela equipe.
Ela **não** vai para o Google Drive. Um computador Windows da empresa lê a
planilha e atualiza o SEEDMAX.

```
Excel no servidor  →  sincronizar_benef_inverno.py (Windows, Agendador de Tarefas)
                   →  transforma em BENEF_INVERNO
                   →  compara com o Firestore (qualidade/BENEF_INVERNO)
                   →  grava só se mudou, e só esse conjunto
                   →  SEEDMAX › Inverno › Beneficiamento
```

## O que o sincronizador NÃO toca

LOTS_INVERNO, análises, lotes comprados, nosso plantio, dados de verão, TSI e
RASTREL. O script entrega para gravação um único conjunto (`BENEF_INVERNO`);
os outros são lidos (CV_META_INVERNO, para a cultura) e nunca reescritos. O
robô do GitHub (`atualizar.py`) também nunca grava `BENEF_INVERNO`.

O índice `qualidade/_meta` é atualizado dentro de uma transação que relê o
índice na hora de gravar e troca só a entrada do próprio conjunto — o robô do
GitHub e o sincronizador podem rodar ao mesmo tempo sem um apagar o que o
outro gravou (ver `seedmax_dados.gravar_mesclando`). **Essa correção precisa
estar na `main` antes de ligar o sincronizador.**

## Regras de leitura da planilha

* Todas as abas visíveis (hoje `INVERNO 2026` e `PGW`); colunas achadas pelo
  texto do cabeçalho: DATA, CULTIVAR, SAFRA, CAT., LOTE, PEN., EMBALAGEM,
  N° BB, PESO, Total, Localização, Observações.
* Só vira lote a linha com CULTIVAR, LOTE e N° BB > 0. Linhas de totalização
  (`N° BAGS / FINALIZADO`) são ignoradas.
* Volume do lote = coluna **Total**; se vazia, N° BB × PESO (diferença entre
  os dois vira aviso no log).
* Peneira vai como está na planilha (`S/P`) — não existe P1/P2 no Inverno.
* Cultura: 1º `CV_META_INVERNO` pelo cultivar; senão a cultura escrita na
  planilha (ex.: título da aba "AVEIA BRANCA - IMPACTA"); senão vazio.
* `lotId` pela regra única da Central de Lotes: `INV2626_<CULTURA>_<LOTE>`.

Travas: se a planilha ficar sem nenhum lote, ou cair mais da metade dos
lotes de uma vez, o script **não grava** (sai com código 2 e explica no log).

## Instalação no computador da empresa (uma vez)

1. **Python 3.12** (python.org → Windows installer; marcar "Add python.exe to
   PATH"). Conferir no prompt: `py -3 --version`.
2. **Pasta** `C:\SEEDMAX\` com:
   * `sincronizador\` → cópia da pasta `scripts\` deste repositório
     (precisa de `sincronizar_benef_inverno.py`, `benef_inverno.py`,
     `seedmax_dados.py`, `central_lotes.py`, `requirements-benef-inverno.txt`
     e a subpasta `windows\`);
   * `credencial\` → o arquivo da conta de serviço (ver item 4);
   * `logs\` → criada sozinha.
3. **Bibliotecas**: `py -3 -m pip install -r C:\SEEDMAX\sincronizador\requirements-benef-inverno.txt`
4. **Credencial**: conta de serviço dedicada `seedmax-benef-inverno` no
   projeto `seedmax-4c755`, papel *Cloud Datastore User*; baixar a chave JSON
   e salvar em `C:\SEEDMAX\credencial\seedmax-benef-inverno.json`. Restringir
   a pasta (Propriedades → Segurança) à conta que roda a tarefa e aos
   administradores. Nunca enviar esse arquivo por e-mail nem colocar no
   repositório.
5. **Configuração**: copiar `windows\config_benef_inverno.exemplo.bat` para
   `windows\config_benef_inverno.bat` e ajustar o caminho de rede da planilha
   (`\\SERVIDOR\...`, não `Z:\`) e o da credencial.
6. **Teste sem gravar**: `C:\SEEDMAX\sincronizador\windows\sincronizar_benef_inverno.bat --simular`
7. **Primeira gravação**: o mesmo comando sem `--simular`. Conferir a aba no SEEDMAX.
8. **Agendar**: executar `windows\agendar_tarefa.bat` como administrador
   (seg–sex, a cada 15 min, 06:00–20:00; pede a senha da conta que acessa o
   servidor, para rodar mesmo sem ninguém logado).

O computador precisa estar ligado e com acesso ao servidor e à internet
(saída HTTPS para `firestore.googleapis.com`) no horário da tarefa.

## Operação

* Log mensal em `C:\SEEDMAX\logs\benef_inverno_AAAA-MM.log`.
* Rodar na mão a qualquer momento: o `.bat` (com ou sem `--simular`).
* Ver/pausar a tarefa: Agendador de Tarefas → "SEEDMAX - Beneficiamento Inverno".
* Planilha aberta no Excel por alguém não atrapalha: o script lê uma cópia.
