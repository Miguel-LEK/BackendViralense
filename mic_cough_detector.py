"""
Listens continuously on a room's microphone, detects coughing/sneezing
events using YAMNet (a pretrained audio classifier), and tracks whether
the current rate is abnormal relative to that room's own recent baseline.

Install: pip install tensorflow tensorflow_hub sounddevice numpy requests
"""

import time
import collections
import numpy as np
import sounddevice as sd
import tensorflow_hub as hub
import csv
import io
import urllib.request

import ir_sensor  # from the same directory

SAMPLE_RATE = 16000          # YAMNet requires 16kHz mono audio
CHUNK_SECONDS = 1.0          # how often we run a classification pass
CONFIDENCE_THRESHOLD = 0.3   # YAMNet scores are not super calibrated; tune this
EVENT_WINDOW_MINUTES = 10    # rolling window for computing a rate
BASELINE_WINDOW_HOURS = 2    # how far back to look for "what's normal for this room"

print("Loading YAMNet model...")
model = hub.load("https://tfhub.dev/google/yamnet/1")

# Load YAMNet's class names so we can find "Cough" / "Sneeze" by name,
# rather than hardcoding index numbers that could be wrong.
class_map_path = model.class_map_path().numpy().decode("utf-8")
class_names = []
with urllib.request.urlopen(class_map_path) as f:
    reader = csv.reader(io.TextIOWrapper(f, "utf-8"))
    next(reader)  # skip header
    class_names = [row[2] for row in reader]

TARGET_INDICES = {
    name: i for i, name in enumerate(class_names)
    if name.lower() in ("cough", "sneeze")
}
print("Tracking classes:", TARGET_INDICES)

# Rolling log of (timestamp, label) for events above threshold
event_log = collections.deque()


def classify_chunk(audio_chunk: np.ndarray):
    """Runs one audio chunk through YAMNet, returns any detected cough/sneeze events."""
    waveform = audio_chunk.astype(np.float32) / 32768.0  # int16 -> float32 [-1, 1]
    scores, embeddings, spectrogram = model(waveform)
    scores_np = scores.numpy().mean(axis=0)  # average over sub-frames in this chunk

    detected = []
    for label, idx in TARGET_INDICES.items():
        if scores_np[idx] >= CONFIDENCE_THRESHOLD:
            detected.append((label, float(scores_np[idx])))
    return detected


def current_rate(window_minutes=EVENT_WINDOW_MINUTES):
    """Events per minute over the recent window."""
    cutoff = time.time() - window_minutes * 60
    recent = [t for t, _ in event_log if t >= cutoff]
    return len(recent) / window_minutes


def is_rate_abnormal(baseline_hours=BASELINE_WINDOW_HOURS):
    """
    Compares the current short-term rate to this room's own longer-term
    baseline average. No universal 'normal cough rate' exists -- what's
    normal varies hugely by room type, season, and time of day -- so we
    flag a spike relative to the room's own recent history instead.
    """
    now = time.time()
    baseline_cutoff = now - baseline_hours * 3600
    baseline_events = [t for t, _ in event_log if t >= baseline_cutoff]
    baseline_rate = len(baseline_events) / (baseline_hours * 60)  # per minute

    recent_rate = current_rate()

    if baseline_rate == 0:
        # No history yet -- can't judge abnormality, just report the raw rate
        return {"abnormal": False, "recent_rate": recent_rate, "baseline_rate": 0}

    ratio = recent_rate / baseline_rate
    return {
        "abnormal": ratio >= 2.0,   # recent rate is 2x+ the room's own baseline
        "recent_rate": round(recent_rate, 2),
        "baseline_rate": round(baseline_rate, 2),
        "ratio": round(ratio, 2),
    }


def listen_loop(backend_url=None, room_id="room_1", lat=0.0, lng=0.0,
                 get_presence_count=None, report_interval_seconds=60):
    """
    Main loop: capture audio, classify, log events, periodically report.
    get_presence_count: optional function returning the current IR sensor
    count (call your IR sensor code here once it's written) -- pass None
    to just report 0 until that piece exists.
    """
    last_report = time.time()

    def audio_callback(indata, frames, time_info, status):
        chunk = indata[:, 0]
        events = classify_chunk(chunk)
        now = time.time()
        for label, score in events:
            event_log.append((now, label))
            print(f"[{time.strftime('%H:%M:%S')}] Detected {label} (score={score:.2f})")

        # Drop events older than our longest window, so the log doesn't grow forever
        cutoff = now - BASELINE_WINDOW_HOURS * 3600
        while event_log and event_log[0][0] < cutoff:
            event_log.popleft()

    with sd.InputStream(
        channels=1,
        samplerate=SAMPLE_RATE,
        blocksize=int(SAMPLE_RATE * CHUNK_SECONDS),
        dtype="int16",
        callback=audio_callback,
    ):
        print("Listening...")
        while True:
            time.sleep(1)
            if backend_url and (time.time() - last_report) >= report_interval_seconds:
                status = is_rate_abnormal()
                presence_count = get_presence_count() if get_presence_count else 0
                payload = {
                    "room_id": room_id, "lat": lat, "lng": lng,
                    "ratio": status.get("ratio", 0), "presence_count": presence_count,
                }
                try:
                    import requests
                    requests.post(backend_url, json=payload, timeout=10)
                except Exception as e:
                    print("Failed to report to backend:", e)
                last_report = time.time()


if __name__ == "__main__":
    # Replace lat/lng with this room's actual fixed location
    listen_loop(
        backend_url="http://YOUR_VULTR_IP:5000/api/room-reading",
        room_id="room_1", lat=45.4215, lng=-75.6972,
        get_presence_count=ir_sensor.get_presence_count,
    )
