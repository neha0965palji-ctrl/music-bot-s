FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN python -m pip install --no-cache-dir -U pip
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
