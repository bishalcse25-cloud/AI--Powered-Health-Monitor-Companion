"""
train_model.py - standalone ML training script (NOT imported by the app).

What it does, in order:
  1. Generates a synthetic ("dummy") health dataset - no database, no real
     patient data. Each row has four vitals and a risk label.
  2. Trains a basic scikit-learn RandomForestClassifier on it.
  3. Prints a quick accuracy / report so you can see it learned something.
  4. Saves the fitted model to  app/ml/model.joblib  - exactly where
     app/ml/predict.py loads it from at import time.

Run it from the project root (Command Prompt / cmd.exe):

    python train_model.py

Requirements (install once, into your virtualenv):

    pip install scikit-learn numpy joblib

Feature order is fixed and MUST stay in sync with app/ml/predict.py:
    [heart_rate_bpm, spo2_percent, body_temp_c, sleep_hours]
Label classes: "LOW", "ELEVATED", "HIGH_ATTENTION"

Re-run this whenever the feature list or the synthetic profiles change, then
restart the API so predict.py picks up the new artifact.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

try:
    import joblib
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import classification_report
    from sklearn.model_selection import train_test_split
except ImportError:  # pragma: no cover - friendly message for a beginner setup
    raise SystemExit(
        "scikit-learn / joblib is not installed in this environment.\n"
        "Install first:  pip install scikit-learn numpy joblib"
    )


FEATURE_NAMES = ["heart_rate_bpm", "spo2_percent", "body_temp_c", "sleep_hours"]
CLASS_NAMES = ["LOW", "ELEVATED", "HIGH_ATTENTION"]
# Must match app/ml/predict.py::MODEL_PATH exactly.
OUTPUT_PATH = Path(__file__).parent / "app" / "ml" / "model.joblib"
RANDOM_SEED = 42
N_SAMPLES = 3000


def generate_dummy_data(n_samples: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Build a synthetic dataset that roughly imitates how vitals look at three
    risk levels. This is fake data for wiring/testing only - it is NOT
    medically validated and must not be used for real risk scoring.
    """
    rng = np.random.default_rng(seed)

    # Rough per-class distributions: (mean, std) for each vital.
    profiles = {
        "LOW": {
            "heart_rate_bpm": (72, 8),
            "spo2_percent": (98, 1.0),
            "body_temp_c": (36.8, 0.25),
            "sleep_hours": (7.5, 1.0),
        },
        "ELEVATED": {
            "heart_rate_bpm": (98, 10),
            "spo2_percent": (94, 1.5),
            "body_temp_c": (37.7, 0.4),
            "sleep_hours": (5.5, 1.2),
        },
        "HIGH_ATTENTION": {
            "heart_rate_bpm": (100, 18),
            "spo2_percent": (89, 3.0),
            "body_temp_c": (39.0, 0.7),
            "sleep_hours": (4.0, 1.5),
        },
    }

    rows: list[list[float]] = []
    labels: list[str] = []

    per_class = n_samples // len(CLASS_NAMES)
    for label in CLASS_NAMES:
        p = profiles[label]
        for _ in range(per_class):
            hr = rng.normal(*p["heart_rate_bpm"])
            spo2 = rng.normal(*p["spo2_percent"])
            temp = rng.normal(*p["body_temp_c"])
            sleep = rng.normal(*p["sleep_hours"])

            # Clip to physically plausible ranges.
            hr = float(np.clip(hr, 35, 200))
            spo2 = float(np.clip(spo2, 70, 100))
            temp = float(np.clip(temp, 34.0, 42.0))
            sleep = float(np.clip(sleep, 0.0, 14.0))

            rows.append([hr, spo2, temp, sleep])
            labels.append(label)

    X = np.array(rows, dtype=float)
    y = np.array(labels, dtype=object)

    # Shuffle so the classes aren't in blocks.
    order = rng.permutation(len(X))
    return X[order], y[order]


def main() -> None:
    print(f"Generating {N_SAMPLES} synthetic samples...")
    X, y = generate_dummy_data(N_SAMPLES, RANDOM_SEED)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_SEED, stratify=y
    )

    print("Training RandomForestClassifier...")
    model = RandomForestClassifier(
        n_estimators=200,
        max_depth=8,
        random_state=RANDOM_SEED,
        class_weight="balanced",
    )
    model.fit(X_train, y_train)

    accuracy = model.score(X_test, y_test)
    print(f"\nHold-out accuracy: {accuracy:.3f}\n")
    print(classification_report(y_test, model.predict(X_test)))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, OUTPUT_PATH)

    print(f"Saved model -> {OUTPUT_PATH}")
    print(f"Feature order: {FEATURE_NAMES}")
    print(f"Classes: {list(model.classes_)}")


if __name__ == "__main__":
    main()
