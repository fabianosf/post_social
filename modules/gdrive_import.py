"""
Google Drive Import — Importa fotos/vídeos de uma pasta compartilhada do Drive.

Dois modos de autenticação (tenta na ordem):
  1. Service Account (completo) — requer credentials/gdrive_service_account.json
  2. gdown (público)            — funciona para pastas com link de compartilhamento ativo,
                                  sem nenhuma configuração adicional

Para o modo gdown:
  pip install gdown>=5.0.0

Para o modo Service Account:
  pip install google-api-python-client google-auth
  (siga credentials/COMO_CONFIGURAR.md)
"""

import io
import os
import re
import shutil
import tempfile
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
CREDS_PATH = os.environ.get(
    "GDRIVE_CREDENTIALS_PATH",
    str(BASE_DIR / "credentials" / "gdrive_service_account.json"),
)

SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov"}
SUPPORTED_MIME = {
    "image/jpeg", "image/png", "image/webp", "image/gif",
    "video/mp4", "video/quicktime",
}

# Mapeamento de nomes de dias PT → weekday (0=segunda … 6=domingo)
_DAY_ALIASES = {
    "segunda": 0, "seg": 0, "segunda-feira": 0, "segunda feira": 0,
    "terca": 1, "terca-feira": 1, "terca feira": 1,
    "terça": 1, "terça-feira": 1, "ter": 1,
    "quarta": 2, "qua": 2, "quarta-feira": 2, "quarta feira": 2,
    "quinta": 3, "qui": 3, "quinta-feira": 3, "quinta feira": 3,
    "sexta": 4, "sex": 4, "sexta-feira": 4, "sexta feira": 4,
    "sabado": 5, "sab": 5, "sábado": 5, "sáb": 5,
    "domingo": 6, "dom": 6,
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def extract_folder_id(url_or_id: str) -> str:
    """Extrai o folder ID de uma URL do Drive ou retorna o ID diretamente."""
    if not url_or_id:
        return ""
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", url_or_id)
    if match:
        return match.group(1)
    if re.match(r"^[a-zA-Z0-9_-]{20,}$", url_or_id.strip()):
        return url_or_id.strip()
    return ""


def _normalize(text: str) -> str:
    """Remove acentos simples para comparação de nomes de dias."""
    return (text.lower()
            .replace("ç", "c").replace("á", "a").replace("é", "e")
            .replace("ã", "a").replace("â", "a").replace("ó", "o")
            .replace("ú", "u").replace("í", "i").replace("à", "a"))


def _detect_day_from_filename(filename: str) -> int | None:
    """Detecta dia da semana pelo nome do arquivo. Ex: segunda.jpg → 0"""
    name = _normalize(Path(filename).stem)
    for alias, weekday in _DAY_ALIASES.items():
        if _normalize(alias) in name:
            return weekday
    return None


def _parse_postagens_txt(content: str) -> dict[int, dict]:
    """
    Parseia o arquivo de postagens do Drive.

    Suporta dois formatos:

    Formato A (simples — uma linha por dia):
        Segunda: Legenda aqui #hashtag1 #hashtag2
        Terça: Outra legenda #hashtag

    Formato B (bloco — separados por === com campos):
        =============================================
        SEGUNDA-FEIRA
        Imagem: segunda-feira.jpg
        Horários: 9:00 e 17:00
        Legenda:
        Texto multilinhas da legenda
        com emojis e tudo
        #hashtag1 #hashtag2
        =============================================

    Retorna {weekday: {caption, hashtags, hours: [9, 17]}}.
    """
    import re as _re

    captions: dict[int, dict] = {}

    # ── Detectar formato B (blocos com ======) ──────────────
    if "======" in content and "Legenda:" in content:
        # Dividir em blocos pelo separador
        blocks = _re.split(r"=+", content)
        for block in blocks:
            block = block.strip()
            if not block:
                continue

            lines = block.splitlines()
            if not lines:
                continue

            # Primeira linha não-vazia é o nome do dia
            day_name = ""
            body_start = 0
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    day_name = stripped
                    body_start = i + 1
                    break

            weekday = _DAY_ALIASES.get(day_name.lower()) or _DAY_ALIASES.get(_normalize(day_name))
            if weekday is None:
                continue

            # Extrair horários (linha "Horários: 9:00 e 17:00")
            hours = []
            legenda_start = body_start
            for i, line in enumerate(lines[body_start:], start=body_start):
                if line.strip().lower().startswith("horário"):
                    nums = _re.findall(r"\b(\d{1,2}):\d{2}", line)
                    hours = [int(n) for n in nums]
                elif line.strip().lower() == "legenda:":
                    legenda_start = i + 1
                    break

            # Resto é a legenda (multilinhas)
            legenda_lines = lines[legenda_start:]
            full_text = "\n".join(legenda_lines).strip()

            # Separar hashtags (linhas ou palavras com #)
            text_lines = []
            hashtag_tokens = []
            for ln in full_text.splitlines():
                words = ln.split()
                ht = [w for w in words if w.startswith("#")]
                tx = [w for w in words if not w.startswith("#")]
                if ht:
                    hashtag_tokens.extend(ht)
                if tx:
                    text_lines.append(" ".join(tx))

            caption = "\n".join(text_lines).strip()
            hashtags = " ".join(hashtag_tokens).strip()

            captions[weekday] = {
                "caption": caption,
                "hashtags": hashtags,
                "hours": hours if hours else [],
            }
            print(f"[GDrive] Dia {weekday} ({day_name}): {caption[:50]}… | horas={hours}")

        return captions

    # ── Formato A (simples: "Segunda: texto #tags") ──────────
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        day_part, _, text_part = line.partition(":")
        day_key = _normalize(day_part.strip())
        weekday = _DAY_ALIASES.get(day_part.strip().lower()) or _DAY_ALIASES.get(day_key)
        if weekday is None:
            continue
        words = text_part.strip().split()
        hashtags = " ".join(w for w in words if w.startswith("#"))
        caption = " ".join(w for w in words if not w.startswith("#"))
        captions[weekday] = {"caption": caption.strip(), "hashtags": hashtags.strip(), "hours": []}
        print(f"[GDrive] Dia {weekday}: {caption[:50]}…")

    return captions


# ─────────────────────────────────────────────────────────────────────────────
# Service Account (modo completo — requer credentials JSON)
# ─────────────────────────────────────────────────────────────────────────────

def _has_service_account() -> bool:
    return os.path.exists(CREDS_PATH)


def _build_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    creds = service_account.Credentials.from_service_account_file(CREDS_PATH, scopes=scopes)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _import_service_account(client_dir: str, folder_id: str) -> tuple[list[dict], str | None]:
    """
    Importa arquivos via Service Account.
    Retorna (lista_de_arquivos, conteudo_postagens_txt_ou_None).
    """
    try:
        service = _build_service()
    except Exception as e:
        print(f"[GDrive] Service Account erro: {e}")
        return [], None

    query = f"'{folder_id}' in parents and trashed=false"
    try:
        results = service.files().list(
            q=query,
            fields="files(id, name, mimeType)",
            orderBy="name",
            pageSize=200,
        ).execute()
    except Exception as e:
        print(f"[GDrive] Erro ao listar pasta: {e}")
        return [], None

    files = results.get("files", [])
    from googleapiclient.http import MediaIoBaseDownload

    imported = []
    postagens_content = None

    for f in files:
        filename = f.get("name", "")
        mime = f.get("mimeType", "")
        ext = Path(filename).suffix.lower()

        # Ler postagens.txt (aceita "postagens", "postagens.txt", "postagens.md")
        if Path(filename).stem.lower() == "postagens":
            try:
                fh = io.BytesIO()
                req = service.files().get_media(fileId=f["id"])
                dl = MediaIoBaseDownload(fh, req)
                done = False
                while not done:
                    _, done = dl.next_chunk()
                postagens_content = fh.getvalue().decode("utf-8", errors="ignore")
            except Exception as e:
                print(f"[GDrive] Erro ao ler postagens.txt: {e}")
            continue

        if mime not in SUPPORTED_MIME and ext not in SUPPORTED_EXT:
            continue

        dest = os.path.join(client_dir, filename)
        if os.path.exists(dest):
            continue

        try:
            req = service.files().get_media(fileId=f["id"])
            fh = io.FileIO(dest, "wb")
            dl = MediaIoBaseDownload(fh, req)
            done = False
            while not done:
                _, done = dl.next_chunk()
            fh.close()
            weekday = _detect_day_from_filename(filename)
            imported.append({"filename": filename, "filepath": dest, "weekday": weekday})
            print(f"[GDrive] SA baixou: {filename}")
        except Exception as e:
            print(f"[GDrive] Erro ao baixar {filename}: {e}")
            if os.path.exists(dest):
                os.remove(dest)

    return imported, postagens_content


# ─────────────────────────────────────────────────────────────────────────────
# gdown (modo público — pasta com link compartilhado, sem setup)
# ─────────────────────────────────────────────────────────────────────────────

def _import_gdown(client_dir: str, folder_id: str) -> tuple[list[dict], str | None]:
    """
    Importa arquivos via gdown (pasta pública compartilhada).
    Retorna (lista_de_arquivos, conteudo_postagens_txt_ou_None).
    """
    try:
        import gdown
    except ImportError:
        print("[GDrive] gdown não instalado. Execute: pip install gdown>=5.0.0")
        return [], None

    folder_url = f"https://drive.google.com/drive/folders/{folder_id}"

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            print(f"[GDrive] gdown baixando pasta {folder_id}…")
            downloaded = gdown.download_folder(
                url=folder_url,
                output=tmpdir,
                quiet=False,
                use_cookies=False,
                remaining_ok=True,
            )
        except Exception as e:
            print(f"[GDrive] gdown erro: {e}")
            return [], None

        if not downloaded:
            print("[GDrive] gdown: nenhum arquivo baixado.")
            return [], None

        imported = []
        postagens_content = None

        for tmp_path_str in downloaded:
            tmp_path = Path(tmp_path_str)
            filename = tmp_path.name

            # Ler postagens.txt (aceita "postagens", "postagens.txt", "postagens.md")
            if Path(filename).stem.lower() == "postagens":
                try:
                    postagens_content = tmp_path.read_text(encoding="utf-8", errors="ignore")
                    print(f"[GDrive] Lido arquivo de legendas: {filename}")
                except Exception:
                    pass
                continue

            ext = tmp_path.suffix.lower()
            if ext not in SUPPORTED_EXT:
                continue

            dest = os.path.join(client_dir, filename)
            if os.path.exists(dest):
                continue

            try:
                shutil.copy2(tmp_path_str, dest)
                weekday = _detect_day_from_filename(filename)
                imported.append({"filename": filename, "filepath": dest, "weekday": weekday})
                print(f"[GDrive] gdown copiou: {filename}")
            except Exception as e:
                print(f"[GDrive] Erro ao copiar {filename}: {e}")

        return imported, postagens_content


# ─────────────────────────────────────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────────────────────────────────────

def import_from_drive(client_id: int, upload_folder: str, folder_id: str = "") -> list[dict]:
    """
    Baixa arquivos novos da pasta do Drive.
    Tenta Service Account primeiro; cai para gdown se não houver credenciais.
    """
    folder_id = extract_folder_id(folder_id or os.environ.get("GOOGLE_DRIVE_FOLDER_ID", ""))
    if not folder_id:
        return []

    client_dir = os.path.join(upload_folder, str(client_id))
    os.makedirs(client_dir, exist_ok=True)

    if _has_service_account():
        print("[GDrive] Usando Service Account…")
        files, _ = _import_service_account(client_dir, folder_id)
    else:
        print("[GDrive] Service Account não encontrado — usando gdown (pasta pública)…")
        files, _ = _import_gdown(client_dir, folder_id)

    return files


def read_postagens_txt(folder_id: str) -> dict[int, dict]:
    """
    Lê postagens.txt da pasta do Drive.
    Retorna {weekday: {caption, hashtags}}.
    """
    folder_id = extract_folder_id(folder_id)
    if not folder_id:
        return {}

    client_dir = tempfile.mkdtemp()
    try:
        if _has_service_account():
            _, content = _import_service_account(client_dir, folder_id)
        else:
            _, content = _import_gdown(client_dir, folder_id)
    finally:
        shutil.rmtree(client_dir, ignore_errors=True)

    if not content:
        return {}
    return _parse_postagens_txt(content)


def sync_drive(client_id: int, upload_folder: str, folder_id: str) -> tuple[list[dict], dict[int, dict]]:
    """
    Operação combinada: baixa fotos novas E lê postagens.txt em uma única chamada ao Drive.
    Retorna (lista_arquivos_importados, legendas_por_dia).
    """
    folder_id = extract_folder_id(folder_id)
    if not folder_id:
        return [], {}

    client_dir = os.path.join(upload_folder, str(client_id))
    os.makedirs(client_dir, exist_ok=True)

    if _has_service_account():
        print("[GDrive] Sync via Service Account…")
        files, postagens_content = _import_service_account(client_dir, folder_id)
    else:
        print("[GDrive] Sync via gdown (pasta pública)…")
        files, postagens_content = _import_gdown(client_dir, folder_id)

    captions = _parse_postagens_txt(postagens_content) if postagens_content else {}
    return files, captions


def list_drive_files(folder_id: str) -> list[dict]:
    """Lista arquivos para preview no dashboard."""
    folder_id = extract_folder_id(folder_id)
    if not folder_id:
        return []

    if not _has_service_account():
        return [{"name": "(lista disponível apenas com Service Account)", "mimeType": ""}]

    try:
        service = _build_service()
        query = f"'{folder_id}' in parents and trashed=false and (mimeType contains 'image/' or mimeType contains 'video/')"
        results = service.files().list(
            q=query,
            fields="files(id, name, mimeType, size)",
            orderBy="name",
            pageSize=50,
        ).execute()
        return results.get("files", [])
    except Exception as e:
        print(f"[GDrive] Erro ao listar: {e}")
        return []
