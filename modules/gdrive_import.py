"""
Google Drive Import — Importa fotos de uma pasta do Drive para o painel.
Requer: pip install google-api-python-client google-auth-oauthlib
Configurar: GOOGLE_DRIVE_FOLDER_ID no .env
"""

import os
import io
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def import_from_drive(client_id: int, upload_folder: str) -> list[dict]:
    """
    Baixa novas imagens de uma pasta do Google Drive.
    Retorna lista de dicts com {filename, filepath}.
    """
    api_key = os.environ.get("GOOGLE_API_KEY")
    folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")

    if not api_key or not folder_id:
        return []

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError:
        print("google-api-python-client não instalado. pip install google-api-python-client")
        return []

    service = build("drive", "v3", developerKey=api_key)

    # Listar arquivos de imagem na pasta
    query = f"'{folder_id}' in parents and mimeType contains 'image/' and trashed=false"
    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType, createdTime)",
        orderBy="createdTime desc",
        pageSize=50,
    ).execute()

    files = results.get("files", [])
    if not files:
        return []

    client_dir = os.path.join(upload_folder, str(client_id))
    os.makedirs(client_dir, exist_ok=True)

    imported = []
    for f in files:
        filename = f["name"]
        dest = os.path.join(client_dir, filename)

        # Pular se já existe
        if os.path.exists(dest):
            continue

        try:
            request = service.files().get_media(fileId=f["id"])
            fh = io.FileIO(dest, "wb")
            downloader = MediaIoBaseDownload(fh, request)

            done = False
            while not done:
                _, done = downloader.next_chunk()

            imported.append({"filename": filename, "filepath": dest})
        except Exception as e:
            print(f"Erro ao baixar {filename}: {e}")
            if os.path.exists(dest):
                os.remove(dest)

    return imported
