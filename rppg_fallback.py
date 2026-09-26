"""
Computes real heart rate directly from webcam video using remote
photoplethysmography (rPPG): the face's skin tone shifts very slightly
with each heartbeat due to blood flow changes. We track the average green
channel intensity of the face region over time and find the dominant
frequency -- that frequency IS the heart rate.

This needs no external API or account -- everything runs locally.
Accuracy is lower than a dedicated medical device, but it's real signal
extraction from real video, well-precedented in research (this is the same
core idea used by several published rPPG papers).

Install: pip install opencv-python numpy scipy
"""

import cv2
import numpy as np
from scipy.signal import butter, filtfilt, find_peaks

FACE_CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def bandpass_filter(signal, fps, low_hz=0.7, high_hz=4.0):
    """
    Keeps only frequencies matching plausible human heart rates.
    0.7-4.0 Hz = 42-240 bpm, a generous safety margin around normal range.
    """
    nyquist = fps / 2
    b, a = butter(3, [low_hz / nyquist, high_hz / nyquist], btype="band")
    return filtfilt(b, a, signal)


def extract_heart_rate(video_path, duration_seconds=20):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30

    green_signal = []

    while len(green_signal) < duration_seconds * fps:
        ok, frame = cap.read()
        if not ok:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = FACE_CASCADE.detectMultiScale(gray, 1.3, 5)

        if len(faces) == 0:
            continue  # skip frames where no face is found

        x, y, w, h = faces[0]
        # Use forehead region specifically -- less affected by talking/expressions
        forehead = frame[y : y + int(h * 0.25), x + int(w * 0.25) : x + int(w * 0.75)]
        green_channel = forehead[:, :, 1]  # BGR order -- index 1 is green
        green_signal.append(np.mean(green_channel))

    cap.release()

    if len(green_signal) < fps * 5:  # need at least ~5 seconds of good signal
        return None

    signal = np.array(green_signal)
    signal = signal - np.mean(signal)  # remove DC offset
    filtered = bandpass_filter(signal, fps)

    # Find the dominant frequency via FFT -- that's the heart rate
    fft_vals = np.abs(np.fft.rfft(filtered))
    freqs = np.fft.rfftfreq(len(filtered), d=1.0 / fps)

    valid_range = (freqs >= 0.7) & (freqs <= 4.0)
    dominant_freq = freqs[valid_range][np.argmax(fft_vals[valid_range])]

    heart_rate_bpm = dominant_freq * 60
    return round(heart_rate_bpm, 1)


def record_and_measure(duration_seconds=20, output_path="/tmp/rppg_clip.mp4"):
    """Records from the default webcam, then measures heart rate from it."""
    cap = cv2.VideoCapture(0)
    fps = 30
    cap.set(cv2.CAP_PROP_FPS, fps)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    for _ in range(duration_seconds * fps):
        ok, frame = cap.read()
        if not ok:
            break
        writer.write(frame)

    cap.release()
    writer.release()

    return extract_heart_rate(output_path, duration_seconds)


if __name__ == "__main__":
    print("Recording 20s clip and measuring heart rate...")
    print("Sit still, face the camera, and make sure your face is well-lit.")
    hr = record_and_measure()
    print(f"Estimated heart rate: {hr} bpm" if hr else "Could not extract a reliable signal")
