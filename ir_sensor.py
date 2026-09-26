"""
Counts presence/foot-traffic events from the IR reflective sensor,
wired to a GPIO pin on the Raspberry Pi (equivalent to the Arduino
version from earlier, but using RPi.GPIO instead of digitalRead()).

Install: pip install RPi.GPIO
"""

import time
import collections
import RPi.GPIO as GPIO

IR_SENSOR_PIN = 4  # BCM numbering -- matches the D4 wiring from your Arduino tests
DEBOUNCE_MS = 300  # ignore repeat triggers within this window (one object = one count)

GPIO.setmode(GPIO.BCM)
GPIO.setup(IR_SENSOR_PIN, GPIO.IN)

event_log = collections.deque()
_last_trigger_time = 0


def _on_detection(channel):
    global _last_trigger_time
    now = time.time()
    if (now - _last_trigger_time) * 1000 < DEBOUNCE_MS:
        return  # too soon after the last trigger, likely the same object still in view
    _last_trigger_time = now
    event_log.append(now)
    print(f"[{time.strftime('%H:%M:%S')}] Presence detected")


# Most of these modules read LOW when an obstacle is detected (same as the
# Arduino version) -- change to GPIO.RISING if yours behaves the opposite way.
GPIO.add_event_detect(IR_SENSOR_PIN, GPIO.FALLING, callback=_on_detection, bouncetime=DEBOUNCE_MS)


def get_presence_count(window_minutes=10):
    """Returns how many presence events happened in the last N minutes."""
    cutoff = time.time() - window_minutes * 60
    while event_log and event_log[0] < cutoff:
        event_log.popleft()
    return len(event_log)


def cleanup():
    GPIO.cleanup()


if __name__ == "__main__":
    print("Watching IR sensor... (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(5)
            print("Count in last 10 min:", get_presence_count())
    except KeyboardInterrupt:
        cleanup()
