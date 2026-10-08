FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    chromium \
    ffmpeg \
    wget \
    ca-certificates \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN python -m pip install --no-cache-dir -U pip
RUN python -m pip install --no-cache-dir -r requirements.txt

# Force the YouTube PO Token provider and its compatible nodriver version.
RUN python -m pip install --no-cache-dir --force-reinstall \
    yt-dlp-getpot-wpc==1.1.2 \
    nodriver==0.50.3

# Fail the Render build immediately if the WPC plugin cannot be imported.
RUN python -c "import yt_dlp; import yt_dlp_plugins.extractor.getpot_wpc; print('WPC OK:', yt_dlp.version.__version__)"

COPY . .

ENV CHROME_BIN=/usr/bin/chromium

CMD ["python", "bot.py"]
