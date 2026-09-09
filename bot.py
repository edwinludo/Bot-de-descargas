"""
Bot de Telegram para descargar archivos de Mega.nz y Mediafire (Soporta hasta 2GB).
Corre un mini servidor Flask en paralelo para mantener vivo el servicio en Render (plan free).
Extrae metadatos automáticamente para corregir la miniatura y el tiempo de reproducción.
"""

import os
import logging
import threading
import ffmpeg

from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message

from downloader import detect_link_type, download_mega, download_mediafire, get_file_size_mb

# --- Configuración del Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- Configuración de Credenciales ---
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Límite nativo de Telegram para aplicaciones/clientes es de 2000 MB (2GB)
MAX_TELEGRAM_MB = 1990  

# --- Servidor Flask de mantenimiento (para Render) ---
web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "Bot activo."

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# --- Inicialización del Cliente Pyrogram ---
if not all([API_ID, API_HASH, BOT_TOKEN]):
    raise RuntimeError("Faltan variables de entorno esenciales (API_ID, API_HASH o BOT_TOKEN)")

bot = Client(
    "mega_mediafire_bot",
    api_id=int(API_ID),
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# --- Handlers del bot ---
@bot.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply_text(
        "¡Hola! Mandame un link de Mega.nz o Mediafire y te lo descargo como video con miniatura."
    )

# Filtro personalizado: Acepta texto pero ignora mensajes que inicien con '/' (comandos)
filter_text_no_command = filters.text & filters.create(lambda _, __, msg: msg.text and not msg.text.startswith("/"))

@bot.on_message(filter_text_no_command)
async def handle_link(client: Client, message: Message):
    url = message.text.strip()
    link_type = detect_link_type(url)

    if link_type is None:
        await message.reply_text(
            "No reconozco ese link. Mandame uno de Mega.nz o Mediafire."
        )
        return

    status_msg = await message.reply_text("Descargando el archivo, un momento...")

    try:
        if link_type == "mega":
            file_path = download_mega(url)
        else:
            file_path = download_mediafire(url)

        size_mb = get_file_size_mb(file_path)

        if size_mb > MAX_TELEGRAM_MB:
            await status_msg.edit_text(
                f"El archivo pesa {size_mb:.1f}MB y supera el límite de Telegram "
                f"({MAX_TELEGRAM_MB}MB) para enviarlo. No lo puedo mandar por acá."
            )
            if os.path.exists(file_path):
                os.remove(file_path)
            return

        await status_msg.edit_text("Analizando metadatos del video para la miniatura...")

        # --- Extraer duración y dimensiones con FFmpeg ---
        vid_duration = 0
        vid_width = 320
        vid_height = 320
        
        try:
            metadata = ffmpeg.probe(file_path)
            video_stream = next((stream for stream in metadata['streams'] if stream['codec_type'] == 'video'), None)
            
            if video_stream:
                vid_width = int(video_stream.get('width', 320))
                vid_height = int(video_stream.get('height', 320))
                # Busca la duración en la pista de video o en la información del formato
                duration_str = video_stream.get('duration') or metadata.get('format', {}).get('duration')
                if duration_str:
                    vid_duration = int(float(duration_str))
        except Exception as fe:
            logger.warning(f"No se pudieron extraer los metadatos de video: {fe}")

        await status_msg.edit_text("Descarga lista, subiendo a Telegram...")

        # Enviamos como video inyectando la duración y dimensiones calculadas por ffmpeg
        await message.reply_video(
            video=file_path, 
            duration=vid_duration, 
            width=vid_width, 
            height=vid_height,
            supports_streaming=True
        )

        await status_msg.delete()
        if os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:
        logger.exception("Error al procesar el link")
        await status_msg.edit_text(f"Ocurrió un error al descargar o subir: {e}")

def main():
    # Arrancar el servidor Flask en un hilo aparte para Render
    threading.Thread(target=run_web, daemon=True).start()

    logger.info("Bot iniciado con Pyrogram, escuchando mensajes...")
    bot.run()

if __name__ == "__main__":
    main()
