#!/usr/bin/env python3
"""
PostSocial - Teste de Login no Instagram
Testa login real para um cliente específico e salva a sessão.
Uso: python test_login.py <client_id>
     python test_login.py            (testa o primeiro cliente)
"""

import json
import sys
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import (
    ChallengeRequired,
    TwoFactorRequired,
    BadPassword,
    PleaseWaitFewMinutes,
)

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config" / "clients.json"
SESSION_DIR = BASE_DIR / "sessions"
SESSION_DIR.mkdir(exist_ok=True)


def load_client(client_id: str = None) -> dict:
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)

    clients = config.get("clients", [])
    if not clients:
        print("❌ Nenhum cliente configurado.")
        sys.exit(1)

    if client_id:
        for c in clients:
            if c["id"] == client_id:
                return c
        print(f"❌ Cliente '{client_id}' não encontrado.")
        sys.exit(1)

    return clients[0]


def challenge_code_handler(username, choice):
    """Handler interativo para resolver challenge."""
    print(f"\n⚠️  CHALLENGE para {username}")
    print(f"    Método de verificação: {choice}")
    print("    O Instagram enviou um código para seu email/SMS.")
    code = input("    Digite o código de 6 dígitos: ").strip()
    return code


def main():
    client_id = sys.argv[1] if len(sys.argv) > 1 else None
    client = load_client(client_id)

    username = client["instagram"]["username"]
    password = client["instagram"]["password"]
    cid = client["id"]
    session_file = SESSION_DIR / f"{cid}_session.json"

    print("=" * 50)
    print(f"  Teste de Login — {client['name']}")
    print(f"  Username: {username}")
    print("=" * 50)

    cl = Client()
    cl.delay_range = [2, 5]

    # Handler para challenge interativo
    cl.challenge_code_handler = challenge_code_handler

    # Tentar sessão existente
    if session_file.exists():
        print("\n📂 Sessão salva encontrada. Tentando reutilizar...")
        try:
            cl.load_settings(session_file)
            cl.login(username, password)
            cl.get_timeline_feed()
            print("✅ Sessão restaurada com sucesso!")
            cl.dump_settings(session_file)
            _show_account_info(cl)
            return
        except Exception as e:
            print(f"⚠️  Sessão expirada: {e}")
            print("    Fazendo login fresh...")

    # Login fresh
    try:
        print("\n🔐 Fazendo login...")
        cl.login(username, password)
        cl.dump_settings(session_file)
        print(f"✅ Login realizado com sucesso!")
        print(f"   Sessão salva em: {session_file}")
        _show_account_info(cl)

    except BadPassword:
        print("❌ SENHA INCORRETA. Verifique config/clients.json")

    except ChallengeRequired:
        print("⚠️  Challenge será resolvido pelo handler...")
        # O handler já foi configurado acima, o instagrapi chama automaticamente
        try:
            cl.login(username, password)
            cl.dump_settings(session_file)
            print("✅ Challenge resolvido e sessão salva!")
            _show_account_info(cl)
        except Exception as e:
            print(f"❌ Falha ao resolver challenge: {e}")

    except TwoFactorRequired:
        print("⚠️  2FA ativo. Digite o código do app autenticador:")
        code = input("   Código 2FA: ").strip()
        try:
            cl.login(username, password, verification_code=code)
            cl.dump_settings(session_file)
            print("✅ Login 2FA realizado e sessão salva!")
            _show_account_info(cl)
        except Exception as e:
            print(f"❌ Falha 2FA: {e}")

    except PleaseWaitFewMinutes:
        print("❌ RATE LIMIT — Instagram pede para aguardar alguns minutos.")
        print("   Tente novamente em 10-15 minutos.")

    except Exception as e:
        print(f"❌ Erro: {type(e).__name__}: {e}")


def _show_account_info(cl: Client):
    """Mostra info básica da conta para confirmar login."""
    try:
        info = cl.account_info()
        print(f"\n   📊 Conta: @{info.username}")
        print(f"   👤 Nome: {info.full_name}")
        print(f"   📸 Posts: {info.media_count}")
        print(f"   👥 Seguidores: {info.follower_count}")
        print(f"   ➡️  Seguindo: {info.following_count}")
    except Exception:
        print("   (Info da conta não disponível)")


if __name__ == "__main__":
    main()
