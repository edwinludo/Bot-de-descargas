"""
Bot de Telegram para descargar archivos de Mega.nz y Mediafire (Soporta hasta 2GB).
Optimizado para Render usando almacenamiento de sesión en disco y servidor web Waitress.
"""

import os
import time
import logging
import threading
import asyncio
import ffmpeg

from flask import Flask
from waitress import serve
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from downloader import detect_link_type, download_mega, download_mediafire, get_file_size_mb

# --- Configuración del Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MAX_TELEGRAM_MB = 1990  

user_queues = {}

# --- Servidor Flask de mantenimiento ---
web_app = Flask(__name__)

@web_app.route("/")
def home():
    return "Bot activo."

def run_web():
    port = int(os.environ.get("PORT", 8080))
    # Usamos Waitress en lugar de web_app.run() para evitar bloqueos de hilos
    serve(web_app, host="0.0.0.0", port=port)

if not all([API_ID, API_HASH, BOT_TOKEN]):
    raise RuntimeError("Faltan variables de entorno esenciales (API_ID, API_HASH o BOT_TOKEN)")

# --- OPTIMIZACIÓN: Guardar la sesión en el disco temporal de Render ---
# Esto evita que Telegram pida autenticación en cada reinicio
session_path = os.path.join("/tmp", "mega_mediafire_bot")

bot = Client(
    session_path,
    api_id=int(API_ID),
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# --- Función para generar cualquier barra de progreso visual ---
def make_progress_text(current, total, start_time, title_mode, current_index, total_links):
    now = time.time()
    elapsed_time = now - start_time
    percentage = (current / total) * 100 if total > 0 else 0
    speed_mbps = (current / elapsed_time / (1024 * 1024)) if elapsed_time > 0 else 0
    
    current_mb = current / (1024 * 1024)
    total_mb = total / (1024 * 1024)

    completed_blocks = int(percentage // 10)
    remaining_blocks = 10 - completed_blocks
    bar = "■" * completed_blocks + "□" * remaining_blocks

    return (
        f"{title_mode} **[Archivo {current_index}/{total_links}]**\n"
        f"🎬 **Video Actual:** No. {current_index}\n\n"
        f"|{bar}| `{percentage:.1f}%`\n"
        f"📦 **Procesado:** {current_mb:.1f} MB / {total_mb:.1f} MB\n"
        f"🚀 **Velocidad:** {speed_mbps:.2f} MB/s"
    )

# --- Callback para la Subida a Telegram ---
async def upload_progress(current, total, status_msg, start_time, current_index, total_links):
    now = time.time()
    if hasattr(status_msg, "last_update_time"):
        if now - status_msg.last_update_time < 3.0:
            return
    status_msg.last_update_time = now

    progress_text = make_progress_text(
        current, total, start_time, "📤 **Subiendo a Telegram...**", current_index, total_links
    )
    try:
        await status_msg.edit_text(progress_text)
    except Exception:
        pass

# --- Handlers del bot ---
@bot.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id in user_queues:
        user_queues[user_id].clear()
    await message.reply_text(
        "¡Hola! Mandame un link de Mega.nz o Mediafire y lo iré guardando.\n"
        "Se renombrarán automáticamente en orden matemático (Video 1, Video 2...)."
    )

filter_text_no_command = filters.text & filters.create(lambda _, __, msg: msg.text and not msg.text.startswith("/"))

@bot.on_message(filter_text_no_command)
async def handle_link(client: Client, message: Message):
    url = message.text.strip()
    link_type = detect_link_type(url)

    if link_type is None:
        await message.reply_text("No reconozco ese link. Mandame uno válido de Mega.nz o Mediafire.")
        return

    user_id = message.from_user.id
    if user_id not in user_queues:
        user_queues[user_id] = []
        
    user_queues[user_id].append(url)
    total_guardados = len(user_queues[user_id])

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Añadir más", callback_data="add_more"),
            InlineKeyboardButton("▶️ Iniciar Descargas", callback_data="start_download")
        ]
    ])

    await message.reply_text(
        f"📥 **¡Enlace guardado en la posición {total_guardados}!**\n"
        f"Se procesará con el nombre de: `Video {total_guardados}`\n\n"
        f"¿Qué deseas hacer ahora?",
        reply_markup=keyboard
    )

@bot.on_callback_query()
async def handle_buttons(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    if data == "add_more":
        await callback_query.answer("Envíame el siguiente enlace.")
        await callback_query.message.edit_text(
            f"Sigo guardando tus enlaces. Actualmente tienes `{len(user_queues.get(user_id, []))}` en cola."
        )
        return

    if data == "start_download":
        queue = user_queues.get(user_id, [])
        if not queue:
            await callback_query.answer("No tienes enlaces en tu lista.", show_alert=True)
            return

        await callback_query.answer("Iniciando descargas en lote...")
        status_msg = await callback_query.message.edit_text("Preparando entorno de descarga...")
        
        total_links = len(queue)
        loop = asyncio.get_event_loop()
        
        for index, url in enumerate(list(queue), start=1):
            link_type = detect_link_type(url)
            thumb_path = f"thumb_{int(time.time())}.jpg"
            file_path = None
            custom_name = f"Video {index}"
            
            start_download_time = time.time()
            last_edit = [time.time()]
            
            def download_callback(current, total):
                now = time.time()
                if now - last_edit[0] >= 3.0:
                    last_edit[0] = now
                    txt = make_progress_text(current, total, start_download_time, "⏳ **Descargando al Servidor...**", index, total_links)
                    asyncio.run_coroutine_threadsafe(status_msg.edit_text(txt), loop)

            try:
                if link_type == "mediafire":
                    file_path = download_mediafire(url, progress_callback=download_callback, custom_filename=custom_name)
                else:
                    await status_msg.edit_text(f"⏳ **[{index}/{total_links}]** Descargando `{custom_name}` desde Mega... (Espera un momento)")
                    file_path = download_mega(url, custom_filename=custom_name)

                size_mb = get_file_size_mb(file_path)
                if size_mb > MAX_TELEGRAM_MB:
                    await callback_query.message.reply_text(f"❌ `{custom_name}` supera el límite permitido ({MAX_TELEGRAM_MB}MB) y será omitido.")
                    if os.path.exists(file_path): os.remove(file_path)
                    continue

                await status_msg.edit_text(f"🔍 **[{index}/{total_links}]** Extrayendo miniatura de `{custom_name}`...")

                vid_duration, vid_width, vid_height, has_thumb = 0, 320, 320, False
                try:
                    metadata = ffmpeg.probe(file_path)
                    video_stream = next((stream for stream in metadata['streams'] if stream['codec_type'] == 'video'), None)
                    if video_stream:
                        vid_width = int(video_stream.get('width', 320))
                        vid_height = int(video_stream.get('height', 320))
                        duration_str = video_stream.get('duration') or metadata.get('format', {}).get('duration')
                        if duration_str: vid_duration = int(float(duration_str))

                    seek_time = "00:00:05" if vid_duration >= 5 else "00:00:00"
                    ffmpeg.input(file_path, ss=seek_time).output(thumb_path, vframes=1, **{'q:v': 2}).overwrite_output().run(capture_stdout=True, capture_stderr=True)
                    if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0: has_thumb = True
                except Exception as fe:
                    logger.warning(f"Error multimedia: {fe}")

                await status_msg.edit_text(f"📤 **[{index}/{total_links}]** Conectando con Telegram...")
                
                start_upload_time = time.time()
                await callback_query.message.reply_video(
                    video=file_path, 
                    duration=vid_duration, 
                    width=vid_width, 
                    height=vid_height,
                    thumb=thumb_path if has_thumb else None,
                    supports_streaming=True,
                    caption=f"🎬 **{custom_name}**\n📦 Tamaño: {size_mb:.1f} MB",
                    progress=upload_progress,
                    progress_args=(status_msg, start_upload_time, index, total_links)
                )

            except Exception as e:
                logger.exception(f"Error en {url}")
                await callback_query.message.reply_text(f"❌ Error al procesar `{custom_name}`: {e}")
                
            finally:
                if file_path and os.path.exists(file_path): os.remove(file_path)
                if os.path.exists(thumb_path): os.remove(thumb_path)

        user_queues[user_id].clear()
        await status_msg.edit_text("✅ ¡Todos los archivos han sido renombrados, descargados y enviados exitosamente!")

def main():
    threading.Thread(target=run_web, daemon=True).start()
    logger.info("Bot iniciado con Pyrogram, escuchando mensajes...")
    
    try:
        bot.run()
    except Exception as e:
        logger.error(f"Error en ejecución: {e}")
        time.sleep(10)

if __name__ == "__main__":
    main()
