"""
Main backend server.
- Hosts on: a Vultr VPS (just a regular Linux server, nothing Vultr-specific in code)
- Stores in: TigerData (a managed Postgres w/ TimescaleDB extension for time-series data)

Setup:
  1. Create a Tiger Cloud service at https://console.cloud.timescale.com
     -> copy its connection string (looks like a normal Postgres URL)
  2. On your Vultr VPS: pip install -r requirements.txt
  3. Set the DATABASE_URL environment variable to that connection string
  4. Run: python server.py   (or gunicorn server:app for production)
"""

import os
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor

from scoring import compute_composite_score
from presage_capture import get_vitals  # real Presage integration
# from rppg_fallback import extract_heart_rate  # use this instead if Presage is down

app = Flask(__name__)
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://user:pass@host:port/dbname")


def get_db():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    """Run once at startup: creates the table + hypertable if they don't exist."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            time        TIMESTAMPTZ NOT NULL,
            source      TEXT NOT NULL,          -- 'checkin' or 'room'
            ref_id      TEXT,                   -- checkin_id or room_id
            lat         DOUBLE PRECISION,
            lng         DOUBLE PRECISION,
            score       DOUBLE PRECISION,
            tier        TEXT,
            raw         JSONB
        );
    """)
    # Turns the table into a hypertable -- TimescaleDB's time-partitioned
    # storage, which is what makes zone/time aggregation queries fast at scale.
    # Safe to call every startup; it no-ops if already a hypertable.
    cur.execute("""
        SELECT create_hypertable('readings', 'time', if_not_exists => TRUE);
    """)
    conn.commit()
    cur.close()
    conn.close()


def insert_reading(source, ref_id, lat, lng, score, tier, raw):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO readings (time, source, ref_id, lat, lng, score, tier, raw)
        VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s)
        """,
        (source, ref_id, lat, lng, score, tier, json.dumps(raw)),
    )
    conn.commit()
    cur.close()
    conn.close()


# ---------------------------------------------------------------------------
# Personal check-in endpoint (webcam + Presage + self-report, from checkin.js)
# ---------------------------------------------------------------------------
@app.route("/api/checkin", methods=["POST"])
def checkin():
    checkin_id = request.form["checkin_id"]
    lat = float(request.form["lat"])
    lng = float(request.form["lng"])
    symptom_score = float(request.form.get("symptom_score", 0.0))
    consent = request.form.get("consent") == "true"

    if not consent:
        return jsonify({"error": "consent required"}), 400

    pulse_rate = None
    breathing_rate = None
    video_file = request.files.get("video")
    if video_file:
        video_path = f"/tmp/{checkin_id}.mp4"
        video_file.save(video_path)
        vitals = get_vitals(video_path)  # real call to Presage's API
        # If Presage isn't responding reliably tonight, swap the line above for:
        # pulse_rate = extract_heart_rate(video_path)
        if vitals:
            pulse_rate = vitals["pulse_rate"]
            breathing_rate = vitals["breathing_rate"]
        os.remove(video_path)  # don't keep raw video after processing

    result = compute_composite_score(
        pulse_rate=pulse_rate, breathing_rate=breathing_rate, self_reported=symptom_score
    )

    insert_reading(
        source="checkin", ref_id=checkin_id, lat=lat, lng=lng,
        score=result["score"], tier=result["tier"], raw=result["breakdown"],
    )
    return jsonify(result)


# ---------------------------------------------------------------------------
# Room-level endpoint (mic cough/sneeze rate + IR presence, from the Pi)
# ---------------------------------------------------------------------------
@app.route("/api/room-reading", methods=["POST"])
def room_reading():
    data = request.json
    room_id = data["room_id"]
    lat = float(data["lat"])
    lng = float(data["lng"])

    # Simple room score: audio anomaly ratio + presence density.
    # Tune this weighting once you see real numbers from your sensors.
    audio_ratio = data.get("ratio", 0)          # from mic_cough_detector.py's is_rate_abnormal()
    presence_count = data.get("presence_count", 0)

    audio_score = min(audio_ratio / 3.0, 1.0)   # a 3x spike over baseline = max concern
    score = round(audio_score * 100, 1)
    tier = "normal" if score < 30 else "mild" if score < 60 else "high"

    insert_reading(
        source="room", ref_id=room_id, lat=lat, lng=lng,
        score=score, tier=tier, raw={"audio_ratio": audio_ratio, "presence_count": presence_count},
    )
    return jsonify({"score": score, "tier": tier})


# ---------------------------------------------------------------------------
# Zone aggregation for the frontend heatmap
# ---------------------------------------------------------------------------
@app.route("/api/zones", methods=["GET"])
def zones():
    """
    Groups recent readings into a coarse grid (rounded lat/lng) and averages
    their scores -- this is what your frontend heatmap should poll.
    """
    window_minutes = int(request.args.get("window_minutes", 60))
    cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """
        SELECT
            ROUND(lat::numeric, 2) AS zone_lat,
            ROUND(lng::numeric, 2) AS zone_lng,
            AVG(score) AS avg_score,
            COUNT(*) AS reading_count
        FROM readings
        WHERE time >= %s
        GROUP BY zone_lat, zone_lng
        """,
        (cutoff,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(rows)


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
