
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
    import os
    import json
    import urllib.parse
    import urllib.request

    PIPED_APIS = [
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.adminforge.de",
    ]

    def get_json(url):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    # Search video
    search_url = "/search?" + urllib.parse.urlencode({
        "q": query,
        "filter": "music"
    })

search_data = None
api_used = None

    for api in PIPED_APIS:
        try:
            print(f"[PLAY] Searching API: {api} | Query: {query}")
            search_data = get_json(api + search_url)

            print(
                f"[PLAY] Search response: "
                f"{len(search_data.get('items', [])) if search_data else 0} items"
            )

            if search_data and search_data.get("items"):
                api_used = api
                break

        except Exception as e:
            print(f"[PLAY] Search API failed: {api}")
            print(f"[PLAY] Error: {type(e).__name__}: {e}")
            continue

    if not search_data or not search_data.get("items"):
        print(f"[PLAY] No search results for: {query}")
        return None
        return None
        return None

    video = None

    for item in search_data["items"]:
        if item.get("type") == "stream":
            video = item
            break

    if not video:
        return None
    parsed = urllib.parse.urlparse(video_url)
    video_id = urllib.parse.parse_qs(parsed.query).get("v", [None])[0]
try:
    print(f"[PLAY] Getting streams for video: {video_id}")
    print(f"[PLAY] Using API: {api_used}")

    stream_data = get_json(
        f"{api_used}/streams/{video_id}"
    )

    print("[PLAY] Stream API response received")

except Exception as e:
    print("[PLAY] Stream API failed")
    print(f"[PLAY] Error: {type(e).__name__}: {e}")
    return None
    # Get audio streams
    stream_data = None

    try:
        stream_data = get_json(
            f"{api_used}/streams/{video_id}"
        )
    except Exception:
        return None

    if not stream_data:
        return None

  audio_streams = stream_data.get("audioStreams", [])

print(f"[PLAY] Audio streams found: {len(audio_streams)}")

if not audio_streams:
    print(f"[PLAY] No audio streams for video ID: {video_id}")
    return None
    # Prefer higher bitrate audio
    audio_streams = sorted(
        audio_streams,
        key=lambda x: x.get("bitrate", 0),
        reverse=True
    )

    audio = audio_streams[0]
    audio_url = audio.get("url")

    if not audio_url:
        return None

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    mime = audio.get("mimeType", "")

    if "webm" in mime:
        ext = ".webm"
    else:
        ext = ".m4a"

    output_file = os.path.join(
        DOWNLOAD_DIR,
        f"{video_id}{ext}"
    )

    # Remove old files for this video
    for old_file in os.listdir(DOWNLOAD_DIR):
        if old_file.startswith(video_id + "."):
            try:
                os.remove(
                    os.path.join(DOWNLOAD_DIR, old_file)
                )
            except Exception:
                pass

    try:
        req = urllib.request.Request(
            audio_url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urllib.request.urlopen(req, timeout=60) as response:
            with open(output_file, "wb") as f:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)

    except Exception:
        return None

    if not os.path.exists(output_file):
        return None

    if os.path.getsize(output_file) < 10000:
        return None

    return {
        "title": title,
        "audio": output_file,
        "id": video_id
    }

async def play_song(chat_id, song):
    current_song[chat_id] = song

    await call_py.play(
        chat_id,
        MediaStream(
            song["file"],
            AudioQuality.HIGH
        )
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

