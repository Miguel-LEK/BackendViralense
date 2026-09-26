# Sickness Zone Tracker — README

Estimates sickness likelihood by area, using personal check-ins (webcam vitals
+ self-reported symptoms) and room-level ambient sensors (mic + IR), displayed
as a heatmap.

## Architecture

```
PERSONAL CHECK-IN (website, any device)
checkin.js → user's browser captures a webcam clip + symptom form + location
           → sends to server.py's /api/checkin

ROOM MONITORING (Raspberry Pi, one per physical room)
ir_sensor.py        → counts foot traffic via the IR sensor
mic_cough_detector.py → listens for coughs/sneezes, imports ir_sensor.py,
                         POSTs a combined reading to server.py's /api/room-reading

BACKEND (Vultr VPS)
server.py → receives both kinds of readings, scores them via scoring.py,
            stores them in TigerData (Postgres + TimescaleDB), and serves
            aggregated zone data via /api/zones

FRONTEND (your React app, not included here)
Polls GET /api/zones and colors a map by average score per area
```

## Files and where each one runs

| File | Runs on | Purpose |
|---|---|---|
| `server.py` | Vultr | Main backend. All other pieces talk to this. |
| `scoring.py` | Vultr | Turns pulse rate / breathing rate / symptoms into a 0–100 score + tier. |
| `presage_capture.py` | Vultr | Calls Presage's API to get real pulse + breathing rate from a webcam clip. |
| `rppg_fallback.py` | Vultr | Backup: computes heart rate from webcam video directly (no external API). Use if Presage isn't working. |
| `requirements.txt` | Vultr | Python dependencies — `pip install -r requirements.txt` |
| `checkin.js` | Website frontend | "New Check-In" button: captures location + webcam clip + symptoms, submits them. |
| `mic_cough_detector.py` | Raspberry Pi | Listens to the room mic, detects coughs/sneezes, reports the rate. |
| `ir_sensor.py` | Raspberry Pi | Counts presence/foot-traffic events from the IR sensor. |

## Setup

### 1. Database (TigerData)
1. Create a free service at [console.cloud.timescale.com](https://console.cloud.timescale.com)
2. Copy its connection string (a standard `postgresql://...` URL)

### 2. Backend (Vultr)
1. Spin up a Vultr VPS (Ubuntu 22.04 is fine)
2. Copy `server.py`, `scoring.py`, `presage_capture.py`, `rppg_fallback.py`,
   `requirements.txt` to it
3. `pip install -r requirements.txt`
4. `export DATABASE_URL="<your TigerData connection string>"`
5. **Test Presage first, before anything else**: `python presage_capture.py`
   — its pip package is archived/unmaintained, so confirm it still connects
   before building on it. If it fails, edit the import at the top of
   `server.py` to use `rppg_fallback.py` instead — it needs no external
   service and is already written as a drop-in replacement for pulse rate.
6. `python server.py` (auto-creates the database table on first run). Use
   `gunicorn server:app` instead for anything beyond a quick demo.
7. Open the port in Vultr's firewall settings (or put nginx in front on port 80)

### 3. Room node (Raspberry Pi)
1. Copy `mic_cough_detector.py` and `ir_sensor.py` to the same folder
2. `pip install RPi.GPIO tensorflow tensorflow_hub sounddevice numpy requests`
3. In `mic_cough_detector.py`'s `__main__` block, set the room's real `lat`/`lng`
   and your Vultr server's IP
4. In `ir_sensor.py`, confirm `IR_SENSOR_PIN` matches your actual wiring
5. `python mic_cough_detector.py`

### 4. Frontend
1. Wire the button in your UI to `startNewCheckIn()` / `submitCheckIn()` from `checkin.js`
2. Point its `fetch()` URL at your Vultr server's `/api/checkin`
3. Have your map component poll `GET http://YOUR_VULTR_IP:5000/api/zones`

## Known risks / test early

- **Presage's Python package is archived (unmaintained since Sep 2025).**
  It may still work since it just hits their REST API, but test it first —
  see step 5 above. `rppg_fallback.py` is your safety net.
- **YAMNet's cough/sneeze confidence threshold (0.3 in `mic_cough_detector.py`)
  is untested against real room noise.** Budget time to test it against
  actual background chatter/HVAC noise and adjust.
- **Running the mic classifier on a Raspberry Pi may be CPU-heavy** —
  test it runs smoothly before relying on it live.
- No accounts/auth exist by design (check-ins are anonymous and ephemeral) —
  that's intentional, not a bug, but worth stating plainly if judges ask.

## Environment variables

| Variable | Where | Value |
|---|---|---|
| `DATABASE_URL` | Vultr (server.py) | TigerData connection string |
| `API_KEY` | Vultr (presage_capture.py) | Your Presage API key (hardcode or move to an env var) |
