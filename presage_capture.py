"""
Captures a real webcam clip and sends it to Presage's Physiology API to get
back real pulse rate (hr) and breathing rate (rr) readings.

KNOWN RISK: the presage_technologies pip package was archived by its
maintainers in Sep 2025 (no further updates). It may still work fine since
it's just hitting their REST API, but TEST THIS FIRST THING TONIGHT with
your actual API key before building anything else on top of it. If it's
dead, use rppg_fallback.py instead -- it needs no external service at all.

Install: pip install presage_technologies opencv-python
Get an API key: https://physiology.presagetech.com
"""

import cv2
import time
from presage_technologies import Physiology

API_KEY = "your_api_key_here"
CLIP_SECONDS = 20          # Presage recommends ~20s windows for reliable results
FPS = 15                   # must be >10 fps per their guidelines
OUTPUT_PATH = "/tmp/clip.mp4"

physio = Physiology(API_KEY)


def record_clip(path=OUTPUT_PATH, seconds=CLIP_SECONDS, fps=FPS):
    """Records a real clip from the default webcam."""
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FPS, fps)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, (width, height))

    frames_needed = seconds * fps
    for _ in range(frames_needed):
        ok, frame = cap.read()
        if not ok:
            break
        writer.write(frame)

    cap.release()
    writer.release()
    return path


def get_vitals(path=OUTPUT_PATH):
    """
    Uploads the clip and retrieves real results.
    Confirmed from Presage's actual package docs:
      - queue_processing_hr_rr(path) -> video_id
      - retrieve_result(video_id) -> {"hr": {timestamp: value, ...}, "rr": {...}}
      They recommend waiting ~half the clip length before the first check.
    """
    video_id = physio.queue_processing_hr_rr(path)
    time.sleep(CLIP_SECONDS / 2)

    for attempt in range(6):  # retry for up to ~30s total if not ready yet
        data = physio.retrieve_result(video_id)
        if data and data.get("hr") and data.get("rr"):
            hr_values = list(data["hr"].values())
            rr_values = list(data["rr"].values())
            return {
                "pulse_rate": sum(hr_values) / len(hr_values),
                "breathing_rate": sum(rr_values) / len(rr_values),
            }
        time.sleep(5)

    return None  # not ready / low-quality video, no vitals extracted


def capture_and_send_to_backend(backend_url, checkin_id, lat, lng):
    import requests
    record_clip()
    vitals = get_vitals()
    if vitals is None:
        print("No vitals returned -- check video quality/lighting, or Presage API status")
        return
    payload = {"checkin_id": checkin_id, "lat": lat, "lng": lng, **vitals}
    requests.post(backend_url, json=payload, timeout=15)


if __name__ == "__main__":
    # Quick manual test -- run this FIRST tonight to confirm the API still works
    record_clip()
    print(get_vitals())
