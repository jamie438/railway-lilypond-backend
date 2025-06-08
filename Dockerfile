FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    lilypond \
    imagemagick \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

# 👉 Wichtig: Hier auf Port 8080 wechseln
CMD ["gunicorn", "-b", "0.0.0.0:8080", "main:app"]
