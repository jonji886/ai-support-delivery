import os


def threshold(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


INTENT_MIN_CONFIDENCE = threshold("INTENT_MIN_CONFIDENCE", 0.70)
INTENT_MIN_MARGIN = threshold("INTENT_MIN_MARGIN", 0.10)
POLICY_MIN_EVIDENCE_SCORE = threshold("POLICY_MIN_EVIDENCE_SCORE", threshold("POLICY_MIN_SIMILARITY", 0.65))
