FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    lilypond \
    imagemagick \
    && rm -rf /var/lib/apt/lists/*

# 👉 Hier wird die PDF-Sicherheitsrichtlinie angepasst:
RUN sed -i 's/<policy domain="coder" rights="none" pattern="PDF" \/>/<policy domain="coder" rights="read|write" pattern="PDF" \/>/' /etc/ImageMagick-6/policy.xml

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

# Railway erwartet Port 8080
CMD ["gunicorn", "-b", "0.0.0.0:8080", "main:app"]
