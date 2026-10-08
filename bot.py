import os
import threading
from collections import defaultdict, deque
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

if not SESSION_STRING:
    raise RuntimeError("SESSION_STRING Render Environment Variable me missing hai.")

# -----------------------------
# Telegram bot
# -----------------------------
app = Client(
    "music_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

# Telegram user account = Music Assistant
user_app = Client(
    "music_assistant",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)

call_py = PyTgCalls(user_app)

# chat_id -> queued song info
queues = defaultdict(deque)

# chat_id -> current song
current_song = {}

# chat_id set when paused
paused = set()


# -----------------------------
# Render health server
# -----------------------------
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Music Bot is running!")

    def log_message(self, format, *args):
        pass


def start_health_server():
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Health server running on port {port}")
    server.serve_forever()


# -----------------------------
# SoundCloud search/extraction
# -----------------------------
def search_song(query):
    """
    Search SoundCloud with yt-dlp.

    We keep the SoundCloud webpage URL in the queue and extract
    the fresh stream URL only when the song is about to play.
    This avoids using an old/expired stream URL from the queue.
    """
    import yt_dlp

    print(f"[PLAY] SoundCloud search: {query}")

    search_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "extract_flat": False,
    }

    with yt_dlp.YoutubeDL(search_opts) as ydl:
        result = ydl.extract_info(
            f"scsearch1:{query}",
            download=False,
        )

    entries = result.get("entries") if result else None
    if not entries:
        raise RuntimeError(
            f"'{query}' SoundCloud par nahi mila."
        )

    for track in entries:
        if not track:
            continue

        webpage_url = track.get("webpage_url")

        # SoundCloud search can expose an API URL in "url".
        # For playback we intentionally use the real webpage URL.
        if not webpage_url:
            continue

        title = track.get("title") or query
        artist = (
            track.get("uploader")
            or track.get("artist")
            or "Unknown artist"
        )

        print(f"[PLAY] Found: {title} - {artist}")
        print(f"[PLAY] URL: {webpage_url}")

        return {
            "title": title,
            "artist": artist,
            "webpage_url": webpage_url,
        }

    raise RuntimeError(
        f"'{query}' ka playable SoundCloud result nahi mila."
    )


def get_stream_url(webpage_url):
    """
    Extract a fresh SoundCloud stream URL immediately before playback.
    """
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "extract_flat": False,
        "format": "bestaudio/best",
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(webpage_url, download=False)

    if not info or not info.get("url"):
        raise RuntimeError("SoundCloud stream URL nahi mila.")

    return info["url"]


async def start_song(chat_id, song):
    # Get a fresh stream URL at the moment of playback.
    stream_url = get_stream_url(song["webpage_url"])

    playable_song = dict(song)
    playable_song["url"] = stream_url

    await call_py.play(
        chat_id,
        MediaStream(
            stream_url,
            AudioQuality.HIGH,
        ),
    )

    current_song[chat_id] = playable_song
    paused.discard(chat_id)


async def play_next(chat_id):
    if not queues[chat_id]:
        current_song.pop(chat_id, None)
        paused.discard(chat_id)
        return False

    song = queues[chat_id].popleft()

    try:
        await start_song(chat_id, song)
        return True
    except Exception as e:
        print(f"[NEXT ERROR] {type(e).__name__}: {e}")

        # Try the next queued song instead of getting stuck.
        if queues[chat_id]:
            return await play_next(chat_id)

        current_song.pop(chat_id, None)
        paused.discard(chat_id)
        return False


# -----------------------------
# Commands
# -----------------------------
@app.on_message(filters.command("start"))
async def start(_, message):
    await message.reply_text(
        "🎵 **Music Bot Online!**\n\n"
        "▶️ /play Song Name\n"
        "⏸ /pause\n"
        "▶️ /resume\n"
        "⏭ /skip\n"
        "⏹ /stop\n"
        "📜 /queue\n"
        "🏓 /ping"
    )


@app.on_message(filters.command("ping"))
async def ping(_, message):
    await message.reply_text("🏓 Pong!")


@app.on_message(filters.command("play"))
async def play_music(_, message):
    if len(message.command) < 2:
        await message.reply_text(
            "❌ Song name do.\n\n"
            "Example:\n"
            "/play Kesariya"
        )
        return

    query = " ".join(message.command[1:]).strip()
    chat_id = message.chat.id

    status = await message.reply_text(
        f"🔎 **SoundCloud par searching...**\n🎵 {query}"
    )

    try:
        song = search_song(query)

        if chat_id in current_song:
            queues[chat_id].append(song)

            await status.edit_text(
                f"➕ **Queue mein add ho gaya**\n\n"
                f"🎵 {song['title']}\n"
                f"🎤 {song['artist']}\n"
                f"📍 Position: {len(queues[chat_id])}"
            )
            return

        await status.edit_text(
            f"🎵 **{song['title']}**\n"
            f"🎤 {song['artist']}\n\n"
            "▶️ Voice Chat mein play kar raha hoon..."
        )

        await start_song(chat_id, song)

        await status.edit_text(
            f"▶️ **Now Playing**\n\n"
            f"🎵 {song['title']}\n"
            f"🎤 {song['artist']}\n\n"
            "⏸ /pause  |  ⏭ /skip  |  ⏹ /stop"
        )

    except Exception as e:
        print(f"[PLAY ERROR] {type(e).__name__}: {e}")

        await status.edit_text(
            "❌ **Music play nahi ho saki.**\n\n"
            f"`{type(e).__name__}: {str(e)[:500]}`"
        )


@app.on_message(filters.command("pause"))
async def pause_music(_, message):
    chat_id = message.chat.id

    if chat_id not in current_song:
        await message.reply_text("❌ Abhi koi song play nahi ho raha.")
        return

    if chat_id in paused:
        await message.reply_text("⏸ Song already paused hai.")
        return

    try:
        await call_py.pause(chat_id)
        paused.add(chat_id)

        await message.reply_text(
            f"⏸ **Paused**\n\n"
            f"🎵 {current_song[chat_id]['title']}\n\n"
            "▶️ /resume se continue karo."
        )

    except Exception as e:
        print(f"[PAUSE ERROR] {type(e).__name__}: {e}")
        await message.reply_text(
            f"❌ Pause nahi ho saka.\n`{str(e)[:300]}`"
        )


@app.on_message(filters.command("resume"))
async def resume_music(_, message):
    chat_id = message.chat.id

    if chat_id not in current_song:
        await message.reply_text("❌ Abhi koi song play nahi ho raha.")
        return

    if chat_id not in paused:
        await message.reply_text("▶️ Song already playing hai.")
        return

    try:
        await call_py.resume(chat_id)
        paused.discard(chat_id)

        await message.reply_text(
            f"▶️ **Resumed**\n\n"
            f"🎵 {current_song[chat_id]['title']}"
        )

    except Exception as e:
        print(f"[RESUME ERROR] {type(e).__name__}: {e}")
        await message.reply_text(
            f"❌ Resume nahi ho saka.\n`{str(e)[:300]}`"
        )


@app.on_message(filters.command("skip"))
async def skip_music(_, message):
    chat_id = message.chat.id

    if chat_id not in current_song:
        await message.reply_text("❌ Abhi koi song play nahi ho raha.")
        return

    old_title = current_song[chat_id]["title"]

    try:
        await call_py.leave_call(chat_id)
    except Exception:
        pass

    current_song.pop(chat_id, None)
    paused.discard(chat_id)

    if await play_next(chat_id):
        await message.reply_text(
            f"⏭ **Skipped**\n\n"
            f"❌ {old_title}\n"
            f"▶️ **Now Playing:** {current_song[chat_id]['title']}"
        )
    else:
        await message.reply_text(
            f"⏭ **Skipped:** {old_title}\n\n"
            "📭 Queue empty hai."
        )


@app.on_message(filters.command("stop"))
async def stop_music(_, message):
    chat_id = message.chat.id

    try:
        await call_py.leave_call(chat_id)
    except Exception:
        pass

    queues[chat_id].clear()
    current_song.pop(chat_id, None)
    paused.discard(chat_id)

    await message.reply_text(
        "⏹ **Music stopped**\n"
        "🗑 Queue bhi clear kar di gayi."
    )


@app.on_message(filters.command("queue"))
async def show_queue(_, message):
    chat_id = message.chat.id
    lines = []

    if chat_id in current_song:
        song = current_song[chat_id]
        lines.append(
            f"▶️ **Now Playing:**\n"
            f"🎵 {song['title']}\n"
            f"🎤 {song['artist']}"
        )

    if queues[chat_id]:
        lines.append("\n📜 **Up Next:**")

        for i, song in enumerate(queues[chat_id], 1):
            lines.append(
                f"{i}. {song['title']} — {song['artist']}"
            )

    if not lines:
        await message.reply_text("📭 Queue empty hai.")
        return

    await message.reply_text("\n".join(lines))


# -----------------------------
# Start
# -----------------------------
print("🎵 Music Bot Starting with SoundCloud audio...")

threading.Thread(
    target=start_health_server,
    daemon=True,
).start()

call_py.start()
app.run()
