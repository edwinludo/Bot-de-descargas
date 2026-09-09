"""
Funciones para descargar archivos desde Mega.nz y Mediafire con soporte de progreso.
"""

import os
import re
import requests
from bs4 import BeautifulSoup
from mega import Mega

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MEGA_REGEX = re.compile(r"https?://mega\.nz/\S+", re.IGNORECASE)
MEDIAFIRE_REGEX = re.compile(r"https?://(www\.)?mediafire\.com/\S+", re.IGNORECASE)


def detect_link_type(url: str) -> str:
    """Devuelve 'mega', 'mediafire' o None según el link recibido."""
    if MEGA_REGEX.search(url):
        return "mega"
    if MEDIAFIRE_REGEX.search(url):
        return "mediafire"
    return None


def download_mega(url: str, custom_filename: str = None) -> str:
    """Descarga un archivo público de Mega.nz."""
    mega = Mega()
    m = mega.login_anonymous()
    
    # mega.py descarga de forma directa y bloqueante en una sola función
    file_path = m.download_url(url, dest_path=DOWNLOAD_DIR)
    
    # Si se pide renombrar para mantener el orden (ej. Video_1.mp4)
    if custom_filename:
        ext = os.path.splitext(file_path)[1] or ".mp4"
        new_path = os.path.join(DOWNLOAD_DIR, f"{custom_filename}{ext}")
        os.rename(file_path, new_path)
        return new_path
        
    return str(file_path)


def download_mediafire(url: str, progress_callback=None, custom_filename: str = None) -> str:
    """Descarga un archivo de Mediafire reportando el progreso de descarga."""
    session = requests.Session()
    resp = session.get(url, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    download_button = soup.find("a", {"id": "downloadButton"})

    if not download_button or not download_button.get("href"):
        raise ValueError("No se pudo encontrar el enlace directo de descarga en Mediafire.")

    direct_link = download_button["href"]
    
    if custom_filename:
        ext = os.path.splitext(direct_link.split("/")[-1].split("?")[0])[1] or ".mp4"
        filename = f"{custom_filename}{ext}"
    else:
        filename = direct_link.split("/")[-1].split("?")[0]
        
    dest_path = os.path.join(DOWNLOAD_DIR, filename)

    with session.get(direct_link, stream=True, timeout=60) as r:
        r.raise_for_status()
        total_size = int(r.headers.get('content-length', 0))
        bytes_downloaded = 0
        
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    bytes_downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        # Invoca la función asíncrona de progreso adaptada para hilos si es necesario
                        progress_callback(bytes_downloaded, total_size)

    return dest_path


def get_file_size_mb(file_path: str) -> float:
    return os.path.getsize(file_path) / (1024 * 1024)
