# Implantação segura — passo a passo

A ideia é que **nada do que funciona hoje pare** até a versão nova estar
validada. O repositório antigo (`dashboard-soja-2526`) e a automação antiga
continuam intactos até a etapa 6.

---

## Etapa 1 — Criar o projeto Firebase "seedmax" (Console, ~10 min)

1. https://console.firebase.google.com → **Adicionar projeto** → nome `seedmax`
   (o Google Analytics pode ficar desligado).
2. **Authentication → Vamos começar → E-mail/senha → Ativar** (deixe
   "Link do e-mail (login sem senha)" desligado).
3. **Firestore Database → Criar banco de dados** → local
   `southamerica-east1 (São Paulo)` → **modo de produção**.
4. **Firestore → Regras** → apague o conteúdo e cole o arquivo
   `firestore.rules` deste repositório → **Publicar**.
5. **Configurações do projeto (engrenagem) → Seus apps → Web (</>)** →
   apelido `seedmax-qualidade` → **não** marque Hosting → copie o bloco
   `firebaseConfig` e cole os valores em `SEEDMAX_FIREBASE_CONFIG` no
   `index.html` (já preenchido: projeto `seedmax-4c755`). Essa configuração é pública por
   natureza; quem protege os dados são as regras.
6. **Authentication → Configurações → Domínios autorizados** → adicionar:
   `laisetimbira-hue.github.io` (para o teste) e `app.seedmax.com.br`.
7. **Configurações do projeto → Contas de serviço → Gerar nova chave
   privada** → baixa um `.json`. Ele vai **só** para o secret
   `FIREBASE_SERVICE_ACCOUNT` (etapa 2). Depois apague o arquivo baixado.

Reforços opcionais (recomendados):
- Google Cloud Console → APIs e serviços → Credenciais → a chave "Browser
  key" do projeto → **Restrições de aplicativo: referenciadores HTTP** →
  `https://app.seedmax.com.br/*` e `https://laisetimbira-hue.github.io/*`.
- Authentication → Configurações → **Ações do usuário** → desmarcar
  "Ativar criação (inscrição)" — aparece quando o projeto usa o Identity
  Platform. Mesmo sem isso, quem se cadastrar sozinho não lê nada (não tem
  `users/{uid}` ativo).

## Etapa 2 — Criar o repositório novo (GitHub, web)

1. **New repository** → nome `seedmax-qualidade` → **Public** (só tem
   código) → sem README.
2. **Add file → Upload files** → arraste todo o conteúdo desta pasta
   (inclusive `.github`, `docs`, `scripts`, `tests`). Commit.
3. **Settings → Secrets and variables → Actions → New repository secret**:

   | Secret | Valor |
   |---|---|
   | `FIREBASE_SERVICE_ACCOUNT` | conteúdo inteiro do `.json` da etapa 1.7 |
   | `ID_ANALISES`, `ID_BENEF`, `ID_ANALISES_INVERNO`, `ID_BENEF_INVERNO` | os mesmos do repositório antigo |
   | `GMAIL_USUARIO`, `GMAIL_SENHA`, `EMAIL_DESTINO`, `EMAIL_ADMIN` | os mesmos do repositório antigo |

4. **Settings → Pages** → Source: *Deploy from a branch* → `main` / root.
   **Não** coloque domínio próprio ainda. O endereço de teste será
   `https://laisetimbira-hue.github.io/seedmax-qualidade/`.

## Etapa 3 — Levar os dados para o banco

1. **Actions → Migração inicial → Run workflow** (deixe os valores padrão).
   O log deve terminar com *"Conferência OK: o banco tem exatamente os mesmos
   dados do HTML antigo"*.
2. **Actions → Testes de segurança → Run workflow** → tudo verde.
3. **Actions → Atualizar dados → Run workflow** → verde. A partir daí ele
   roda sozinho a cada 15 min, **em paralelo** com o antigo. O e-mail para a
   equipe fica desligado neste repositório até a etapa 6.

## Etapa 4 — Cadastrar os usuários

Veja `docs/USUARIOS.md`. Comece por você como `ADMIN`.

## Etapa 5 — Validar no endereço de teste

Em `https://laisetimbira-hue.github.io/seedmax-qualidade/`:

- [ ] sem login: só aparece a tela de login (Ctrl+U: nenhum lote no código);
- [ ] senha errada → recusa;
- [ ] seu usuário → abre o dashboard;
- [ ] números iguais aos de `app.seedmax.com.br` (Visão Geral, Lotes,
      Comprados, Beneficiamento, Mapa de Campos, Inverno);
- [ ] "Sair" → volta ao login; recarregar não reabre;
- [ ] um usuário com `active = false` → bloqueado;
- [ ] depois de uma atualização do robô aparece "Dados atualizados".

## Etapa 6 — Virada (só depois da etapa 5 ok)

1. Repositório **antigo** → Settings → Pages → remover o domínio
   `app.seedmax.com.br`.
2. Repositório **novo** → Settings → Pages → Custom domain →
   `app.seedmax.com.br` → Enforce HTTPS. (O DNS já aponta para o GitHub.)
3. Repositório novo → Settings → Secrets and variables → Actions →
   **Variables** → `ENVIAR_EMAIL` = `sim`.
4. Repositório antigo → Actions → "Atualizar dashboard" → **Disable workflow**.
5. Repositório antigo → Settings → **Change visibility → Private**. Isso tira
   do ar o site antigo e o histórico público com os dados.

**Voltar atrás**, se algo der errado: desfazer os passos 1–2 (domínio de
volta no repositório antigo) e reativar o workflow antigo. Nada foi apagado.
