
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
    import json
    import urllib.parse
    import urllib.request

    # Public Piped instances can go offline/change, so keep several fallbacks.
    PIPED_APIS = [
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.tokhmi.xyz",
        "https://pipedapi.moomoo.me",
        "https://pipedapi.syncpundit.io",
        "https://api-piped.mha.fi",
        "https://piped-api.garudalinux.org",
        "https://pipedapi.rivo.lol",
        "https://pipedapi.adminforge.de",
    ]

    def get_json(url, timeout=20):
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    search_url = "/search?" + urllib.parse.urlencode({
        "q": query,
        "filter": "music"
    })

    # Try each instance all the way through search -> stream lookup.
    for api in PIPED_APIS:
        try:
            print(f"[PLAY] Searching: {api} | {query}")

            search_data = get_json(api + search_url)

            if not search_data:
                print(f"[PLAY] Empty search response: {api}")
                continue

            items = search_data.get("items", [])
            print(f"[PLAY] Search results from {api}: {len(items)}")

            video = next(
                (item for item in items if item.get("type") == "stream"),
                None
            )

            if not video:
                print(f"[PLAY] No stream result: {api}")
                continue

            video_url = video.get("url", "")
            parsed = urllib.parse.urlparse(video_url)
            video_id = urllib.parse.parse_qs(parsed.query).get(
                "v", [None]
            )[0]

            # Some Piped responses may provide the id directly.
            if not video_id:
                video_id = video.get("id")

            if not video_id:
                print(f"[PLAY] No video ID: {api}")
                continue

            stream_url = f"{api}/streams/{video_id}"
            print(f"[PLAY] Getting streams: {stream_url}")

            stream_data = get_json(stream_url)

            audio_streams = stream_data.get("audioStreams", [])
            print(
                f"[PLAY] Audio streams from {api}: "
                f"{len(audio_streams)}"
            )

            if not audio_streams:
                print(f"[PLAY] No audio streams: {api}")
                continue

            # Prefer the highest bitrate stream that has a URL.
            audio_streams = sorted(
                [x for x in audio_streams if x.get("url")],
                key=lambda x: x.get("bitrate", 0),
                reverse=True
            )

            if not audio_streams:
                print(f"[PLAY] Audio URL missing: {api}")
                continue

            audio = audio_streams[0]
            audio_url = audio["url"]

            mime_type = audio.get("mimeType", "")
            ext = ".webm" if "webm" in mime_type else ".m4a"

            file_path = os.path.join(
                DOWNLOAD_DIR,
                f"{video_id}{ext}"
            )

            print(f"[PLAY] Downloading audio from {api}...")

            req = urllib.request.Request(
                audio_url,
                headers={"User-Agent": "Mozilla/5.0"}
            )

            with urllib.request.urlopen(req, timeout=90) as response:
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
                continue

            title = video.get("title") or query

            print(f"[PLAY] Download complete: {file_path}")

            # Return a dict because the rest of the bot expects title + path.
            return {
                "title": title,
                "path": file_path,
                "video_id": video_id,
            }

        except Exception as e:
            print(
                f"[PLAY] API failed: {api} | "
                f"{type(e).__name__}: {e}"
            )
            continue

    print("[PLAY] All Piped instances failed")
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

