
import os
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

    print(f"🌐 Starting health server on port {port}")

    server = HTTPServer(("0.0.0.0", port), HealthHandler)

    print(f"✅ Health server started on port {port}")

    server.serve_forever()

def cleanup_downloads():
    for f in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
        try:
            os.remove(f)
        except Exception:
            pass

async def search_and_download(query):
    """Search YouTube Music and download the best audio stream directly."""
    import urllib.request

    try:
        from ytmusicapi import YTMusic
    except ImportError as e:
        print(f"[PLAY] ytmusicapi missing: {e}")
        return None

    try:
        print(f"[PLAY] YouTube Music search: {query}")
        ytm = YTMusic()

        # Search official music catalogue first.
        results = ytm.search(query, filter="songs", limit=5)
        video = next(
            (x for x in results if x.get("videoId") and x.get("isAvailable", True)),
            None
        )

        # Fallback to normal videos if no song result is available.
        if not video:
            results = ytm.search(query, filter="videos", limit=5)
            video = next(
                (x for x in results if x.get("videoId") and x.get("isAvailable", True)),
                None
            )

        if not video:
            print("[PLAY] YouTube Music returned no playable result")
            return None

        video_id = video["videoId"]
        title = video.get("title") or query
        print(f"[PLAY] Found: {title} | {video_id}")

        # Fresh signature timestamp gives get_song() valid streaming URLs.
        signature_timestamp = ytm.get_signatureTimestamp()
        song_data = ytm.get_song(video_id, signature_timestamp)

        playability = song_data.get("playabilityStatus", {})
        print(f"[PLAY] Playability: {playability.get('status')}")

        streaming = song_data.get("streamingData", {})
        formats = [
            f for f in streaming.get("adaptiveFormats", [])
            if f.get("url") and str(f.get("mimeType", "")).startswith("audio/")
        ]

        if not formats:
            print("[PLAY] No direct audio stream returned")
            return None

        # Prefer the highest bitrate audio-only stream.
        audio = max(formats, key=lambda f: f.get("bitrate", 0))
        audio_url = audio["url"]
        mime = audio.get("mimeType", "")
        ext = ".m4a" if "mp4" in mime else ".webm"

        file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}{ext}")
        print(f"[PLAY] Downloading audio... bitrate={audio.get('bitrate')}")

        req = urllib.request.Request(
            audio_url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "*/*",
            },
        )

        with urllib.request.urlopen(req, timeout=120) as response:
            with open(file_path, "wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)

        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            print("[PLAY] Downloaded file is empty")
            try:
                os.remove(file_path)
            except Exception:
                pass
            return None

        print(f"[PLAY] Download complete: {file_path}")
        return {
            "title": title,
            "path": file_path,
            "video_id": video_id,
        }

    except Exception as e:
        print(f"[PLAY] YouTube Music error: {type(e).__name__}: {e}")
        return None


async def play_song(chat_id, song):
    """Start a downloaded audio file in the Telegram voice chat."""
    file_path = song["path"]

    if not os.path.exists(file_path):
        raise FileNotFoundError(file_path)

    await call_py.play(
        chat_id,
        MediaStream(
            file_path,
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
            await message.reply_text(
                "❌ Song nahi mila."
            )
            return

        chat_id = message.chat.id

        if chat_id in current_song:
            queues.setdefault(
                chat_id,
                []
            ).append(song)

            await message.reply_text(
                f"➕ Queue me add ho gaya:\n"
                f"{song['title']}"
            )
            return

        await play_song(
            chat_id,
            song
        )

        await message.reply_text(
            f"▶️ Playing:\n"
            f"{song['title']}"
        )

    except Exception as e:
        print(
            "PLAY ERROR:",
            repr(e)
        )

        await message.reply_text(
            f"❌ Play error:\n"
            f"{type(e).__name__}: {e}"
        )


@app.on_message(filters.command("pause"))
async def pause_music(_, message):
    try:
        await call_py.pause(
            message.chat.id
        )

        await message.reply_text(
            "⏸ Paused"
        )

    except Exception as e:
        await message.reply_text(
            f"❌ Pause error: {e}"
        )


@app.on_message(filters.command("resume"))
async def resume_music(_, message):
    try:
        await call_py.resume(
            message.chat.id
        )

        await message.reply_text(
            "▶️ Resumed"
        )

    except Exception as e:
        await message.reply_text(
            f"❌ Resume error: {e}"
        )


@app.on_message(filters.command("skip"))
async def skip_music(_, message):
    chat_id = message.chat.id

    try:
        await call_py.leave_call(
            chat_id
        )

        current_song.pop(
            chat_id,
            None
        )

        if queues.get(chat_id):
            next_song = queues[
                chat_id
            ].pop(0)

            await play_song(
                chat_id,
                next_song
            )

            await message.reply_text(
                f"⏭ Playing next:\n"
                f"{next_song['title']}"
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
        await call_py.leave_call(
            chat_id
        )
    except Exception:
        pass

    current_song.pop(
        chat_id,
        None
    )

    queues.pop(
        chat_id,
        None
    )

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
            f"▶️ Now: "
            f"{current_song[chat_id]['title']}"
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
            "🎵 Queue:\n\n"
            + "\n".join(items)
        )


@app.on_message(filters.command("ping"))
async def ping(_, message):
    await message.reply_text(
        "🏓 Pong!"
    )


print("🎵 Music Bot Starting...")

cleanup_downloads()

threading.Thread(
    target=start_web_server,
    daemon=True
).start()

call_py.start()

app.run()

