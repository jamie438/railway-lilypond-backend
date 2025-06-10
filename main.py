
from flask import Flask, request, jsonify
import re
import subprocess
import psycopg2.extras
from flask_socketio import SocketIO, emit, join_room
from pathlib import Path
from supabase import create_client, Client
import os
from PIL import Image, ImageChops, ImageOps
import jwt
from jwt import InvalidTokenError
import mimetypes
import tempfile
import requests

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")




SUPABASE_URL = "https://saxhvimwcbkkoxalhrqx.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNheGh2aW13Y2Jra294YWxocnF4Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0OTQ1OTk3NCwiZXhwIjoyMDY1MDM1OTc0fQ.8ovzcbJlHJnEc_yKdA0XrOs-Ks7ALTovwcMn9ElpNcM"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
BUCKET_NAME = "audiofiles"

def get_db_connection():
    conn = psycopg2.connect("postgresql://postgres.saxhvimwcbkkoxalhrqx:Grandma%40Lachen1234@aws-0-eu-central-1.pooler.supabase.com:5432/postgres?sslmode=require")
    conn.autocommit = True
    return conn


@app.route("/try_again", methods=["POST"])
def try_again():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing JSON payload"}), 400

    user_id = data.get("user_id")
    name = data.get("exercise_name")
    frequencies = data.get("frequencies")
    durations = data.get("durations")
    time_signature = data.get("time_signature")
    acc_positions = data.get("accidentals_position")
    acc_types = data.get("accidental_types")

    if user_id is None or name is None or frequencies is None:
        return jsonify({"error": "Missing required fields"}), 400

    note_count = data.get("note_count", len(frequencies))
    accidentals_count = data.get("accidentals_count", len(acc_positions or []))

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        insert_query = """
            INSERT INTO reference_exercises (
                user_id, name, note_count, accidentals_count,
                accidentals_position, freq, durations,
                time_signature, accidental_types
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        cursor.execute(
            insert_query,
            (
                user_id,
                name,
                note_count,
                accidentals_count,
                acc_positions or [],
                frequencies or [],
                durations or [],
                time_signature,
                acc_types or []
            )
        )

        conn.commit()
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

    # Nach conn.commit(), aber vor conn.close():
    process_reference_exercise(
        user_id=user_id,
        name=name,
        freq=frequencies,
        durations=durations,
        time_signature=time_signature,
        accidental_types=acc_types
    )

    return jsonify({"status": "success", "exercise_name": name}), 200


def process_reference_exercise(user_id, name, freq, durations, time_signature, accidental_types):
    print("📌 Verarbeite Referenzübung:")
    print("👤 user_id:", user_id)
    print("📛 name:", name)
    print("📊 freq:", freq)
    print("🕒 durations:", durations)
    print("🎼 time_signature:", time_signature)
    print("♯ accidental_types:", accidental_types)

    NOTE_FREQUENCIES = {
        "c": 116.54, "cis": 123.47, "d": 130.81, "dis": 138.59, "e": 146.83,
        "f": 155.56, "fis": 164.81, "g": 174.61, "gis": 185.00, "a": 196.00,
        "ais": 207.65, "b": 220.00, "c'": 233.08, "cis'": 246.94, "d'": 261.63,
        "dis'": 277.18, "e'": 293.66, "f'": 311.13, "fis'": 329.63, "g'": 349.23,
        "gis'": 369.99, "a'": 392.00, "ais'": 415.30, "b'": 440.00, "c''": 466.16,
        "cis''": 493.88, "d''": 523.25, "dis''": 554.37, "e''": 587.33,
        "f''": 622.25, "fis''": 659.25, "g''": 698.46, "gis''": 739.99,
        "a''": 783.99, "ais''": 830.61, "b''": 880.00,
         "a'''": 1567.98  # für Anhang
    }

    def match_note_name(f: float) -> str:
        return min(NOTE_FREQUENCIES.items(), key=lambda item: abs(item[1] - f))[0]

    def apply_accidental(note: str, accidental_type: str) -> str:
        if accidental_type == "1":
            return note
        match = re.match(r"([a-g])(.*)", note)
        if not match:
            return note
        base, suffix = match.groups()
        if accidental_type == "0":
            return base + "es" + suffix
        elif accidental_type == "2":
            return base + "is" + suffix
        return note

    min_len = min(len(freq), len(durations), len(accidental_types))

    freq = freq[:min_len]
    durations = durations[:min_len]
    accidental_types = accidental_types[:min_len]

    # 🎼 Normale Noten konvertieren
    lilypond_notes_raw = [match_note_name(f) for f in freq]
    lilypond_notes = [
        apply_accidental(note, acc_type) + str(dur)
        for note, acc_type, dur in zip(lilypond_notes_raw, accidental_types, durations)
    ]

    # 🎼 Zwei feste Noten anhängen: e1 und a'''1
    lilypond_notes.append("e1")
    lilypond_notes.append("a'''1")

    lilypond_string = '{ ' + ' '.join(lilypond_notes) + ' }'
    print("🎼 LilyPond-Format:", lilypond_string)

    # 🔁 → PNG generieren + hochladen
    try_again_process_scale(f"{name}_{user_id}", lilypond_string)

    # 🔁 → Rückgabe
    return {f"{name}_{user_id}": lilypond_string}


def try_again_process_scale(name, notes):
    note_list = notes.split()
    note_list = note_list[:-2]  # 🚫 Letzte 2 Noten entfernen
    # Taktart aus LilyPond-Code extrahieren oder festlegen
    time_signature_str = "4/4"  # falls du es später dynamisch machen willst, extrahiere es aus notes oder gib es mit
    time_signature_map = {
        "2/4": 2,
        "3/4": 3,
        "4/4": 4,
        "6/8": 6
    }
    time_signature = time_signature_map.get(time_signature_str, 4)  # Default = 4

    note_count = len(note_list)
    note_width_mm = 24
    padding_mm = 40
    total_width = note_count * note_width_mm + padding_mm
    dpi = 600

    tmp = Path("/tmp")
    output_png_path = tmp / f"{name}.png"
    temp_png_path = tmp / "temp_output.png"
    cropped_png_path = tmp / "cropped_output.png"

    ly_code = f"""
    \\version "2.24.1"

    #(set-global-staff-size 36)
    \\paper {{
      indent = 0
      line-width = {total_width}\\mm
      ragged-right = ##t
      paper-width = {total_width}\\mm
      paper-height = 180\\mm
      tagline = ##f
    }}

    \\layout {{
      \\context {{
        \\Score
        \\remove "Bar_number_engraver"
      }}
    }}

    \\score {{
      \\new Staff {{
        \\clef treble
        \\key c \\major
        \\time 4/4

        {notes}
      }}
    }}
    """
    ly_code = ly_code.replace('\\version "2.24.2"', '\\version "2.24.1"')

    ly_file = Path("/tmp/notation.ly")
    pdf_file = ly_file.with_suffix(".pdf")
    ly_file.write_text(ly_code)

    subprocess.run(["lilypond", "-o", str(ly_file.with_suffix("")), str(ly_file)], check=True)

    subprocess.run([
        "convert", "-density", str(dpi), "-background", "none", "-alpha", "on",
        str(pdf_file), str(temp_png_path)
    ], check=True)

    subprocess.run([
        "convert", str(temp_png_path),
        "-trim", "-bordercolor", "none", "-border", "20",
        str(output_png_path)
    ], check=True)

    img = Image.open(output_png_path)
    width, height = img.size




    temp_png_path.unlink(missing_ok=True)


    print(f"✅ PNG fertig: {output_png_path}")

    upload_path = f"media/exercises/{name}.png"
    with open(output_png_path, "rb") as f:
        supabase.storage.from_("audiofiles").upload(
            f"{upload_path}?upsert=true",
            f,
            {"content-type": "image/png"}
        )
    print(f"🚀 Hochgeladen nach Supabase: {upload_path}")

    accidental_positions = []
    accidental_types = []
    accidental_count = 0
    durations = []
    frequencies = []
    note_regex = re.compile(r"([a-g][eis]*[,']*)(\d+\.*)")

    NOTE_FREQUENCIES = {
        # Subsubkontra-Oktave
        "c,,": 29.14, "cis,,": 30.96, "des,,": 30.96, "d,,": 32.70, "dis,,": 34.65, "es,,": 34.65,
        "e,,": 36.71, "f,,": 38.89, "fis,,": 41.20, "ges,,": 41.20, "g,,": 43.65,
        "gis,,": 46.25, "as,,": 46.25, "a,,": 49.00, "ais,,": 51.91, "bes,,": 51.91, "b,,": 55.00,

        # Subkontra-Oktave
        "c,": 58.27, "cis,": 61.74, "des,": 61.74, "d,": 65.41, "dis,": 69.30, "es,": 69.30,
        "e,": 73.42, "f,": 77.78, "fis,": 82.41, "ges,": 82.41, "g,": 87.31,
        "gis,": 92.50, "as,": 92.50, "a,": 98.00, "ais,": 103.83, "bes,": 103.83, "b,": 110.00,

        # Kontra-Oktave
        "c": 116.54, "cis": 123.47, "des": 123.47, "d": 130.81, "dis": 138.59, "es": 138.59,
        "e": 146.83, "f": 155.56, "fis": 164.81, "ges": 164.81, "g": 174.61,
        "gis": 185.00, "as": 185.00, "a": 196.00, "ais": 207.65, "bes": 207.65, "b": 220.00,

        # eingestrichene Oktave
        "c'": 233.08, "cis'": 246.94, "des'": 246.94, "d'": 261.63, "dis'": 277.18, "es'": 277.18,
        "e'": 293.66, "f'": 311.13, "fis'": 329.63, "ges'": 329.63, "g'": 349.23,
        "gis'": 369.99, "as'": 369.99, "a'": 392.00, "ais'": 415.30, "bes'": 415.30, "b'": 440.00,
        "eis''": 622.25,
        # zweigestrichene Oktave
        "c''": 466.16, "cis''": 493.88, "des''": 493.88, "d''": 523.25, "dis''": 554.37, "es''": 554.37,
        "e''": 587.33, "f''": 622.25, "fis''": 659.25, "ges''": 659.25, "g''": 698.46,
        "gis''": 739.99, "as''": 739.99, "a''": 783.99, "ais''": 830.61, "bes''": 830.61, "b''": 880.00, "bis''": 932.33,
        "ces'''": 880.00, "eis'''": 1244.51,
        # dreigestrichene Oktave
        "c'''": 932.33, "cis'''": 987.77, "des'''": 987.77, "d'''": 1046.50, "dis'''": 1108.73, "es'''": 1108.73,
        "e'''": 1174.66, "f'''": 1244.51, "fis'''": 1318.51, "ges'''": 1318.51, "g'''": 1396.91,
        "gis'''": 1479.98, "as'''": 1479.98, "a'''": 1567.98, "ais'''": 1661.22, "bes'''": 1661.22, "b'''": 1760.00,
    }

    def lilypond_note_to_frequency(note_str: str) -> float:
        pitch_part = re.match(r"([a-g](is|es)?[,']*)", note_str)
        if not pitch_part:
            return 0.0

        note_key = pitch_part.group(1)


        if note_key in NOTE_FREQUENCIES:
            return NOTE_FREQUENCIES[note_key]
        else:
            print(f"⚠️  WARNUNG: Note '{note_key}' nicht gefunden!")
            return 0.0

    for i, token in enumerate(note_list):
        match = note_regex.match(token)
        if not match:
            continue
        note, dur = match.groups()

        # ♯/♭-Logik
        # ♯/♭-Typ erkennen: 0 = ♭, 1 = natürlich, 2 = ♯
        note_base = re.match(r"([a-g])(is|es)?", note)
        if note_base:
            base, acc = note_base.groups()
            if acc == "es":
                accidental_positions.append(str(i))
                accidental_types.append("0")
                accidental_count += 1
            elif acc == "is":
                accidental_positions.append(str(i))
                accidental_types.append("2")
                accidental_count += 1
            else:
                accidental_types.append("1")

            # Keine Position, kein Count für natürliche Noten

            # ⚠️ Normale Noten NICHT zum accidental_count zählen!

        # 🎵 Rhythmus-Wert berechnen (inkl. Punktierungen)
        # 🎵 Rhythmus-Wert berechnen (inkl. Punktierungen)
        # 🎵 Rhythmus-Wert strikt zuweisen
        duration_map = {
            "1": 1,
            "2": 2,
            "2.": 1.5,
            "4": 4,
            "4.": 3.5,
            "8": 8,
            "8.": 7.5,
            "16": 16
        }

        dur_clean = dur.strip() if dur else "4"
        duration_float = duration_map.get(dur_clean, 1.0)
        durations.append(str(duration_float))

        # 🎼 Frequenz
        freq = lilypond_note_to_frequency(note)
        frequencies.append(f"{round(freq, 2)}")

    existing_ids = [row['id'] for row in supabase.table("reference_exercises").select("id").execute().data]
    new_id = next(i for i in range(10000) if i not in existing_ids)


    print(f"🧠 Datenbankeintrag erstellt mit ID {new_id}")

def sanitize_filename(filename: str) -> str:
    # Nur Buchstaben, Zahlen, Unterstriche, Bindestriche und Punkt (für .pdf/.png) erlauben
    safe = re.sub(r'[^A-Za-z0-9._-]', '_', filename)
    return safe[:100]  # Optional: maximale Länge beschränken

OWN_SECRET_KEY = "meinSuperGeheimerKey123"

def verify_jwt_and_get_user_id(token: str):
    try:
        print(f"🔐 Token kommt rein: {token[:16]}...", flush=True)

        # Nur zum Debuggen: Unsignierter Inhalt
        decoded_debug = jwt.decode(token, options={"verify_signature": False})
        print("🔍 JWT-Inhalt (unsigniert):", decoded_debug, flush=True)

        # 🔐 Jetzt mit HMAC-SHA256 verifizieren
        decoded = jwt.decode(token, OWN_SECRET_KEY, algorithms=["HS256"])
        print("✅ Signatur OK. Decoded:", decoded, flush=True)

        import uuid

        user_id_str = str(decoded.get("user_id"))  # ← das ist vermutlich bereits ein richtiger UUID-String
        user_id = uuid.UUID(user_id_str)  # ← ergibt ein UUID-Objekt

        if not user_id:
            print("❌ Kein user_id im Payload", flush=True)
            return None

        return user_id

    except InvalidTokenError as e:
        print(f"❌ JWT ungültig: {e}", flush=True)
        return None
    except Exception as e:
        print(f"💥 Fehler beim JWT-Check: {e}", flush=True)
        return None

@app.route("/user_scores", methods=["POST"])
def handle_upload_request():
    # 🔐 Authentifizieren über Authorization-Header
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Kein gültiger Bearer-Token"}), 401

    token = auth_header.replace("Bearer ", "")
    user_id = verify_jwt_and_get_user_id(token)
    if not user_id:
        return jsonify({"error": "Token ungültig"}), 403

    print(f"✅ Authentifiziert als user_id: {user_id}")

    # 📎 Formulardaten & Datei extrahieren
    file = request.files.get("file")
    title = request.form.get("title", "")
    subtitle = request.form.get("subtitle", "")
    composer = request.form.get("composer", "")
    difficulty = request.form.get("difficulty", "3")

    if not file:
        return jsonify({"error": "Keine Datei übergeben"}), 400

    # ✅ Weitergabe an Upload-Logik
    return secure_process_upload(
        file=file,
        user_id=user_id,  # kommt jetzt aus dem verifizierten Token
        title=title,
        subtitle=subtitle,
        composer=composer,
        difficulty=difficulty
    )


ALLOWED_EXTENSIONS = {".pdf": "application/pdf", ".png": "image/png"}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

def secure_process_upload(file, user_id, title, subtitle, composer, difficulty):
    print("➡️ secure_process_upload wird aufgerufen", flush=True)

    try:
        # 🧾 Basisinfos loggen
        print("📥 Upload-Vorgang gestartet")
        print(f"👤 User ID: {user_id}")
        print(f"📄 Titel: {title}, Untertitel: {subtitle}, Komponist: {composer}, Schwierigkeit: {difficulty}")
        print(f"📎 Datei erhalten: {file.filename}, MIME-Type: {file.mimetype}")

        # 🔐 Dateiname und MIME prüfen
        original_filename = file.filename or "unnamed_file"
        safe_filename = sanitize_filename(original_filename)
        ext = os.path.splitext(safe_filename)[1].lower()
        mime = file.mimetype or ""

        if ext not in ALLOWED_EXTENSIONS:
            print(f"❌ Nicht erlaubte Datei-Endung: {ext}")
            return jsonify({"error": f"Dateiendung {ext} nicht erlaubt"}), 400

        expected_mime = ALLOWED_EXTENSIONS[ext]
        if mime != expected_mime:
            print(f"❌ MIME mismatch: erwartet {expected_mime}, erhalten {mime}")
            return jsonify({"error": f"MIME-Type {mime} stimmt nicht mit {expected_mime} überein"}), 400

        # 📏 Größe prüfen
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        if size > MAX_FILE_SIZE:
            print(f"❌ Datei zu groß: {size} Byte")
            return jsonify({"error": "Datei zu groß (max. 10 MB)"}), 400

        print(f"✅ Datei OK: {safe_filename} ({round(size / 1024 / 1024, 2)} MB)")

        # 🗃️ Eintrag in PostgreSQL
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO user_uploaded_scores (user_id, filename, title, subtitle, composer, difficulty, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """, (str(user_id), safe_filename, title, subtitle, composer, int(difficulty)))

            conn.commit()
            cur.close()
            print("✅ Metadaten erfolgreich in PostgreSQL gespeichert.")
        except Exception as e:
            print(f"❌ Fehler beim DB-Insert: {e}")
            return jsonify({"error": "Fehler beim DB-Speichern"}), 500

        # ☁️ Upload in Supabase Storage per HTTP PUT
        try:
            with tempfile.NamedTemporaryFile(delete=True) as temp:
                file.save(temp.name)
                file.seek(0)
                with open(temp.name, "rb") as f:
                    file_data = f.read()

                storage_path = f"media/user_scores/{user_id}_{safe_filename}"
                url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET_NAME}/{storage_path}"
                headers = {
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "Content-Type": mime,
                    "x-upsert": "true"
                }

                response = requests.put(url, headers=headers, data=file_data)
                print(f"📤 Supabase Storage Upload Status: {response.status_code}")
                if response.status_code >= 300:
                    print(f"❌ Fehler beim Upload: {response.text}")
                    return jsonify({"error": "Fehler beim Datei-Upload"}), 500

                print(f"✅ Datei erfolgreich hochgeladen: {storage_path}")
        except Exception as e:
            print(f"❌ Fehler beim Datei-Upload: {e}")
            return jsonify({"error": "Fehler beim Datei-Upload"}), 500

        return jsonify({
            "success": True,
            "filename": safe_filename,
            "message": "Datei + Daten erfolgreich gespeichert"
        }), 200

    except Exception as e:
        print(f"💥 Unerwarteter Fehler: {e}")
        return jsonify({"error": "Unerwarteter Fehler beim Upload"}), 500


DEV_MODE = True  # 🔁 Immer aktiv beim lokalen Entwickeln

def scan_file_with_clamav(file) -> bool:
    with tempfile.NamedTemporaryFile(delete=True) as temp:
        file.save(temp.name)

        try:
            result = subprocess.run(
                ["clamscan", "--no-summary", temp.name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10
            )

            # Wenn clamscan 0 zurückgibt → kein Virus gefunden
            return result.returncode == 0
        except Exception as e:
            print(f"⚠️ ClamAV-Fehler: {e}")
            if DEV_MODE:
                print("🧪 Ignoriere Scanfehler im Dev-Modus")
                return True  # <- Ja, erlauben!
            return False

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))  # früher: 10000
    print(f"🚀 Starte Flask-Server auf Port {port}", flush=True)
    socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)
