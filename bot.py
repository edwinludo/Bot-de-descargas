"""
Bot de Telegram para descargar archivos de Mega.nz y Mediafire.

Corre un mini servidor Flask en paralelo porque Render (plan free) exige
que el servicio abra un puerto para considerarlo "vivo".
"""

import os
import logging
import threading

from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

from downloader import detect_link_type, download_mega, download_mediafire, get_file_size_mb

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
MAX_TELEGRAM_MB = 49  # límite real de Telegram Bot API es 50MB, dejamos margen

# --- Servidor Flask de mantenimiento (para Render) ---
web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "Bot activo."


def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)


# --- Handlers del bot ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "¡Hola! Mandame un link de Mega.nz o Mediafire y te lo descargo."
    )


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    link_type = detect_link_type(url)

    if link_type is None:
        await update.message.reply_text(
            "No reconozco ese link. Mandame uno de Mega.nz o Mediafire."
        )
        return

    status_msg = await update.message.reply_text("Descargando el archivo, un momento...")

    try:
        if link_type == "mega":
            file_path = download_mega(url)
        else:
            file_path = download_mediafire(url)

        size_mb = get_file_size_mb(file_path)

        if size_mb > MAX_TELEGRAM_MB:
            await status_msg.edit_text(
                f"El archivo pesa {size_mb:.1f}MB y supera el límite de Telegram "
                f"({MAX_TELEGRAM_MB}MB) para que el bot lo pueda enviar. "
                "No lo puedo mandar por acá."
            )
            os.remove(file_path)
            return

        await status_msg.edit_text("Descarga lista, subiendo a Telegram...")

        with open(file_path, "rb") as f:
            await update.message.reply_document(document=f)

        await status_msg.delete()
        os.remove(file_path)

    except Exception as e:
        logger.exception("Error al procesar el link")
        await status_msg.edit_text(f"Ocurrió un error al descargar: {e}")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("Falta la variable de entorno BOT_TOKEN")

    # Arrancar el servidor Flask en un hilo aparte
    threading.Thread(target=run_web, daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    logger.info("Bot iniciado, escuchando mensajes...")
    application.run_polling()


if __name__ == "__main__":
    main()
