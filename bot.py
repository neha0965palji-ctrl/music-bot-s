import os
import glob
import threading
import requests
from http.server import BaseHTTPRequestHandler, HTTPServer

from dotenv import load_dotenv
from pyrogram import Client, filters
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream

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

user_app = Client(
    "music_assistant",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING
) if SESSION_STRING else Client(
    "music_assistant",
    api_id=API_ID,
    api_hash=API_HASH
)

call_py = PyTgCalls(user_app)

queues = {}
current_song = {}


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


def start_web_server():
    port = int(os.environ.get("PORT", 10000))
    print(f"Starting health server on port {port}")
    HTTPServer(("0.0.0.0", port), HealthHandler).serve_forever()


def cleanup_downloads():
    os.makedirs("downloads", exist_ok=True)
    for f in glob.glob("downloads/*"):
        try:
            os.remove(f)
        except Exception:
            pass


def search_song(query):
    """Search JioSaavn and return a direct audio URL."""
    url = "https://saavn.dev/api/search/songs"

    print(f"[PLAY] Saavn search: {query}")

    response = requests.get(
        url,
        params={"query": query, "limit": 10},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20
    )
    response.raise_for_status()

    data = response.json()
    results = data.get("data", {}).get("results", [])

    if not results:
        raise RuntimeError("No song found")

    # Prefer a normal song result with a usable download URL.
    song = None
    audio_url = None

    for item in results:
        links = item.get("downloadUrl") or []
        links = [x for x in links if x.get("url")]
        if links:
            song = item
            audio_url = max(
                links,
                key=lambda x: int(
                    str(x.get("quality", "0")).replace("kbps", "") or 0
                )
            )["url"]
            break

    if not song or not audio_url:
        raise RuntimeError("No playable audio URL")

    title = song.get("name") or query
    artist = song.get("primaryArtists") or ""

    print(f"[PLAY] Found: {title} - {artist}")
    print("[PLAY] Direct audio stream ready")

    return {
        "title": title,
        "artist": artist,
        "url": audio_url,
    }


async def play_song(chat_id, song):
    await call_py.play(
        chat_id,
        MediaStream(
            song["url"],
            video_flags=MediaStream.Flags.IGNORE
        )
    )
    current_song[chat_id] = song


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
        await message.reply_text("❌ Song name likho.")
        return

    query = " ".join(message.command[1:])

    try:
        await message.reply_text(f"🔎 Searching: {query}")

        song = search_song(query)
        chat_id = message.chat.id

        if chat_id in current_song:
            queues.setdefault(chat_id, []).append(song)
            await message.reply_text(
                f"➕ Queue me add ho gaya:\n{song['title']}"
            )
            return

        await play_song(chat_id, song)

        await message.reply_text(
            f"▶️ Playing:\n{song['title']}\n"
            f"🎤 {song['artist']}"
        )

    except Exception as e:
        print(f"[PLAY ERROR] {type(e).__name__}: {e}")
        await message.reply_text(
            f"❌ Play error: {type(e).__name__}: {e}"
        )


@app.on_message(filters.command("pause"))
async def pause_music(_, message):
    try:
        await call_py.pause(message.chat.id)
        await message.reply_text("⏸ Paused")
    except Exception as e:
        await message.reply_text(f"❌ Pause error: {e}")


@app.on_message(filters.command("resume"))
async def resume_music(_, message):
    try:
        await call_py.resume(message.chat.id)
        await message.reply_text("▶️ Resumed")
    except Exception as e:
        await message.reply_text(f"❌ Resume error: {e}")


@app.on_message(filters.command("skip"))
async def skip_music(_, message):
    chat_id = message.chat.id

    try:
        await call_py.leave_call(chat_id)
    except Exception:
        pass

    current_song.pop(chat_id, None)

    if queues.get(chat_id):
        next_song = queues[chat_id].pop(0)
        try:
            await play_song(chat_id, next_song)
            await message.reply_text(
                f"⏭ Playing next:\n{next_song['title']}"
            )
        except Exception as e:
            await message.reply_text(f"❌ Skip error: {e}")
    else:
        await message.reply_text("⏭ Queue khali hai.")


@app.on_message(filters.command("stop"))
async def stop_music(_, message):
    chat_id = message.chat.id

    try:
        await call_py.leave_call(chat_id)
    except Exception:
        pass

    current_song.pop(chat_id, None)
    queues.pop(chat_id, None)

    await message.reply_text("⏹ Music stopped.")


@app.on_message(filters.command("queue"))
async def show_queue(_, message):
    chat_id = message.chat.id
    items = []

    if chat_id in current_song:
        items.append(f"▶️ Now: {current_song[chat_id]['title']}")

    for i, song in enumerate(queues.get(chat_id, []), 1):
        items.append(f"{i}. {song['title']}")

    await message.reply_text(
        "🎵 Queue:\n\n" + "\n".join(items)
        if items else "📭 Queue empty."
    )


@app.on_message(filters.command("ping"))
async def ping(_, message):
    await message.reply_text("🏓 Pong!")


print("🎵 Music Bot Starting...")

threading.Thread(
    target=start_web_server,
    daemon=True
).start()

call_py.start()
app.run()
