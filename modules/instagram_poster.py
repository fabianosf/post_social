"""
Módulo de postagem no Instagram via instagrapi.
Gerencia login, sessão, challenge handling e upload de fotos.
"""

import json
import time
import random
from pathlib import Path
from typing import Optional

from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired,
    ChallengeRequired,
    TwoFactorRequired,
    BadPassword,
    PleaseWaitFewMinutes,
)


SESSION_DIR = Path("sessions")


class InstagramPoster:
    def __init__(self, username: str, password: str, client_id: str, logger):
        self.username = username
        self.password = password
        self.client_id = client_id
        self.logger = logger
        self.client = Client()
        self.client.delay_range = [2, 5]  # delay entre requisições internas

        SESSION_DIR.mkdir(exist_ok=True)

    @property
    def session_file(self) -> Path:
        return SESSION_DIR / f"{self.client_id}_session.json"

    def login(self) -> bool:
        """
        Login com reuso de sessão salva.
        Fluxo:
          1. Tenta carregar sessão existente
          2. Se falhar, faz login fresh
          3. Salva sessão para próximo uso
        """
        # Tentar reuso de sessão
        if self.session_file.exists():
            try:
                self.logger.info(f"Carregando sessão salva para {self.username}")
                self.client.load_settings(self.session_file)
                self.client.login(self.username, self.password)
                self.client.get_timeline_feed()  # valida sessão
                self.logger.info("Sessão restaurada com sucesso")
                return True
            except (LoginRequired, Exception) as e:
                self.logger.warning(f"Sessão expirada, fazendo login fresh: {e}")
                self.session_file.unlink(missing_ok=True)

        # Login fresh
        try:
            self.logger.info(f"Login fresh para {self.username}")
            self.client.login(self.username, self.password)
            self.client.dump_settings(self.session_file)
            self.logger.info("Login realizado e sessão salva")
            return True

        except BadPassword:
            self.logger.error(f"ERRO: Senha incorreta para {self.username}")
            return False

        except ChallengeRequired as e:
            self.logger.error(
                f"CHALLENGE REQUIRED para {self.username}. "
                f"Verifique o email/SMS vinculado à conta. Detalhes: {e}"
            )
            return self._handle_challenge()

        except TwoFactorRequired:
            self.logger.error(
                f"2FA ativo para {self.username}. "
                "Configure o TOTP no config ou desative 2FA na conta."
            )
            return False

        except PleaseWaitFewMinutes:
            self.logger.error(
                f"RATE LIMIT: Instagram pede para aguardar. "
                f"Cliente {self.client_id} será ignorado nesta execução."
            )
            return False

        except Exception as e:
            self.logger.error(f"Erro inesperado no login: {type(e).__name__}: {e}")
            return False

    def _handle_challenge(self) -> bool:
        """
        Tenta resolver challenge automaticamente.
        O Instagram pode enviar código por email/SMS.
        """
        try:
            # Solicita envio do código por email (método 1)
            self.client.challenge_resolve(self.client.last_json)
            self.logger.warning(
                "Challenge enviado. Um código foi enviado para o email/SMS da conta. "
                "Para resolver automaticamente, implemente um leitor de email "
                "ou execute manualmente: python -m modules.challenge_solver"
            )
            return False
        except Exception as e:
            self.logger.error(f"Não foi possível resolver challenge: {e}")
            return False

    def post_photo(self, image_path: str, caption: str) -> Optional[str]:
        """
        Posta uma foto no Instagram.
        Retorna o media_id em caso de sucesso, None em caso de falha.
        """
        path = Path(image_path)
        if not path.exists():
            self.logger.error(f"Imagem não encontrada: {image_path}")
            return None

        try:
            self.logger.info(f"Postando imagem: {path.name}")
            media = self.client.photo_upload(
                path=path,
                caption=caption,
            )
            media_id = media.pk
            self.logger.info(f"Postagem realizada! Media ID: {media_id}")
            return str(media_id)

        except PleaseWaitFewMinutes:
            self.logger.error("RATE LIMIT durante postagem. Abortando.")
            return None

        except LoginRequired:
            self.logger.error("Sessão perdida durante postagem. Re-login necessário.")
            return None

        except Exception as e:
            self.logger.error(f"Erro ao postar: {type(e).__name__}: {e}")
            return None

    def logout(self):
        """Encerra sessão de forma limpa."""
        try:
            self.client.dump_settings(self.session_file)
            self.logger.debug("Sessão salva antes de encerrar")
        except Exception:
            pass
