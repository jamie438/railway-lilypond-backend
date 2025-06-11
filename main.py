
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
from datetime import date, datetime
from psycopg2.extras import json


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
import uuid

def verify_jwt_and_get_user_id(token: str):
    """
    Verifiziert den JWT und extrahiert die user_id.
    Erwartet, dass die user_id ein Integer ist.
    """
    try:
        print(f"🔐 Token wird geprüft: {token[:16]}...", flush=True)

        # Token dekodieren und Signatur prüfen
        decoded = jwt.decode(token, OWN_SECRET_KEY, algorithms=["HS256"])
        print("✅ Signatur OK. Inhalt:", decoded, flush=True)

        user_id = decoded.get("user_id")

        # Einfache Prüfung: Ist die user_id ein Integer?
        if isinstance(user_id, int):
            print(f"🧾 Gültige user_id (int) gefunden: {user_id}")
            return user_id
        else:
            print(f"❌ user_id ist kein Integer oder fehlt. Typ: {type(user_id)}")
            return None

    except jwt.InvalidTokenError as e:
        print(f"❌ JWT ungültig: {e}", flush=True)
        return None
    except Exception as e:
        print(f"💥 Allgemeiner Fehler beim JWT-Check: {e}", flush=True)
        return None



@app.route("/user_scores", methods=["POST"])
def handle_upload_request():
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Kein gültiger Bearer-Token"}), 401

    token = auth_header.replace("Bearer ", "")
    user_id = verify_jwt_and_get_user_id(token)
    if not user_id:
        return jsonify({"error": "Token ungültig oder keine gültige User-ID"}), 403

    print(f"✅ Authentifiziert als user_id: {user_id}")

    # Formulardaten extrahieren
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "Keine Datei übergeben"}), 400

    return secure_process_upload(
        file=file,
        user_id=user_id,
        title=request.form.get("title", ""),
        subtitle=request.form.get("subtitle", ""),
        composer=request.form.get("composer", ""),
        difficulty=request.form.get("difficulty", "3")
    )


ALLOWED_EXTENSIONS = {".pdf": "application/pdf", ".png": "image/png"}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def secure_process_upload(file, user_id, title, subtitle, composer, difficulty):
    """
    Verarbeitet den Upload sicher: prüft Datei und speichert sie in DB und Storage.
    """
    print("➡️ secure_process_upload wird aufgerufen", flush=True)

    try:
        # 🔐 Dateiprüfungen (Name, Typ, Größe)
        safe_filename = sanitize_filename(file.filename or "unnamed")
        ext = os.path.splitext(safe_filename)[1].lower()
        mime = file.mimetype

        if ext not in ALLOWED_EXTENSIONS or mime != ALLOWED_EXTENSIONS.get(ext):
            print(f"❌ Unerlaubter Dateityp: {safe_filename} (MIME: {mime})")
            return jsonify({"error": "Dateityp nicht erlaubt"}), 400

        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        if size > MAX_FILE_SIZE:
            print(f"❌ Datei zu groß: {size / 1024:.2f} KB")
            return jsonify({"error": "Datei zu groß (max. 10 MB)"}), 400

        print(f"✅ Datei OK: {safe_filename} ({size / (1024 * 1024):.2f} MB)")

        # 🗃️ Eintrag in PostgreSQL (user_id wird jetzt als int übergeben)
        try:
            conn = get_db_connection()
            cur = conn.cursor()

            # KORREKTE ANWEISUNG:
            # Wir listen hier EXAKT die Spalten auf, die wir befüllen wollen.
            # Die Spalte 'id' wird ausgelassen, damit die Datenbank sie automatisch füllt.
            # Die Datenbank weiß jetzt: der erste Wert (%s) gehört zu 'user_id', der zweite zu 'filename' usw.
            cur.execute("""
                INSERT INTO user_uploaded_scores (user_id, filename, title, subtitle, composer, difficulty)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (user_id, safe_filename, title, subtitle, composer, int(difficulty)))

            conn.commit()
            cur.close()
            conn.close()
            print("✅ Metadaten in PostgreSQL gespeichert.")
        except Exception as e:
            print(f"❌ Fehler beim DB-Insert: {e}")

            return jsonify({"error": "Fehler beim Speichern der Daten"}), 500

        # ☁️ Upload in Supabase Storage
        try:
            storage_path = f"media/user_scores/{user_id}_{title}"
            url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET_NAME}/{storage_path}"
            headers = {"Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": mime, "x-upsert": "true"}

            response = requests.put(url, headers=headers, data=file.read())

            if response.status_code >= 300:
                print(f"❌ Fehler beim Upload zu Supabase: {response.text}")
                return jsonify({"error": "Fehler beim Datei-Upload"}), 500

            print(f"✅ Datei erfolgreich hochgeladen: {storage_path}")
        except Exception as e:
            print(f"❌ Fehler beim Datei-Upload: {e}")
            return jsonify({"error": "Fehler beim Datei-Upload"}), 500

        return jsonify({"success": True, "message": "Datei und Daten erfolgreich verarbeitet"}), 200

    except Exception as e:
        print(f"💥 Unerwarteter Fehler in secure_process_upload: {e}")
        return jsonify({"error": "Ein unerwarteter Fehler ist aufgetreten"}), 500


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


@app.route("/level_exercises", methods=["POST"])
def update_level_exercises():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Keine Daten empfangen"}), 400

        level_exercises = data.get("level_exercises")
        user_id = data.get("user_id")
        if level_exercises is None or user_id is None:
            return jsonify({"error": "level_exercises und user_id müssen angegeben werden."}), 400

        level_exercises_str = json.dumps(level_exercises)

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET level_exercises = %s WHERE id = %s", (level_exercises_str, user_id))
        conn.commit()
        conn.close()

        # ✅ Neue PNGs generieren
        for exercise_name, level in level_exercises.items():
            try:
                generate_exercise_png(exercise_name, level, user_id)
            except Exception as gen_err:
                print(f"⚠️ Fehler beim Generieren von PNG für {exercise_name} (Level {level}):", gen_err)

        return jsonify({"message": "Level exercises erfolgreich aktualisiert"}), 200

    except Exception as e:
        print("❌ Fehler beim Aktualisieren der level exercises:", e)
        return jsonify({"error": "Fehler beim Aktualisieren der level exercises"}), 500


def generate_exercise_png(exercise_name: str, level: int, user_id: int):
    # 🧠 Schwächen analysieren → schwache Noten + Score-Map holen
    try:
        schwache_noten, score_map = get_weakness(exercise_name, user_id)
    except Exception as e:
        print(f"❌ Fehler beim Holen der Schwächen: {e}", flush=True)
        return

    # 🧪 Abbruch-Kriterium je Level definieren
    if exercise_name.endswith("_1"):
        threshold = 15
    elif exercise_name.endswith("_2"):
        threshold = 10
    elif exercise_name.endswith("_3"):
        threshold = 5
    else:
        threshold = 15

    # ⛔ Keine Note ist schlechter als Schwelle → Kurs stoppen
    if not any(score > threshold for note, score in score_map.items() if note in schwache_noten):
        print(f"⛔ Keine ausreichend schwachen Noten für {exercise_name} (Level {level}) → Generierung abgebrochen", flush=True)
        stop_course(exercise_name, user_id)
        return

    # 🎼 Übung erzeugen basierend auf Score-Wahrscheinlichkeiten
    uebung = generate_note_sequence_with_rhythm(
        user_id,
        weak_notes=schwache_noten,
        strong_notes=None,
        exercise_name=exercise_name,
        score_map=score_map
    )

    # 🏷️ Namen und Formatierung
    full_name = f"{exercise_name}_{level}"
    note_string = " ".join(lilypond_safe(n) for n in uebung)
    note_inputs = [(full_name, note_string)]

    # 🖼️ PNG generieren
    for exercise_name, full_sequence_raw in note_inputs:
        try:
            url = process_scale(exercise_name, full_sequence_raw, user_id)
            print(f"✅ {exercise_name} → {url}")
        except Exception as e:
            print(f"❌ Fehler bei {exercise_name}: {e}")


def get_weakness(exercise_name, user_id):
    import json

    # 🎚 Schwellenwert je Level
    if exercise_name.endswith("_1"):
        min_score = 10
    elif exercise_name.endswith("_2"):
        min_score = 5
    elif exercise_name.endswith("_3"):
        min_score = -1  # keine Grenze
    else:
        min_score = 10

    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT intonation_stats FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        raw = row[0] if row else {}

        stats = {}
        if isinstance(raw, str):
            try:
                stats = json.loads(raw)
            except json.JSONDecodeError:
                print("⚠️ JSON-Fehler bei intonation_stats", flush=True)
                return [], {}
        elif isinstance(raw, dict):
            stats = raw
        else:
            print("⚠️ Unbekanntes Format für intonation_stats", flush=True)
            return [], {}

        note_scores = stats.get(exercise_name, {})
        if not isinstance(note_scores, dict):
            print("⚠️ Ungültiges Format in intonation_stats", flush=True)
            return [], {}

        if min_score < 0:
            result_notes = list(note_scores.keys())
        else:
            result_notes = [note for note, score in note_scores.items() if score >= min_score]

        print(f"🧪 Notenauswahl für {exercise_name}: {result_notes}", flush=True)
        return result_notes, note_scores

    except Exception as e:
        print(f"❌ Fehler in get_weakness: {e}", flush=True)
        return [], {}

    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


def stop_course(exercise_name, user_id):
    from flask_socketio import emit

    print(f"📴 Kurs gestoppt: {exercise_name} (User {user_id})", flush=True)

    # 🛰 SocketIO-Nachricht an Client senden
    socketio.emit(
        "test_course",
        {"exercise": exercise_name},
        to=str(user_id)
    )


def generate_note_sequence_with_rhythm(weak_notes: list[str], strong_notes: list[str] = None, exercise_name: str = "", score_map: dict[str, int] = None, user_id: int = None) -> list[str]:

    """
    Generiert eine musikalisch sinnvolle Übung mit 1 oder 2 vollen Takten (je 8 Achtelwerte).
    Keine zwei identischen Noten direkt hintereinander erlaubt.
    Kursabhängige Regeln werden beachtet.
    """
    import random

    if strong_notes is None:
        strong_notes = ["c'", "d'", "e'", "f'", "g'", "a'", "b'", "c''", "d''", "e''", "f''", "g''", "a''"]

    total_eighths_per_bar = 8
    total_bars = 2

    # 💡 Kursabhängiger Bereich & Dauer
    if exercise_name.startswith("course_low_register_1"):
        allowed_range = ["g", "a", "b", "c'", "d'"]
        allowed_durations = [("1", 8), ("2", 4), ("4", 2)]
        max_interval = 4  # max Terz

    elif exercise_name.startswith("course_low_register_2"):
        allowed_range = ["e", "f", "g", "a", "b", "c'", "d'"]
        allowed_durations = [
            ("1", 8), ("2", 4), ("2.", 6), ("4", 2),
            ("8", 1), ("16", 0.5),
            ("\\tuplet 3/2 { NOTE8 NOTE8 NOTE8 }", 2)
        ]
        max_interval = 7  # max Quinte

    elif exercise_name.startswith("course_low_register_3"):
        allowed_range = ["e", "fis", "f", "ges", "g", "gis", "aes", "a", "ais", "bes", "b", "c'"]
        allowed_durations = None
        max_interval = None

    elif exercise_name.startswith("course_middle_register_1"):
        allowed_range = ["c'",  "d", "e'", "f'", "g'", "a'"]
        allowed_durations = [("1", 8), ("2", 4), ("4", 2)]
        max_interval = 4  # max Terz

    elif exercise_name.startswith("course_middle_register_2"):
        allowed_range = ["c'",  "d", "e'", "f'", "g'", "a'", "b'", "c''", "d''"]
        allowed_durations = [
            ("1", 8), ("2", 4), ("2.", 6), ("4", 2),
             ("8", 1), ("16", 0.5),
            ("\\tuplet 3/2 { NOTE8 NOTE8 NOTE8 }", 2)
        ]
        max_interval = 7  # max Terz


    elif exercise_name.startswith("course_middle_register_3"):
        allowed_range = ["c'", "cis'", "des'", "d", "dis'", "es'", "e'", "f'", "fis'", "ges'", "g'", "gis'", "aes'",
                         "a'", "ais'", "bes'", "c''", "cis''", "des''", "d''", "dis''"]
        allowed_durations = None
        max_interval = None
        min_interval = 4  # mindestens Terz (inklusive)

    elif exercise_name.startswith("course_highnotes_1"):
        allowed_range = ["g''", "a''", "b''", "c''", "d''"]
        allowed_durations = [("1", 8), ("2", 4), ("4", 2)]
        max_interval = 4  # max Terz

    elif exercise_name.startswith("course_highnotes_2"):
        allowed_range = ["g''", "a''", "b''", "c'''", "d'''", "e'''", "f'''"]
        allowed_durations = [
            ("1", 8), ("2", 4), ("2.", 6), ("4", 2),
            ("8", 1), ("16", 0.5),
            ("\\tuplet 3/2 { NOTE8 NOTE8 NOTE8 }", 2)
        ]
        max_interval = 7
        min_interval = None  # mindestens Terz (inklusive)

    elif exercise_name.startswith("course_highnotes_3"):
        allowed_range = ["g''", "gis''", "aes''", "a''", "aes''", "bes''", "b''", "c'''", "cis'''", "des'''", "d'''", "dis''", "ees'''",
                         "e'''", "f'''", "fis'''", "ges'''", "g'''", "gis'''", "aes'''", "a'''"]
        allowed_durations = None
        max_interval = 12
        min_interval = None

    elif exercise_name.startswith("course_intonation_1"):
        allowed_range = ["g", "a", "b", "c'", "d'", "e'", "f'", "g'", "a'", "b'", "c''"]
        allowed_durations = [("1", 8), ("2", 4), ("4", 2)]
        max_interval = 4
        min_interval = None

    elif exercise_name.startswith("course_intonation_2"):
        allowed_range = ["e", "fis", "f", "ges", "g", "gis", "aes", "a", "ais", "bes", "b", "c'", "cis'", "des'", "d", "dis'", "es'", "e'", "f'", "fis'", "ges'", "g'", "gis'", "aes'",
                         "a'", "ais'", "bes'", "c''", "cis''", "des''", "d''", "dis''", "es''", "e''", "f''", "fis''", "ges''", "g''", "gis''", "aes''", "a''", "ais''", "bes''", "b''", "c'''"]
        allowed_durations = [("1", 8), ("2", 4), ("4", 2)]
        max_interval = 4
        min_interval = 3

    elif exercise_name.startswith("course_intonation_3"):
        allowed_range = ["e", "fis", "f", "ges", "g", "gis", "aes", "a", "ais", "bes", "b", "c'", "cis'", "des'", "d",
                         "dis'", "es'", "e'", "f'", "fis'", "ges'", "g'", "gis'", "aes'",
                         "a'", "ais'", "bes'", "c''", "cis''", "des''", "d''", "dis''", "es''", "e''", "f''", "fis''",
                         "ges''", "g''", "gis''", "aes''", "a''", "ais''", "bes''", "b''", "c'''"]

        allowed_durations = [("1", 8), ("2", 4), ("4", 2)]
        max_interval = 12
        min_interval = None

    elif exercise_name.startswith("course_tone_1"):
        allowed_range = ["e", "f", "g", "a", "b", "c'", "d'", "e'", "f'", "g'", "a'", "b'", "c''"]
        allowed_durations = [("2", 4), ("4", 2)]
        max_interval = 2
        min_interval = None

    elif exercise_name.startswith("course_tone_2"):
        allowed_range = ["c''", "cis''", "des''", "d''", "dis''", "es''", "e''", "f''", "fis''",
                         "ges''", "g''", "gis''", "aes''", "a''", "ais''", "bes''", "b''", "c'''"]

        allowed_durations = [("2", 4), ("4", 2)]
        max_interval = 2
        min_interval = None

    elif exercise_name.startswith("course_tone_3"):
        allowed_range = ["e", "fis", "f", "ges", "g", "gis", "aes", "a", "ais", "bes", "b", "c'", "cis'", "des'", "d",
                         "dis'", "es'", "e'", "f'", "fis'", "ges'", "g'", "gis'", "aes'",
                         "a'", "ais'", "bes'", "c''", "cis''", "des''", "d''", "dis''", "es''", "e''", "f''", "fis''",
                         "ges''", "g''", "gis''", "aes''", "a''", "ais''", "bes''", "b''", "c'''"]

        allowed_durations = [("2", 4), ("4", 2)]
        max_interval = 7
        min_interval = None

    elif exercise_name.startswith("course_connections_1"):
        allowed_range = ["e", "fis", "f", "ges", "g", "gis", "aes", "a", "ais", "bes", "b", "c'", "cis'", "des'", "d",
                         "dis'", "es'", "e'", "f'", "fis'", "ges'", "g'"]

        allowed_durations = [("1", 8), ("2", 4), ("4", 2)]
        max_interval = 7
        min_interval = 3



    elif exercise_name.startswith("course_connections_2"):

        allowed_range = ["e", "fis", "f", "ges", "g", "gis", "aes", "a", "ais", "bes", "b", "c'", "cis'", "des'", "d",

                         "dis'", "es'", "e'", "f'", "fis'", "ges'", "g'", "gis'", "aes'",

                         "a'", "ais'", "bes'", "c''", "cis''", "des''", "d''", "dis''", "es''", "e''", "f''", "fis''",

                         "ges''", "g''", "gis''", "aes''", "a''", "ais''", "bes''", "b''", "c'''"]

        allowed_durations = [("4", 2)]  # ➕ Das hat gefehlt!

        max_interval = 7

        min_interval = 7


    elif exercise_name.startswith("course_connections_3"):
        allowed_range = ["e", "fis", "f", "ges", "g", "gis", "aes", "a", "ais", "bes", "b", "c'", "cis'", "des'", "d",
                         "dis'", "es'", "e'", "f'", "fis'", "ges'", "g'", "gis'", "aes'",
                         "a'", "ais'", "bes'", "c''", "cis''", "des''", "d''", "dis''", "es''", "e''", "f''", "fis''",
                         "ges''", "g''", "gis''", "aes''", "a''", "ais''", "bes''", "b''", "c'''"]
        allowed_durations = [("1", 8), ("2", 4), ("2.", 6), ("4", 2)]
        max_interval = 12
        min_interval = 12

    elif exercise_name.startswith("course_finger_1"):
        allowed_range = ["e", "f", "fis", "g", "gis", "a", "ais", "b", "c'", "cis'", "d'", "dis'", "e'", "f'", "fis'",
                         "g'"]

    elif exercise_name.startswith("course_finger_2"):
        allowed_range = ["e", "fis", "f", "ges", "g", "gis", "aes", "a", "ais", "bes", "b", "c'", "cis'", "des'", "d",
                         "dis'", "es'", "e'", "f'", "fis'", "ges'", "g'", "gis'", "aes'",
                         "a'", "ais'", "bes'", "c''", "cis''", "des''", "d''", "dis''", "es''", "e''", "f''", "fis''",
                         "ges''", "g''", "gis''", "aes''", "a''", "ais''", "bes''", "b''", "c'''"]
        allowed_durations = [("16", 0.5)]
        max_interval = None
        min_interval = None

    elif exercise_name.startswith("course_finger_3"):
        allowed_range = ["e", "fis", "f", "ges", "g", "gis", "aes", "a", "ais", "bes", "b", "c'", "cis'", "des'", "d",
                         "dis'", "es'", "e'", "f'", "fis'", "ges'", "g'", "gis'", "aes'",
                         "a'", "ais'", "bes'", "c''", "cis''", "des''", "d''", "dis''", "es''", "e''", "f''", "fis''",
                         "ges''", "g''", "gis''", "aes''", "a''", "ais''", "bes''", "b''", "c'''"]
        allowed_durations = [("16", 0.5)]
        max_interval = None
        min_interval = None

    else:

        allowed_range = ["e", "f", "g", "a", "b", "c'", "d'", "e'", "f'", "g'", "a'", "b'", "c''", "d''", "e''", "f''",
                         "g''", "a''"]
        allowed_durations = None
        max_interval = None
        min_interval = None


    def lilypond_safe(note: str) -> str:
        return note.strip().replace("♯", "is").replace("♭", "es")

    def pitch_to_midi(note: str) -> int:
        mapping = {
            "c": 60, "cis": 61, "des": 61, "d": 62, "dis": 63, "ees": 63, "es": 63,
            "e": 64, "f": 65, "fis": 66, "ges": 66, "g": 67, "gis": 68, "aes": 68,
            "a": 69, "ais": 70, "bes": 70, "b": 71,
        }
        base = note.replace("'", "")
        octave = note.count("'")
        return mapping.get(base, 60) + octave * 12


    def extract_pitch(note: str) -> str:
        return note.replace("16", "").replace("8", "").replace("4", "").replace("2", "").replace("1", "").replace(".", "").replace("\\tuplet 3/2 {", "").replace("}", "").strip()

    if score_map:
        weighted_weak_notes = []
        for n in allowed_range:
            score = score_map.get(n, 0)
            if score > 0:
                weighted_weak_notes.extend([n] * score)
        if not weighted_weak_notes:
            weighted_weak_notes = list(allowed_range)
    else:
        weighted_weak_notes = list(weak_notes)

    def choose_note(prio_weak=True) -> str:
        attempts = 0
        while attempts < 50:
            if prio_weak and weighted_weak_notes and random.random() < 0.7:
                raw = random.choice(weighted_weak_notes)
            else:
                raw = random.choice(strong_notes)
            clean = lilypond_safe(raw)
            if clean in allowed_range:
                return clean
            attempts += 1
        return random.choice(allowed_range)


    if allowed_durations is not None:
        patterns = []

        for dur, val in allowed_durations:
            if "tuplet" in dur:
                def make(v=val):
                    n1 = choose_note()
                    n2 = choose_note(False)
                    n3 = choose_note()
                    return [f"\\tuplet 3/2 {{ {n1}8 {n2}8 {n3}8 }}"], v
                patterns.append(make)
            else:
                def make(d=dur, v=val):
                    return [choose_note() + d], v
                patterns.append(make)
    else:
        patterns = [
            lambda: ([choose_note() + "8", choose_note(False) + "8"], 2),
            lambda: ([f"\\tuplet 3/2 {{ {choose_note()}8 {choose_note(False)}8 {choose_note()}8 }}"], 3),
            lambda: ([choose_note() + "4"], 2),
            lambda: ([choose_note() + "8.", choose_note(False) + "16"], 2),
            lambda: ([choose_note() + "2"], 4),
            lambda: ([choose_note() + "4", choose_note(False) + "4"], 4),
            lambda: ([choose_note() + "1"], 8),
        ]

    full_sequence = []
    full_sequence_raw = []
    full_sequence_durations = []

    if exercise_name.startswith("course_finger_1"):
        full_sequence = []
        direction = random.choice(["up", "down"])
        base_note = choose_note()

        def shift_by_intervals(base: str, intervals: list[int]) -> list[str]:
            try:
                base_midi = pitch_to_midi(base)
                seq = [base_midi]
                for iv in intervals:
                    seq.append(seq[-1] + iv)
                return [n for n in [note for note in allowed_range if pitch_to_midi(note) in seq] for _ in [0]]
            except:
                return []

        if direction == "up":
            intervals = [4, 3, 4, 3, -14]  # Gesamtbewegung: +14 (zurück zur Oktave tiefer)
        else:
            intervals = [-3, -4, -3, -4, +14]

        # Erzeuge Sequenz
        note_names = shift_by_intervals(base_note, intervals)
        if len(note_names) != 6:
            print("⚠️ Ungültige Folge – versuche erneut")
            return generate_note_sequence_with_rhythm(weak_notes, strong_notes, exercise_name, score_map, user_id)

        # z. B. 6 Noten je Viertel
        full_sequence = [note + "4" for note in note_names]

        return full_sequence

    intervals_up = [4, -2, 3, -1, 3, -2, 4, -2, 4, -2, 3, 4, -2, 3, -1, 3, -2, 4, -2, 4, -2, 3]
    intervals_down = [-3, 2, -4, 2, -4, 2, -1, 1, -3, 2, -4, -3, 2, -4, 2, -4, 2, -1, 1, -3, 2, -4]

    if exercise_name.startswith("course_finger_2"):
        full_sequence = []
        direction = random.choice(["up", "down"])
        base_note = choose_note()

        def shift_sequence(base: str, intervals: list[int]) -> list[str]:
            try:
                base_midi = pitch_to_midi(base)
                seq = [base_midi]
                for iv in intervals:
                    seq.append(seq[-1] + iv)
                # Nur erlaubte Noten
                return [n for n in [note for note in allowed_range if pitch_to_midi(note) in seq]]
            except:
                return []

        intervals = intervals_up if direction == "up" else intervals_down
        note_names = shift_sequence(base_note, intervals)

        if len(note_names) != len(intervals) + 1:
            print("⚠️ Ungültige Folge – versuche erneut")
            return generate_note_sequence_with_rhythm(weak_notes, strong_notes, exercise_name, score_map, user_id)

        # z. B. durchgehend Achtelnoten
        full_sequence = [note + "16" for note in note_names]
        return full_sequence

    if exercise_name.startswith("course_finger_3"):
        def get_note_sequence_from_intervals(start_note: str, intervals: list[int]) -> list[str]:
            sequence = [start_note]
            current_midi = pitch_to_midi(start_note)
            for step in intervals:
                current_midi += step
                candidates = [n for n in allowed_range if pitch_to_midi(n) == current_midi]
                if not candidates:
                    return []
                sequence.append(candidates[0])
            return sequence

        # 🎯 Alle definierten Abläufe (jeweils: (aufwärts, abwärts))
        all_patterns = [
            (
                [2, 2, 1, -3, 2, 1, 2, -3, 1, 2, 2, -4, 2, 2, 2, -4, 2, 2, 1, -3, 2, 1, 2, -3, 1, 2, 2, -4],
                [-1, -2, -2, 4, -2, -2, -2, 4, -2, -2, -1, 3, -2, -1, -2, 3, -1, -2, -2, 4, -2, -2, -1, 1],
            ),
            (
                [4, 3, 3, 2, 4, 3, 3, 2],
                [-2, -3, -3, -4, -2, -3, -3, -4],
            ),
        ]

        # 🔁 Auswahl eines zufälligen Musters
        direction = random.choice(["up", "down"])
        pattern = random.choice(all_patterns)
        intervals = pattern[0] if direction == "up" else pattern[1]

        # 🔁 Wiederhole für `total_bars`
        full_sequence = []
        for _ in range(total_bars):
            root_note = choose_note()
            note_names = get_note_sequence_from_intervals(root_note, intervals)
            if not note_names:
                continue
            full_sequence.extend([n + "16" for n in note_names])

        return full_sequence

    if exercise_name.startswith("course_connections_2"):
        # 🎯 Spezielle Sequenz: Grundton–Quinte–Wechsel
        # Wir nehmen zufällige Grundtöne und wechseln zur Quinte
        def get_quinte(note: str) -> str:
            try:
                base_midi = pitch_to_midi(note)
                quinte_midi = base_midi + 7
                candidates = [n for n in allowed_range if pitch_to_midi(n) == quinte_midi]
                return candidates[0] if candidates else None
            except:
                return None

        for _ in range(total_bars):
            takt = []
            used = 0
            while used < total_eighths_per_bar:
                grundton = choose_note()
                quinte = get_quinte(grundton)
                if not quinte:
                    continue  # finde anderen Grundton
                # Verwende immer Viertelnoten für Gleichverteilung
                takt.append(grundton + "4")
                takt.append(quinte + "4")
                used += 4  # 2 Viertel = 4 Achtel
            full_sequence.extend(takt)
        return full_sequence

    for _ in range(total_bars):
        takt = []
        used = 0
        attempt = 0

        while used < total_eighths_per_bar and attempt < 200:
            notes, dur = random.choice(patterns)()

            if used + dur > total_eighths_per_bar:
                attempt += 1
                continue

            last_note = extract_pitch((takt + full_sequence)[-1]) if (takt or full_sequence) else None
            first_note = extract_pitch(notes[0])

            if last_note and first_note == last_note:
                attempt += 1
                continue

            if not all(extract_pitch(n) in allowed_range for n in notes):
                attempt += 1
                continue

            # ➕ Intervallregel (nur bei bestimmten Kursen aktiv)
            if last_note:
                try:
                    midi1 = pitch_to_midi(last_note)
                    midi2 = pitch_to_midi(first_note)

                    if max_interval is not None or min_interval is not None or exercise_name.startswith(
                            "course_highnotes_3") or exercise_name.startswith("course_intonation_3"):
                        try:
                            midi1 = pitch_to_midi(last_note)
                            midi2 = pitch_to_midi(first_note)
                            interval = abs(midi2 - midi1)

                            # 🎯 Spezieller Fall: course_highnotes_3
                            if exercise_name.startswith("course_highnotes_3"):
                                if interval > 12:
                                    attempt += 1
                                    continue
                                # Bevorzuge Terz–Quintintervall
                                if not (3 <= interval <= 7) and random.random() < 0.7:
                                    attempt += 1
                                    continue

                            # 🎯 Neuer Fall: course_intonation_3
                            elif exercise_name.startswith("course_intonation_3"):
                                if interval > 12:
                                    attempt += 1
                                    continue
                                # Bevorzuge ebenfalls Terz–Quinte
                                if not (3 <= interval <= 7) and random.random() < 0.7:
                                    attempt += 1
                                    continue

                            # 🎯 Standardfall für min/max
                            else:
                                if max_interval is not None and interval > max_interval:
                                    attempt += 1
                                    continue
                                if min_interval is not None and interval < min_interval:
                                    attempt += 1
                                    continue

                        except Exception:
                            attempt += 1
                            continue

                        except Exception:
                            attempt += 1
                            continue

                    if min_interval is not None and abs(midi2 - midi1) < min_interval:
                        attempt += 1
                        continue

                except Exception:
                    attempt += 1
                    continue

            # ⚠️ Wiederholung z. B. auf Positionen 1/3 oder 2/4 vermeiden
            flattened = takt + full_sequence
            prev_notes = [extract_pitch(n) for n in flattened]

            check_indices = [len(prev_notes) + i for i in range(len(notes))]

            repetitive = False
            for i, idx in enumerate(check_indices):
                if idx >= 2 and idx - 2 < len(prev_notes):
                    if extract_pitch(notes[i]) == prev_notes[idx - 2]:
                        repetitive = True
                        break

            # ⛔ Wenn Wiederholung erkannt & andere Optionen vorhanden → skip mit Wahrscheinlichkeit
            if repetitive and random.random() < 0.8:
                attempt += 1
                continue

            takt.extend(notes)
            for n in notes:
                full_sequence_raw.append(extract_pitch(n))  # z. B. "g'" aus "g'8"
                full_sequence_durations.append(dur / len(notes))  # z. B. bei Tuplet = 3 Noten mit je 0.666

            used += dur

        if used != total_eighths_per_bar:
            print("⚠️ Takt nicht exakt gefüllt, wiederhole...")
            return generate_note_sequence_with_rhythm(weak_notes, strong_notes, exercise_name, score_map, user_id)

        full_sequence.extend(takt)

    if user_id is not None:
        process_scale(full_sequence_raw, exercise_name, user_id)

    # ✅ Immer am Ende: Abschlussnoten
    full_sequence.append("e,1")
    full_sequence.append("a'''1")

    return full_sequence


def lilypond_safe(note: str) -> str:
    return (
        note.replace("♯", "is")
            .replace("♭", "es")
            .replace("𝄪", "isis")  # optional
            .replace("𝄫", "eses")  # optional
    )


def process_scale(exercise_name, full_sequence_raw, user_id):
    note_list = full_sequence_raw.split()
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
    output_png_path = tmp / f"{exercise_name}.png"
    temp_png_path = tmp / "temp_output.png"
    cropped_png_path = tmp / "cropped_output.png"

    #note_crop_width_px = int((cut_notes * note_width_mm + cut_padding_mm) * dpi / 15.4)

    ly_code = f"""
    \\version "2.24.2"
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

        {full_sequence_raw}
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
    upload_path = f"media/exercises/{user_id}/{exercise_name}.png"
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

        # zweigestrichene Oktave
        "c''": 466.16, "cis''": 493.88, "des''": 493.88, "d''": 523.25, "dis''": 554.37, "es''": 554.37,
        "e''": 587.33, "f''": 622.25, "fis''": 659.25, "ges''": 659.25, "g''": 698.46,
        "gis''": 739.99, "as''": 739.99, "a''": 783.99, "ais''": 830.61, "bes''": 830.61, "b''": 880.00,

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

    data = {
        "id": new_id,
        "name": exercise_name,
        "created_at": datetime.utcnow().isoformat(),
        "note_count": note_count,
        "accidentals_count": accidental_count,
        "accidentals_position": accidental_positions,
        "freq": frequencies,
        "user_id": 0,
        "durations": durations,
        "accidental_types": accidental_types,
        "time_signature": time_signature,

    }

    res = supabase.table("reference_exercises").insert(data).execute()
    print(f"🧠 Datenbankeintrag erstellt mit ID {new_id}")


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))  # früher: 10000
    print(f"🚀 Starte Flask-Server auf Port {port}", flush=True)
    socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)
