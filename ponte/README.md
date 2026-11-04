# Ponte de login SEEDMAX → TSI / RASTREL — **NÃO IMPLANTADA**

Login só no Firebase `seedmax`; a função `ponteModulo` confere quem é e, se o perfil permitir,
devolve um *custom token* que o app do módulo usa **uma vez** em `signInWithCustomToken()`.
Depois disso a sessão do módulo é uma sessão normal do Firebase (o SDK renova o ID token a cada
hora); o custom token não serve para mais nada.

| Arquivo | O que é |
|---|---|
| `decisao.js` | Quem recebe login em qual módulo (função pura). VISUALIZACAO e QUALIDADE: nenhum módulo operacional |
| `ponte.js` | Fluxo da ponte com dependências injetadas; nunca registra tokens |
| `index.js` | Cloud Function 2ª geração (callable). **Exige Blaze — não publicada** |
| `test/` | Testes (`npm test`) |
| `prova/` | Prova técnica no Cloud Shell, **sem Blaze** |

## IAM (sem chave JSON)

| Conta | Projeto | Roles | Para quê |
|---|---|---|---|
| `ponte-login@seedmax-4c755` | seedmax | `datastore.viewer`, `firebaseauth.viewer`, `logging.logWriter` | ler `users/{uid}`, conferir revogação, registrar decisão |
| (mesma) | — | `iam.serviceAccountTokenCreator` **só sobre** as duas contas abaixo | pedir a assinatura ao IAM |
| `ponte-assina-tsi@estoquetsi` | estoquetsi | nenhuma | assina o login do TSI (conta precisa ser do projeto do TSI) |
| `ponte-assina-rastrel@rastreabilidade-a511a` | rastreabilidade-a511a | nenhuma | assina o login do RASTREL |

## Prova técnica (Cloud Shell, logada como dona dos projetos)

1. No console do Firebase **seedmax**: Authentication → adicionar um usuário de teste
   (ex.: `prova.ponte@sementescomvigor.com`, senha que você escolher). Copie o UID.
   Firestore → `users/<UID>` com `name`, `email`, `role = "TSI"`, `active = true`.
2. Cloud Shell:
   ```bash
   git clone https://github.com/laisetimbira-hue/seedmax-qualidade.git
   cd seedmax-qualidade/ponte/prova
   bash preparar.sh            # contas de serviço + permissões (sem chave)
   sleep 120                   # propagação do IAM
   npm install --no-audit --no-fund
   PROVA_EMAIL=prova.ponte@sementescomvigor.com node prova.mjs   # pede a senha, sem mostrar
   bash desfazer.sh            # remove a permissão temporária
   ```
3. Apague o usuário de teste no console (Authentication e `users/<UID>`).

A prova roda 10 cenários (TSI e RASTREL autorizados, perfis não autorizados, inativo, token
adulterado, regra do módulo como proteção final, assinatura por conta de outro projeto) e grava
`prova-resultado.json` **sem tokens**. Ela só cria e apaga dados de teste: o cadastro central do
usuário de teste é restaurado, os `users/<UID>` de teste nos módulos e os usuários de Auth criados
pela prova são apagados no fim.
