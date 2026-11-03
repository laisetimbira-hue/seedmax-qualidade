# SEEDMAX · Gestão de Qualidade (versão protegida)

Este repositório tem **só código**. Os dados da cooperativa (lotes,
análises, bags, compras, beneficiamento, campos) **nunca** entram aqui:
ficam no Firestore e só são entregues a quem faz login e está autorizado.

```
portal.seedmax.com.br  (público, sem dados)
        │  botão "Entrar" / "Abrir"
        ▼
app.seedmax.com.br     (este repositório — só a tela de login + código)
        │  Firebase Authentication (e-mail + senha, sem cadastro público)
        ▼
users/{uid}  →  active == true  e  role autorizado?
        │  sim
        ▼
Firestore: qualidade/*  →  dashboard roda com os dados
```

## Arquivos

| Arquivo | O que é |
|---|---|
| `index.html` | Dashboard de sempre + login real. Nenhum dado embutido. |
| `firestore.rules` | Regras de acesso (o que realmente protege os dados). |
| `scripts/atualizar.py` | Robô: Drive → processamento → Firestore (mesmos cálculos de antes). |
| `scripts/seedmax_dados.py` | Leitura/gravação dos conjuntos no Firestore (divisão em partes, gravação atômica, `lotId`). |
| `scripts/migrar_do_html.py` | Migração única: dados do `index.html` antigo → Firestore, com conferência. |
| `scripts/usuarios.py` | Cadastro/desativação de usuários (uso do administrador, no computador). |
| `.github/workflows/atualizar-dados.yml` | Atualização automática (a cada 15 min, horário comercial). |
| `.github/workflows/migracao-inicial.yml` | Botão para rodar a migração única. |
| `.github/workflows/testes.yml` | Testa as regras no emulador oficial do Firebase. |
| `tests/` | Testes das regras e teste de ponta a ponta do login. |

## Onde ficam os dados

Coleção `qualidade` no Firestore: um documento por conjunto, com o **mesmo
nome** da constante que antes ficava no HTML (`LOTS`, `SUMMARY`,
`SUMMARY_PREV`, `PMS_CV`, `LOTES_COMPRADOS`, `NOSSO_PLANTIO`, `BENEF`,
`HISTORICO_APROVACAO`, `MUDANCAS_RECENTES`, `DIAG_DATA`, `TZ_DATA`,
`CAMPOS_SIGEF`, `CV_META`, `CV_UBS` e os de Inverno), mais `qualidade/_meta`
com a versão e a data da atualização. Cada lote tem um `lotId` estável
(ex.: `SOJA2526_26S999X`) para a futura Central de Lotes (`lots/{lotId}`,
regra já pronta).

## Perfis (`users/{uid}`)

`{ name, email, role, active }` — `role` ∈ `ADMIN`, `QUALIDADE`, `TSI`,
`RASTREL`, `VISUALIZACAO`. Hoje leem a Qualidade: ADMIN, QUALIDADE e
VISUALIZACAO. Só ADMIN gerencia usuários. Ninguém grava dados pelo navegador.

Passo a passo de implantação: [`docs/IMPLANTACAO.md`](docs/IMPLANTACAO.md).
Cadastro de usuários: [`docs/USUARIOS.md`](docs/USUARIOS.md).
