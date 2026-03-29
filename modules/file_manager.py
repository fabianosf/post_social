"""
Módulo de gerenciamento de arquivos.
Varre pasta de entrada, seleciona imagens não postadas e move para 'postados'.
"""

import shutil
from pathlib import Path
from typing import Optional

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


class FileManager:
    def __init__(self, entrada_dir: str, postados_dir: str, logger):
        self.entrada = Path(entrada_dir)
        self.postados = Path(postados_dir)
        self.logger = logger

        self.entrada.mkdir(parents=True, exist_ok=True)
        self.postados.mkdir(parents=True, exist_ok=True)

    def get_next_image(self) -> Optional[Path]:
        """
        Retorna a próxima imagem da pasta de entrada (ordem alfabética).
        Ignora arquivos que não são imagens suportadas.
        """
        images = sorted(
            f
            for f in self.entrada.iterdir()
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        )

        if not images:
            self.logger.info("Nenhuma imagem pendente na pasta de entrada")
            return None

        self.logger.info(
            f"{len(images)} imagem(ns) pendente(s). Próxima: {images[0].name}"
        )
        return images[0]

    def move_to_posted(self, image_path: Path) -> bool:
        """Move imagem para pasta de postados após sucesso."""
        try:
            dest = self.postados / image_path.name

            # Evitar sobrescrita
            if dest.exists():
                stem = image_path.stem
                suffix = image_path.suffix
                counter = 1
                while dest.exists():
                    dest = self.postados / f"{stem}_{counter}{suffix}"
                    counter += 1

            shutil.move(str(image_path), str(dest))
            self.logger.info(f"Imagem movida para postados: {dest.name}")
            return True

        except Exception as e:
            self.logger.error(f"Erro ao mover imagem: {e}")
            return False

    def count_pending(self) -> int:
        """Conta imagens pendentes."""
        return sum(
            1
            for f in self.entrada.iterdir()
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        )
