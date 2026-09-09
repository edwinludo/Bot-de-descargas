"""
Bot de Telegram para descargar archivos de Mega.nz y Mediafire (Soporta hasta 2GB).
Corre un mini servidor Flask en paralelo para mantener vivo el servicio en Render (plan free).
"""

import os
import logging
import threading

from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import Message

from downloader import detect_link_type, download_mega, download_mediafire, get_file_size_mb

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
        "¡Hola! Mandame un link de Mega.nz o Mediafire y te lo descargo (Soporto hasta 2GB)."
    )

@bot.on_message(filters.text & ~filters.command)
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

        await status_msg.edit_text("Descarga lista, subiendo a Telegram...")

        # Pyrogram maneja la subida en partes de forma automática
        await message.reply_document(document=file_path)

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
