import os
import asyncio
import glob
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from dotenv import load_dotenv
from pyrogram import Client, filters
from pytgcalls import PyTgCalls
from pytgcalls.types import AudioQuality, MediaStream

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SESSION_STRING = os.getenv("SESSION_STRING")

app = Client(
    "music_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

if SESSION_STRING:
    user_app = Client(
        "music_assistant",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING
    )
else:
    user_app = Client(
        "music_assistant",
        api_id=API_ID,
        api_hash=API_HASH
    )

call_py = PyTgCalls(user_app)

queues = {}
current_song = {}

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()


def cleanup_downloads():
    for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
        try:
            os.remove(f)
        except Exception:
            pass

async def search_and_download(query):
    import yt_dlp
    import os
    import glob
    import shutil

    cookie_path = os.path.join(DOWNLOAD_DIR, "cookies.txt")

    if os.path.exists("/etc/secrets/cookies.txt"):
        shutil.copyfile("/etc/secrets/cookies.txt", cookie_path)

  opts = {
    "extractor_args": {
        "youtube": {
            "player_client": ["default", "web_embedded"],
            "player_skip": ["webpage"]
        }
    }
}

    if os.path.exists(cookie_path):
        opts["cookiefile"] = cookie_path

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            f"ytsearch1:{query}",
            download=True
        )

    if not info or not info.get("entries"):
        return None

    video = info["entries"][0]
    video_id = video["id"]
    title = video.get("title", query)

    files = glob.glob(
        os.path.join(DOWNLOAD_DIR, f"{video_id}.*")
    )

    if not files:
        return None
    current_song[chat_id] = song
    await call_py.play(
        chat_id,
        MediaStream(song["file"], AudioQuality.HIGH)
    )


@app.on_message(filters.command("start"))
async def start(_, message):
    await message.reply_text(
        "🎵 Music Bot Online!\n\n"
        "/play Song Name\n"
        "/pause\n"
        "/resume\n"
        "/skip\n"
        "/stop\n"
        "/queue"
    )


@app.on_message(filters.command("play"))
async def play_music(_, message):
    if len(message.command) < 2:
        await message.reply_text(
            "❌ Song name likho.\n"
            "Example: /play Tum Hi Ho"
        )
        return

    query = " ".join(message.command[1:])

    try:
        await message.reply_text(
            f"🔎 Searching: {query}"
        )

        song = await search_and_download(query)

        if not song:
            await message.reply_text("❌ Song nahi mila.")
            return

        chat_id = message.chat.id

        if chat_id in current_song:
            queues.setdefault(chat_id, []).append(song)

            await message.reply_text(
                f"➕ Queue me add ho gaya:\n{song['title']}"
            )
            return

        await play_song(chat_id, song)

        await message.reply_text(
            f"▶️ Playing:\n{song['title']}"
        )

    except Exception as e:
        print("PLAY ERROR:", repr(e))
        await message.reply_text(
            f"❌ Play error:\n{type(e).__name__}: {e}"
        )


@app.on_message(filters.command("pause"))
async def pause_music(_, message):
    try:
        await call_py.pause(message.chat.id)
        await message.reply_text("⏸ Paused")
    except Exception as e:
        await message.reply_text(
            f"❌ Pause error: {e}"
        )


@app.on_message(filters.command("resume"))
async def resume_music(_, message):
    try:
        await call_py.resume(message.chat.id)
        await message.reply_text("▶️ Resumed")
    except Exception as e:
        await message.reply_text(
            f"❌ Resume error: {e}"
        )


@app.on_message(filters.command("skip"))
async def skip_music(_, message):
    chat_id = message.chat.id

    try:
        await call_py.leave_call(chat_id)

        current_song.pop(chat_id, None)

        if queues.get(chat_id):
            next_song = queues[chat_id].pop(0)

            await play_song(chat_id, next_song)

            await message.reply_text(
                f"⏭ Playing next:\n{next_song['title']}"
            )
        else:
            await message.reply_text(
                "⏭ Queue khali hai."
            )

    except Exception as e:
        await message.reply_text(
            f"❌ Skip error: {e}"
        )


@app.on_message(filters.command("stop"))
async def stop_music(_, message):
    chat_id = message.chat.id

    try:
        await call_py.leave_call(chat_id)
    except Exception:
        pass

    current_song.pop(chat_id, None)
    queues.pop(chat_id, None)

    cleanup_downloads()

    await message.reply_text(
        "⏹ Music stopped."
    )


@app.on_message(filters.command("queue"))
async def show_queue(_, message):
    chat_id = message.chat.id
    items = []

    if chat_id in current_song:
        items.append(
            f"▶️ Now: {current_song[chat_id]['title']}"
        )

    for i, song in enumerate(
        queues.get(chat_id, []),
        1
    ):
        items.append(
            f"{i}. {song['title']}"
        )

    if not items:
        await message.reply_text(
            "📭 Queue empty."
        )
    else:
        await message.reply_text(
            "🎵 Queue:\n\n" + "\n".join(items)
        )


@app.on_message(filters.command("ping"))
async def ping(_, message):
    await message.reply_text("🏓 Pong!")


print("🎵 Music Bot Starting...")

cleanup_downloads()

threading.Thread(
    target=start_web_server,
    daemon=True
).start()

call_py.start()
app.run()
