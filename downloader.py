"""
Funciones para descargar archivos desde Mega.nz y Mediafire.
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


def download_mega(url: str) -> str:
    """
    Descarga un archivo público de Mega.nz.
    Devuelve la ruta local del archivo descargado.
    """
    mega = Mega()
    m = mega.login_anonymous()
    file_path = m.download_url(url, dest_path=DOWNLOAD_DIR)
    return str(file_path)


def download_mediafire(url: str) -> str:
    """
    Descarga un archivo público de Mediafire.
    Mediafire no tiene API pública, así que se scrapea el botón de descarga.
    Devuelve la ruta local del archivo descargado.
    """
    session = requests.Session()
    resp = session.get(url, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    download_button = soup.find("a", {"id": "downloadButton"})

    if not download_button or not download_button.get("href"):
        raise ValueError("No se pudo encontrar el enlace directo de descarga en Mediafire.")

    direct_link = download_button["href"]
    filename = direct_link.split("/")[-1].split("?")[0]
    dest_path = os.path.join(DOWNLOAD_DIR, filename)

    with session.get(direct_link, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    return dest_path


def get_file_size_mb(file_path: str) -> float:
    return os.path.getsize(file_path) / (1024 * 1024)
