# Backup verificado antes da publicação do PR #33

Ferramenta operacional (branch de trabalho, **não vai para a `main`**). Não contém
credenciais nem dados: roda no Cloud Shell com a conta já autenticada lá.

| comando | o que faz |
|---|---|
| `bash executar.sh backup` | copia todo o Firestore em JSON (pasta privada `~/seedmax-backups`), confere hashes, remonta os conjuntos da coleção `qualidade` e registra totais/lotes |
| `bash executar.sh guardar` | envia a cópia para o bucket privado `gs://seedmax-4c755-backups` (acesso público bloqueado) e confere baixando de volta |
| `bash executar.sh exportar` | exportação oficial do Firestore para o mesmo bucket; confirma estado `SUCCESSFUL` |
| `bash executar.sh funcao` | registra a revisão publicada de `sincronizarBenefInverno` e guarda o código-fonte dela |
| `bash executar.sh depois` | após publicar: totais atuais comparados com os de antes (aponta lotes que sumiram) |

Nenhum comando grava, altera ou apaga dados do Firestore. `bash testar.sh` testa tudo
contra um Firestore falso (dados fictícios) que derruba o teste em qualquer tentativa de escrita.
