"""
Bot de Telegram para descargar archivos de Mega.nz y Mediafire (Soporta hasta 2GB).
Permite acumular múltiples enlaces en una lista y procesarlos en lote mediante botones interactivos.
Genera miniaturas dinámicas (segundo 5) e incluye barra de progreso en tiempo real.
"""

import os
import time
import logging
import threading
import ffmpeg

from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

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

# --- Almacenamiento Temporal en Memoria ---
user_queues = {}

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
async def progress_bar(current, total, status_msg, start_time, current_index, total_links):
    now = time.time()
    elapsed_time = now - start_time
    
    if hasattr(status_msg, "last_update_time"):
        if now - status_msg.last_update_time < 3.0:
            return
    status_msg.last_update_time = now

    if total == 0:
        return

    percentage = (current / total) * 100
    speed_bps = current / elapsed_time if elapsed_time > 0 else 0
    speed_mbps = speed_bps / (1024 * 1024)
    
    current_mb = current / (1024 * 1024)
    total_mb = total / (1024 * 1024)

    completed_blocks = int(percentage // 10)
    remaining_blocks = 10 - completed_blocks
    bar = "■" * completed_blocks + "□" * remaining_blocks

    progress_text = (
        f"⚡ **Subiendo a Telegram... [Archivo {current_index}/{total_links}]**\n\n"
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
    user_id = message.from_user.id
    if user_id in user_queues:
        user_queues[user_id].clear()
    await message.reply_text(
        "¡Hola! Mandame un link de Mega.nz o Mediafire y lo iré guardando en tu lista. "
        "Cuando termines de pasarme todos los links, presiona el botón para iniciar la descarga masiva."
    )

# Filtro personalizado: Acepta texto pero ignora comandos
filter_text_no_command = filters.text & filters.create(lambda _, __, msg: msg.text and not msg.text.startswith("/"))

@bot.on_message(filter_text_no_command)
async def handle_link(client: Client, message: Message):
    url = message.text.strip()
    link_type = detect_link_type(url)

    if link_type is None:
        await message.reply_text(
            "No reconozco ese link. Mandame uno válido de Mega.nz o Mediafire."
        )
        return

    user_id = message.from_user.id
    
    if user_id not in user_queues:
        user_queues[user_id] = []
        
    user_queues[user_id].append(url)
    total_guardados = len(user_queues[user_id])

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ Añadir más links", callback_data="add_more"),
            InlineKeyboardButton("▶️ Iniciar Descargas", callback_data="start_download")
        ]
    ])

    await message.reply_text(
        f"📥 **¡Enlace guardado exitosamente!**\n"
        f"Llevas `{total_guardados}` enlace(s) acumulado(s) en tu lista de espera.\n\n"
        f"¿Qué deseas hacer ahora?",
        reply_markup=keyboard
    )

@bot.on_callback_query()
async def handle_buttons(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data

    if data == "add_more":
        await callback_query.answer("Listo, envíame el siguiente enlace.")
        await callback_query.message.edit_text(
            f"Sigo guardando tus enlaces. Actualmente tienes `{len(user_queues.get(user_id, []))}` en cola.\n"
            "Mándame otro link cuando quieras."
        )
        return

    if data == "start_download":
        queue = user_queues.get(user_id, [])
        
        if not queue:
            await callback_query.answer("No tienes enlaces en tu lista.", show_alert=True)
            await callback_query.message.edit_text("Tu lista está vacía. Envíame un enlace para empezar.")
            return

        await callback_query.answer("Iniciando procesamiento por lotes...")
        status_msg = await callback_query.message.edit_text("Iniciando la descarga de tu lista, por favor espera...")
        
        total_links = len(queue)
        
        for index, url in enumerate(list(queue), start=1):
            link_type = detect_link_type(url)
            thumb_path = f"thumb_{int(time.time())}.jpg"
            file_path = None
            
            try:
                await status_msg.edit_text(f"⏳ **[{index}/{total_links}]** Descargando del servidor externo...")
                
                if link_type == "mega":
                    file_path = download_mega(url)
                else:
                    file_path = download_mediafire(url)

                size_mb = get_file_size_mb(file_path)

                if size_mb > MAX_TELEGRAM_MB:
                    await callback_query.message.reply_text(
                        f"❌ El archivo {index} pesa {size_mb:.1f}MB y supera el límite permitido de {MAX_TELEGRAM_MB}MB. "
                        f"Se omitirá este enlace."
                    )
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    continue

                await status_msg.edit_text(f"🔍 **[{index}/{total_links}]** Analizando formato y extrayendo miniatura...")

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

                    seek_time = "00:00:05" if vid_duration >= 5 else "00:00:00"

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
                    logger.warning(f"Error procesando multimedia: {fe}")

                await status_msg.edit_text(f"📤 **[{index}/{total_links}]** Preparando conexión para la subida...")

                start_upload_time = time.time()
                
                await callback_query.message.reply_video(
                    video=file_path, 
                    duration=vid_duration, 
                    width=vid_width, 
                    height=vid_height,
                    thumb=thumb_path if has_thumb else None,
                    supports_streaming=True,
                    progress=progress_bar,
                    progress_args=(status_msg, start_upload_time, index, total_links)
                )

            except Exception as e:
                logger.exception(f"Error procesando enlace {url}")
                await callback_query.message.reply_text(f"❌ Error al procesar el archivo {index}: {e}")
                
            finally:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
                if os.path.exists(thumb_path):
                    os.remove(thumb_path)

        user_queues[user_id].clear()
        await status_msg.edit_text("✅ ¡Todos los archivos de tu lista han sido procesados y enviados exitosamente!")

def main():
    threading.Thread(target=run_web, daemon=True).start()
    logger.info("Bot iniciado con Pyrogram (Modo Cola Activo), escuchando mensajes...")
    bot.run()

if __name__ == "__main__":
    main()
