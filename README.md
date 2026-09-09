# Bot de Telegram - Descargas de Mega y Mediafire

Bot que recibe un link de Mega.nz o Mediafire, descarga el archivo y te lo manda por Telegram.

## Limitación importante

Telegram solo permite que un bot **envíe archivos de hasta 50MB**. Si el archivo pesa
más, el bot te avisa pero no lo puede mandar por ese medio.

## 1. Crear el bot en Telegram

1. Hablá con [@BotFather](https://t.me/BotFather) en Telegram.
2. Mandale `/newbot` y seguí los pasos.
3. Te va a dar un **token** (algo como `123456:ABC-DEF...`). Guardalo, es tu `BOT_TOKEN`.

## 2. Subir el proyecto a GitHub

```bash
cd telegram-mega-bot
git init
git add .
git commit -m "Bot inicial de Mega/Mediafire"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git push -u origin main
```

## 3. Probarlo local (opcional, antes de subirlo)

```bash
pip install -r requirements.txt
cp .env.example .env   # y poné tu token ahí
export $(cat .env | xargs)   # en Windows: usar variables de entorno del sistema
python bot.py
```

## 4. Desplegar en Render (gratis)

1. Entrá a [render.com](https://render.com) y creá una cuenta (podés usar GitHub para loguearte).
2. Click en **New +** → **Web Service**.
3. Conectá tu repositorio de GitHub.
4. Render va a detectar el `render.yaml` automáticamente. Si no, configurá:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
5. En **Environment Variables**, agregá:
   - `BOT_TOKEN` = el token que te dio BotFather
6. Deploy. Cuando termine, el bot va a quedar escuchando mensajes.

## 5. Que no se "duerma" (plan free)

Render free apaga el servicio tras ~15 min sin tráfico HTTP. Como el bot igual
tiene una URL web (por el mini servidor Flask incluido), podés usar un servicio
gratuito como [UptimeRobot](https://uptimerobot.com) para que le pegue a esa URL
cada 5-10 minutos y lo mantenga despierto. Si no te importa "prenderlo" a mano
(entrando a la URL cuando lo vayas a usar), también funciona sin esto.

## Estructura del proyecto

```
telegram-mega-bot/
├── bot.py            # Bot principal + servidor Flask
├── downloader.py     # Lógica de descarga de Mega y Mediafire
├── requirements.txt
├── render.yaml
├── .env.example
└── .gitignore
```
