# Usuários autorizados

Não existe cadastro público. Uma pessoa só entra se tiver **as duas coisas**:

1. **Conta de login** no Firebase Authentication (e-mail + senha);
2. **Cadastro de acesso** no Firestore: documento `users/{UID}` com
   `active = true` e um perfil (`role`).

Quem tiver só a conta de login (por exemplo, alguém que tentou se cadastrar
sozinho usando a chave pública do app) **não lê nada**: as regras do
Firestore exigem o cadastro de acesso ativo.

## Pelo Console do Firebase (sem programar)

1. **Authentication → Usuários → Adicionar usuário**: e-mail e senha
   provisória. Copie o **UID do usuário** que aparece na lista.
2. **Firestore Database → Iniciar coleção** `users` (só na primeira vez) →
   **ID do documento = o UID copiado** → campos:

   | campo | tipo | valor |
   |---|---|---|
   | `name` | string | Nome da pessoa |
   | `email` | string | e-mail (minúsculo) |
   | `role` | string | `ADMIN`, `QUALIDADE`, `TSI`, `RASTREL` ou `VISUALIZACAO` |
   | `active` | boolean | `true` |

3. Passe a senha provisória à pessoa por um canal seguro (pessoalmente,
   WhatsApp direto). Ela pode trocar pelo "esqueci a senha" do Firebase,
   ou você gera um link em Authentication → ⋮ → Redefinir senha.

## Desativar alguém

- Firestore → `users/{UID}` → `active` = `false` → **corta o acesso aos
  dados na hora**, mesmo que a pessoa esteja com a tela aberta (ao recarregar
  ela é barrada).
- Opcional: Authentication → ⋮ → **Desativar conta** (impede até o login).

## Pelo script (computador do administrador)

```
export FIREBASE_SERVICE_ACCOUNT="$(cat chave-da-conta-de-servico.json)"
cd scripts
python usuarios.py adicionar --email fulano@sementescomvigor.com --nome "Fulano" --perfil QUALIDADE
python usuarios.py desativar --email fulano@sementescomvigor.com
python usuarios.py listar
```

> A chave da conta de serviço é uma credencial administrativa: nunca a
> coloque no repositório, no HTML, em e-mail ou em grupo de mensagens.
