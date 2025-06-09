FROM python:3.11-slim

# 🔧 Systempakete: Lilypond, Imagemagick, ClamAV
RUN apt-get update && apt-get install -y \
    lilypond \
    imagemagick \
    clamav \
    clamav-daemon \
    && rm -rf /var/lib/apt/lists/*

# 📄 PDF-Sicherheitsrichtlinie fixen (für Imagemagick)
RUN sed -i 's/<policy domain="coder" rights="none" pattern="PDF" \/>/<policy domain="coder" rights="read|write" pattern="PDF" \/>/' /etc/ImageMagick-6/policy.xml || true

# 🔄 ClamAV-Datenbank updaten (wichtig!)
RUN freshclam

# 📁 Projektstruktur
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

# 🚀 App starten (Railway erwartet Port 8080)
CMD ["gunicorn", "-b", "0.0.0.0:8080", "main:app"]
