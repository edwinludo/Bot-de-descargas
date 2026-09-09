"""
Bot de Telegram para descargar archivos de Mega.nz y Mediafire (Soporta hasta 2GB).
Genera miniaturas a partir del segundo 5 del video para evitar pantallas negras.
Incluye una barra de progreso dinámica con velocidad de subida en tiempo real.
"""

import os
import time
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

# --- Función Callback para la Barra de Progreso ---
async def progress_bar(current, total, status_msg, start_time):
    now = time.time()
    elapsed_time = now - start_time
    
    # Evitar actualizar el mensaje excesivamente (máximo una vez cada 3 segundos)
    # para cumplir con los límites de peticiones (Rate Limits) de Telegram
    if hasattr(status_msg, "last_update_time"):
        if now - status_msg.last_update_time < 3.0:
            return
    status_msg.last_update_time = now

    if total == 0:
        return

    percentage = (current / total) * 100
    
    # Calcular velocidad (Bytes por segundo -> MB/s)
    speed_bps = current / elapsed_time if elapsed_time > 0 else 0
    speed_mbps = speed_bps / (1024 * 1024)
    
    current_mb = current / (1024 * 1024)
    total_mb = total / (1024 * 1024)

    # Construcción visual de la barra de progreso
    completed_blocks = int(percentage // 10)
    remaining_blocks = 10 - completed_blocks
    bar = "■" * completed_blocks + "□" * remaining_blocks

    progress_text = (
        f"⚡ **Subiendo archivo a Telegram...**\n\n"
        f"|{bar}| `{percentage:.1f}%`\n"
        f"📦 **Procesado:** {current_mb:.1f} MB / {total_mb:.1f} MB\n"
        f"🚀 **Velocidad:** {speed_mbps:.2f} MB/s"
    )

    try:
        await status_msg.edit_text(progress_text)
    except Exception:
        pass

# --- Handlers del bot ---
@bot.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply_text(
        "¡Hola! Mandame un link de Mega.nz o Mediafire y te lo descargo como video con miniatura."
    )

# Filtro personalizado: Acepta texto pero ignora comandos
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

    # Definimos la ruta de la miniatura temporal fuera del try para asegurar su limpieza
    thumb_path = f"thumb_{int(time.time())}.jpg"

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

        await status_msg.edit_text("Analizando metadatos del video y generando miniatura...")

        # --- Extraer duración, dimensiones y miniatura (segundo 5) con FFmpeg ---
        vid_duration = 0
        vid_width = 320
        vid_height = 320
        has_thumb = False
        
        try:
            metadata = ffmpeg.probe(file_path)
            video_stream = next((stream for stream in metadata['streams'] if stream['codec_type'] == 'video'), None)
            
            if video_stream:
                vid_width = int(video_stream.get('width', 320))
                vid_height = int(video_stream.get('height', 320))
                duration_str = video_stream.get('duration') or metadata.get('format', {}).get('duration')
                if duration_str:
                    vid_duration = int(float(duration_str))

            # Si el video dura más de 5 segundos, tomamos el fotograma del segundo 5; si no, del segundo 0
            seek_time = "00:00:05" if vid_duration >= 5 else "00:00:00"

            # Comando FFmpeg para extraer 1 único fotograma en alta calidad congelado en el tiempo designado
            (
                ffmpeg
                .input(file_path, ss=seek_time)
                .output(thumb_path, vframes=1, **{'q:v': 2})
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
                has_thumb = True

        except Exception as fe:
            logger.warning(f"No se pudieron extraer los metadatos o la miniatura: {fe}")

        await status_msg.edit_text("Descarga lista, preparando envío...")

        # --- Envío del Video con Barra de Progreso y Miniatura ---
        start_upload_time = time.time()
        
        await message.reply_video(
            video=file_path, 
            duration=vid_duration, 
            width=vid_width, 
            height=vid_height,
            thumb=thumb_path if has_thumb else None, # Inyección de la miniatura JPG del segundo 5
            supports_streaming=True,
            progress=progress_bar,  # Función callback vinculada
            progress_args=(status_msg, start_upload_time) # Argumentos pasados al callback
        )

        await status_msg.delete()

    except Exception as e:
        logger.exception("Error al procesar el link")
        await status_msg.edit_text(f"Ocurrió un error al descargar o subir: {e}")
        
    finally:
        # Limpieza absoluta de archivos locales para cuidar el almacenamiento efímero de Render
        if 'file_path' in locals() and os.path.exists(file_path):
            os.remove(file_path)
        if os.path.exists(thumb_path):
            os.remove(thumb_path)

def main():
    # Arrancar el servidor Flask en un hilo aparte para Render
    threading.Thread(target=run_web, daemon=True).start()

    logger.info("Bot iniciado con Pyrogram, escuchando mensajes...")
    bot.run()

if __name__ == "__main__":
    main()
