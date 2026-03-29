#!/usr/bin/env python3
"""
Setup Instagram — Resolve o challenge interativamente e salva a sessão.
Rodar UMA VEZ por conta. Depois o worker usa a sessão salva.
"""

import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.models import db, InstagramAccount
from instagrapi import Client as IGClient

SESSION_DIR = Path("sessions")
SESSION_DIR.mkdir(exist_ok=True)


def challenge_code_handler(username, choice):
    print(f"\n⚠️  Instagram pediu verificação para @{username}")
    print(f"    Método: {choice}")
    print("    Verifique seu email ou SMS.")
    code = input("    Digite o código de 6 dígitos: ").strip()
    return code


def main():
    app = create_app()

    with app.app_context():
        # Buscar contas
        accounts = InstagramAccount.query.all()

        if not accounts:
            print("❌ Nenhuma conta Instagram cadastrada. Cadastre pelo painel web primeiro.")
            sys.exit(1)

        # Selecionar conta
        if len(accounts) == 1:
            account = accounts[0]
        else:
            print("Contas disponíveis:")
            for i, acc in enumerate(accounts):
                print(f"  {i + 1}. @{acc.ig_username} (cliente #{acc.client_id})")
            choice = int(input("Escolha o número: ")) - 1
            account = accounts[choice]

        username = account.ig_username
        password = account.get_ig_password()
        session_file = SESSION_DIR / f"client_{account.client_id}.json"

        print(f"\n🔐 Fazendo login em @{username}...")

        cl = IGClient()
        cl.delay_range = [2, 5]
        cl.challenge_code_handler = challenge_code_handler

        try:
            cl.login(username, password)
            cl.dump_settings(session_file)

            print(f"\n✅ Login realizado com sucesso!")
            print(f"   📊 @{username}")
            print(f"   Sessão salva em: {session_file}")
            print("   O worker agora vai conseguir postar sem pedir código.")

            account.status = "active"
            account.status_message = None
            db.session.commit()

        except Exception as e:
            print(f"\n❌ Erro: {type(e).__name__}: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
