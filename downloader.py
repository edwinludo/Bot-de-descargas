"""
Funciones asíncronas para descargar archivos desde Mega.nz y Mediafire.
"""

import os
import re
import aiohttp
from bs4 import BeautifulSoup
from mega import Mega

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MEGA_REGEX = re.compile(r"https?://mega\.nz/\S+", re.IGNORECASE)
MEDIAFIRE_REGEX = re.compile(r"https?://(www\.)?mediafire\.com/\S+", re.IGNORECASE)


def detect_link_type(url: str) -> str:
    if MEGA_REGEX.search(url):
        return "mega"
    if MEDIAFIRE_REGEX.search(url):
        return "mediafire"
    return None


async def download_mega_async(url: str, custom_filename: str = None) -> str:
    """Descarga de Mega (usa la librería estándar en un bloque ejecutor seguro)"""
    mega = Mega()
    m = mega.login_anonymous()
    file_path = m.download_url(url, dest_path=DOWNLOAD_DIR)
    
    if custom_filename:
        ext = os.path.splitext(file_path)[1] if "." in file_path else ".mp4"
        new_path = os.path.join(DOWNLOAD_DIR, f"{custom_filename}{ext}")
        os.rename(file_path, new_path)
        return new_path
    return str(file_path)


async def download_mediafire_async(url: str, progress_callback=None, custom_filename: str = None) -> str:
    """Descarga de Mediafire de forma 100% asíncrona sin bloquear el bot."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, timeout=30) as resp:
            resp.raise_for_status()
            html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        download_button = soup.find("a", {"id": "downloadButton"})

        if not download_button or not download_button.get("href"):
            raise ValueError("No se pudo encontrar el enlace directo de descarga en Mediafire.")

        direct_link = download_button["href"]
        
        if custom_filename:
            original_name = direct_link.split("/")[-1].split("?")[0]
            ext = os.path.splitext(original_name)[1] if "." in original_name else ".mp4"
            filename = f"{custom_filename}{ext}"
        else:
            filename = direct_link.split("/")[-1].split("?")[0]
            
        dest_path = os.path.join(DOWNLOAD_DIR, filename)

        async with session.get(direct_link, timeout=60) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            bytes_downloaded = 0
            
            with open(dest_path, "wb") as f:
                async for chunk in r.content.iter_chunked(65536):
                    if chunk:
                        f.write(chunk)
                        bytes_downloaded += len(chunk)
                        if progress_callback and total_size > 0:
                            # Al ser asíncrono, podemos llamar al progreso directamente
                            await progress_callback(bytes_downloaded, total_size)

    return dest_path


def get_file_size_mb(file_path: str) -> float:
    return os.path.getsize(file_path) / (1024 * 1024)
