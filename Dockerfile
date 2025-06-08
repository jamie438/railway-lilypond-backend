FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    lilypond \
    imagemagick \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

CMD ["gunicorn", "-b", "0.0.0.0:10000", "main:app"]
