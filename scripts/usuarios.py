#!/usr/bin/env python3
"""
SEEDMAX — cadastro de usuários autorizados (uso do ADMINISTRADOR).

Não existe cadastro público: só entra quem tiver
  1. conta no Firebase Authentication (e-mail + senha), e
  2. documento users/{uid} com active = true e um perfil (role).

Este script faz os dois passos. Precisa da variável FIREBASE_SERVICE_ACCOUNT
(JSON da conta de serviço) — rode no seu computador, nunca no navegador.
O mesmo pode ser feito à mão pelo Console do Firebase (ver docs/USUARIOS.md).

  python scripts/usuarios.py adicionar  --email x@y.com --nome "Fulano" --perfil QUALIDADE
  python scripts/usuarios.py desativar  --email x@y.com
  python scripts/usuarios.py reativar   --email x@y.com
  python scripts/usuarios.py perfil     --email x@y.com --perfil VISUALIZACAO
  python scripts/usuarios.py listar

Perfis: ADMIN, QUALIDADE, TSI, RASTREL, VISUALIZACAO
"""

import argparse
import secrets

import seedmax_dados as store

PERFIS = ["ADMIN", "QUALIDADE", "TSI", "RASTREL", "VISUALIZACAO"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("acao", choices=["adicionar", "desativar", "reativar", "perfil", "listar"])
    ap.add_argument("--email")
    ap.add_argument("--nome")
    ap.add_argument("--perfil", choices=PERFIS)
    a = ap.parse_args()

    destino = store._DestinoFirestore()  # exige FIREBASE_SERVICE_ACCOUNT
    from firebase_admin import auth, firestore
    users = destino.db.collection("users")

    if a.acao == "listar":
        for d in users.stream():
            u = d.to_dict()
            print(f"{u.get('email'):35s} {u.get('role'):13s} {'ativo' if u.get('active') else 'DESATIVADO':10s} {u.get('name')}")
        return

    if not a.email:
        raise SystemExit("Informe --email")
    email = a.email.strip().lower()

    if a.acao == "adicionar":
        if not (a.nome and a.perfil):
            raise SystemExit("Informe --nome e --perfil")
        try:
            u = auth.get_user_by_email(email)
            print("Conta de login já existia — só o cadastro de acesso será atualizado.")
        except auth.UserNotFoundError:
            senha = secrets.token_urlsafe(12)
            u = auth.create_user(email=email, password=senha, display_name=a.nome)
            print(f"Conta criada. Senha provisória (passe à pessoa por canal seguro): {senha}")
            print(f"Link para ela definir a própria senha: {auth.generate_password_reset_link(email)}")
        users.document(u.uid).set({
            "name": a.nome, "email": email, "role": a.perfil, "active": True,
            "createdAt": firestore.SERVER_TIMESTAMP, "updatedAt": firestore.SERVER_TIMESTAMP,
        })
        print(f"OK: {email} liberado como {a.perfil}.")
        return

    u = auth.get_user_by_email(email)
    if a.acao in ("desativar", "reativar"):
        ativo = a.acao == "reativar"
        users.document(u.uid).update({"active": ativo, "updatedAt": firestore.SERVER_TIMESTAMP})
        auth.update_user(u.uid, disabled=not ativo)
        if not ativo:
            auth.revoke_refresh_tokens(u.uid)  # derruba sessões abertas
        print(f"OK: {email} {'reativado' if ativo else 'desativado'}.")
    elif a.acao == "perfil":
        if not a.perfil:
            raise SystemExit("Informe --perfil")
        users.document(u.uid).update({"role": a.perfil, "updatedAt": firestore.SERVER_TIMESTAMP})
        print(f"OK: {email} agora é {a.perfil}.")


if __name__ == "__main__":
    main()
