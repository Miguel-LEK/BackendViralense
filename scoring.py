"""
Composite "sickness likelihood" scoring module, matched to what your real
data sources actually provide:
  - pulse_rate:      from Presage API OR the rPPG fallback
  - breathing_rate:  from Presage API only (rPPG fallback doesn't measure this)
  - self_reported:   from your web form's symptom checkboxes

Plug this into your backend API: receive real metrics from checkin_endpoint,
call compute_composite_score(), store the result alongside location/timestamp.
"""

NORMAL_RANGES = {
    "pulse_rate":      {"low": 60, "high": 100},   # bpm
    "breathing_rate":  {"low": 12, "high": 20},    # breaths/min
}

EXTREME_OFFSETS = {
    "pulse_rate": 40,       # 100 -> 140 bpm hits max concern
    "breathing_rate": 12,   # 20 -> 32 breaths/min hits max concern
}

# Relative importance of each signal. Must sum to 1.0.
# breathing_rate only contributes when available (Presage path, not rPPG-only).
WEIGHTS = {
    "pulse_rate": 0.45,
    "breathing_rate": 0.25,
    "self_reported": 0.30,
}


def _deviation_score(value, metric_name, baseline=None):
    """0.0-1.0 concern score for a single metric, vs. population or personal baseline."""
    if value is None:
        return None  # signals "not available" so we can re-normalize weights below

    rng = NORMAL_RANGES[metric_name]
    low, high = rng["low"], rng["high"]

    if baseline is not None:
        span = high - low
        low, high = baseline - span / 2, baseline + span / 2

    if low <= value <= high:
        return 0.0

    distance = (low - value) if value < low else (value - high)
    return min(distance / EXTREME_OFFSETS[metric_name], 1.0)


def compute_composite_score(pulse_rate=None, breathing_rate=None,
                             self_reported: float = 0.0, baselines: dict = None) -> dict:
    """
    pulse_rate: float or None (None if the rPPG/Presage call failed this round)
    breathing_rate: float or None (only available via the Presage path)
    self_reported: 0-1, e.g. (symptoms checked / total symptoms)
    baselines: optional {"pulse_rate": float, "breathing_rate": float} --
               that user's own resting values from an earlier check-in, if you have one

    Returns: {"score": 0-100, "tier": "normal"|"mild"|"high", "breakdown": {...}}
    """
    baselines = baselines or {}

    raw_scores = {
        "pulse_rate": _deviation_score(pulse_rate, "pulse_rate", baselines.get("pulse_rate")),
        "breathing_rate": _deviation_score(breathing_rate, "breathing_rate", baselines.get("breathing_rate")),
        "self_reported": min(max(self_reported, 0.0), 1.0),
    }

    # Only weight the signals that actually came through this round --
    # if breathing_rate is missing (e.g. rPPG-only path), redistribute its
    # weight proportionally across whatever IS available, rather than
    # silently treating "missing" as "normal".
    available = {k: v for k, v in raw_scores.items() if v is not None}
    total_weight = sum(WEIGHTS[k] for k in available)

    weighted_sum = sum(available[k] * WEIGHTS[k] for k in available) / total_weight
    score = round(weighted_sum * 100, 1)
    tier = "normal" if score < 30 else "mild" if score < 60 else "high"

    return {"score": score, "tier": tier, "breakdown": raw_scores}


if __name__ == "__main__":
    # Example 1: full Presage data available
    print(compute_composite_score(pulse_rate=112, breathing_rate=23, self_reported=0.4))

    # Example 2: rPPG fallback only -- no breathing rate
    print(compute_composite_score(pulse_rate=105, breathing_rate=None, self_reported=0.4))
