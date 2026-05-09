from __future__ import annotations


def clamp(value: float, low: float, high: float) -> float:
    if value < low:
        return low
    if value > high:
        return high
    return value


def normalize_0_100(value: float) -> float:
    return clamp(value, 0.0, 100.0)


def to_trust_score(score_0_100: float) -> float:
    trust_score = round(score_0_100 / 10.0, 1)
    return clamp(trust_score, 1.0, 10.0)
