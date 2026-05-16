"""
Módulo de postagem no Facebook via Graph API.
Posta fotos em Páginas do Facebook usando Page Access Token.
"""

import os
from pathlib import Path
from typing import Optional

import httpx


GRAPH_API_URL = "https://graph.facebook.com/v21.0"


class FacebookPoster:
    def __init__(self, page_id: str, access_token: str, client_id: str, logger):
        self.page_id = page_id
        self.access_token = access_token
        self.client_id = client_id
        self.logger = logger

    def validate_token(self) -> bool:
        """Verifica se o token é válido e tem permissões necessárias."""
        try:
            self.logger.info(f"Validando token Facebook para página {self.page_id}")
            with httpx.Client(timeout=15) as client:
                resp = client.get(
                    f"{GRAPH_API_URL}/{self.page_id}",
                    params={
                        "fields": "name,id,access_token",
                        "access_token": self.access_token,
                    },
                )

            if resp.status_code == 200:
                data = resp.json()
                self.logger.info(f"Token válido. Página: {data.get('name', self.page_id)}")
                return True

            error = resp.json().get("error", {})
            self.logger.error(
                f"Token inválido. Código: {error.get('code')} — "
                f"{error.get('message', 'Erro desconhecido')}"
            )
            return False

        except Exception as e:
            self.logger.error(f"Erro ao validar token Facebook: {e}")
            return False

    def _permalink_for_id(self, post_id: str) -> Optional[str]:
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(
                    f"{GRAPH_API_URL}/{post_id}",
                    params={"fields": "permalink_url", "access_token": self.access_token},
                )
            if resp.status_code == 200:
                return resp.json().get("permalink_url")
            err = resp.json().get("error", {})
            self.logger.warning(f"[Facebook] permalink: {err.get('message', resp.text[:200])}")
        except Exception as e:
            self.logger.warning(f"[Facebook] permalink: {e}")
        return None

    def post_photo(self, image_path: str, caption: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Posta uma foto na Página do Facebook.
        Retorna (post_id, permalink_url, mensagem_erro).
        """
        path = Path(image_path)
        if not path.exists():
            self.logger.error(f"Imagem não encontrada: {image_path}")
            return None, None, "Imagem não encontrada"

        try:
            self.logger.info(f"[Facebook] Postando imagem: {path.name}")

            with open(path, "rb") as img_file:
                with httpx.Client(timeout=60) as client:
                    resp = client.post(
                        f"{GRAPH_API_URL}/{self.page_id}/photos",
                        data={
                            "message": caption,
                            "access_token": self.access_token,
                        },
                        files={
                            "source": (path.name, img_file, "image/jpeg"),
                        },
                    )

            if resp.status_code == 200:
                data = resp.json()
                post_id = str(data.get("post_id") or data.get("id") or "")
                link = self._permalink_for_id(post_id) if post_id else None
                self.logger.info(f"[Facebook] Postagem realizada! Post ID: {post_id}")
                return post_id or None, link, None

            error = resp.json().get("error", {})
            msg = f"Código {error.get('code')}: {error.get('message', 'Erro desconhecido')}"
            self.logger.error(f"[Facebook] Erro na postagem. {msg}")
            return None, None, msg

        except httpx.TimeoutException:
            self.logger.error("[Facebook] Timeout no upload da imagem.")
            return None, None, "Timeout no upload da imagem no Facebook"

        except Exception as e:
            self.logger.error(f"[Facebook] Erro ao postar: {type(e).__name__}: {e}")
            return None, None, f"{type(e).__name__}: {e}"

    def post_text(self, message: str) -> Optional[str]:
        """Posta somente texto (sem imagem) na Página."""
        try:
            self.logger.info("[Facebook] Postando texto")

            with httpx.Client(timeout=30) as client:
                resp = client.post(
                    f"{GRAPH_API_URL}/{self.page_id}/feed",
                    data={
                        "message": message,
                        "access_token": self.access_token,
                    },
                )

            if resp.status_code == 200:
                post_id = resp.json().get("id")
                self.logger.info(f"[Facebook] Texto postado! Post ID: {post_id}")
                return str(post_id)

            error = resp.json().get("error", {})
            self.logger.error(
                f"[Facebook] Erro: {error.get('code')} — {error.get('message')}"
            )
            return None

        except Exception as e:
            self.logger.error(f"[Facebook] Erro ao postar texto: {e}")
            return None
