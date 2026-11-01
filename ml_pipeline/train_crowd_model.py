"""Train the CampuSense crowd model from a real college TIMETABLE (15-minute resolution).

Run from the project root:   python ml_pipeline/train_crowd_model.py
Output:                      ml_pipeline/crowd_model.pkl   (back up your old one first)

HOW IT WORKS
Crowd level is 0 = Low, 1 = Medium, 2 = High. For each type of place, SCHEDULE lists the
time windows when it is busy. Anything not listed is Low. The script turns those windows
into training data (with a little random blur at the edges, like real life) and trains
XGBoost on:  hour (decimal, 8.25 = 8:15), location_id, is_event.

Windows marked  # GIVEN  come from the college timetable you described.
Windows marked  # ASSUMED  are my guesses. Edit them to match reality, then retrain.
"""
import json
import pickle

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

SEED = 42
REPEATS = 40  # noisy samples per (location, time slot, event flag)
START, END, STEP = 8.0, 18.0, 0.25  # modelled day: 8:00 to 18:00 in 15-minute steps


def T(s):
    """'8:30' -> 8.5"""
    h, m = s.split(":")
    return int(h) + int(m) / 60


# ----------------------------------------------------------------------------------------
# TIMETABLE: (from, to, level). Level 2 = High, 1 = Medium. Not listed = Low.
# College starts 9:00 and ends 3:15 PM.
# ----------------------------------------------------------------------------------------
SCHEDULE = {
    # Main gate: crowded ONLY when students arrive (before 9:00) and leave (3:15 PM)
    "gate": [
        ("8:00", "8:15", 1),
        ("8:15", "9:15", 2),    # GIVEN: college starts 9:00
        ("9:15", "9:30", 1),
        ("14:45", "15:00", 1),
        ("15:00", "15:45", 2),  # GIVEN: leaving time 3:15
        ("15:45", "16:15", 1),
    ],
    # Canteens: morning 8:30 and the 11:00 break are crowded
    "food": [
        ("8:00", "8:15", 1),
        ("8:15", "9:00", 2),    # GIVEN: 8:30 morning rush
        ("9:00", "9:15", 1),
        ("10:45", "11:30", 2),  # GIVEN: 11:00 break
        ("11:30", "11:45", 1),
        ("12:15", "12:45", 1),  # ASSUMED: lunch break
        ("12:45", "13:30", 2),  # ASSUMED: lunch break
        ("13:30", "14:00", 1),  # ASSUMED
        ("15:15", "16:30", 1),  # ASSUMED: snacks after class
    ],
    # Gym: early morning and evening
    "gym": [
        ("8:00", "9:00", 2),    # GIVEN: early morning
        ("9:00", "9:30", 1),
        ("15:30", "16:15", 1),
        ("16:15", "18:15", 2),  # GIVEN: evening
    ],
    # Hostel: students leave in the morning and come back after class
    "hostel": [
        ("8:00", "8:45", 2),    # ASSUMED
        ("12:30", "13:30", 1),  # ASSUMED: lunch
        ("15:15", "16:15", 2),  # ASSUMED: back from class
        ("17:30", "18:15", 1),  # ASSUMED
    ],
    # Library: busy after classes and in free hours
    "library": [
        ("9:15", "10:45", 1),   # ASSUMED
        ("11:00", "12:30", 1),  # ASSUMED
        ("13:00", "15:15", 1),  # ASSUMED
        ("15:30", "17:00", 2),  # ASSUMED
        ("17:00", "18:15", 1),  # ASSUMED
    ],
    # Department / classroom blocks: arrival rush, classes, leaving rush
    "academic": [
        ("8:30", "9:15", 2),    # arrival before 9:00 start
        ("9:15", "12:30", 1),   # ASSUMED: classes in session
        ("13:30", "15:00", 1),  # ASSUMED: afternoon classes
        ("15:00", "15:45", 2),  # leaving at 3:15
        ("15:45", "16:30", 1),
    ],
    # Offices (admin, help desk, placement)
    "office": [
        ("9:00", "9:30", 1),    # ASSUMED
        ("9:30", "11:30", 2),   # ASSUMED
        ("11:30", "13:00", 1),  # ASSUMED
        ("14:00", "16:00", 1),  # ASSUMED
    ],
    # Quiet rooms (staff room, research centre)
    "quiet": [
        ("10:45", "11:30", 1),  # ASSUMED: break time
    ],
    # Indoor stadium: sports after class
    "stadium": [
        ("16:00", "17:00", 1),  # ASSUMED
        ("17:00", "18:15", 2),  # ASSUMED
    ],
    # Memorial / hall: quiet unless there is an event
    "hall": [],
}

# "Campus Event Ongoing?" ticked: +1 level for these places between 9:00 and 4:30 PM
EVENT_BUMP = {"gate": 1, "food": 1, "office": 1, "academic": 1, "library": 1,
              "hostel": 0, "gym": 0, "quiet": 0, "stadium": 0, "hall": 0}
# ...and event venues are packed from 10:00 to 4:30 PM
EVENT_VENUES = {"stadium", "hall"}


def kind(name):
    n = name.lower()
    if "canteen" in n:
        return "food"
    if "library" in n:
        return "library"
    if "gate" in n:
        return "gate"
    if "gym" in n:
        return "gym"
    if "hostel" in n:
        return "hostel"
    if "stadium" in n:
        return "stadium"
    if "memorial" in n:
        return "hall"
    if "placement" in n or "help desk" in n or "admin" in n:
        return "office"
    if "climate" in n or "staff room" in n:
        return "quiet"
    return "academic"  # departments, blocks


def level_at(k, t, event):
    lvl = 0
    for a, b, v in SCHEDULE[k]:
        if T(a) <= t < T(b):
            lvl = max(lvl, v)
    if event:
        if k in EVENT_VENUES:
            if T("10:00") <= t < T("16:30"):
                lvl = 2
            elif T("9:30") <= t < T("17:30"):
                lvl = max(lvl, 1)
        elif T("9:00") <= t < T("16:30"):
            lvl = min(2, lvl + EVENT_BUMP[k])
    return lvl


def make_data(nodes):
    rng = np.random.default_rng(SEED)
    slots = np.arange(START, END + 1e-9, STEP)
    rows = []
    for name, d in nodes.items():
        k = kind(name)
        for t in slots:
            for event in (0, 1):
                for _ in range(REPEATS):
                    tj = t + rng.normal(0, 5 / 60)  # blur window edges by about 5 minutes
                    lvl = level_at(k, tj, event)
                    if rng.random() < 0.03:  # 3% label noise
                        lvl = int(np.clip(lvl + rng.choice([-1, 1]), 0, 2))
                    rows.append((round(float(t), 2), d["id"], event, lvl))
    return pd.DataFrame(rows, columns=["hour", "location_id", "is_event", "crowd"])


def fmt(t):
    h, m = int(t), int(round((t % 1) * 60))
    return f"{(h % 12) or 12}:{m:02d}"


if __name__ == "__main__":
    with open("data/campus_nodes.json") as f:
        nodes = json.load(f)

    df = make_data(nodes)
    print(f"{len(df)} rows, {len(nodes)} locations")
    X, y = df[["hour", "location_id", "is_event"]], df["crowd"]
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=SEED, stratify=y)

    model = XGBClassifier(
        n_estimators=300, max_depth=10, learning_rate=0.1, subsample=0.9,
        objective="multi:softprob", eval_metric="mlogloss", random_state=SEED,
    )
    model.fit(X_tr, y_tr)
    print("Test accuracy (noisy data):", round(accuracy_score(y_te, model.predict(X_te)), 3))

    # How well does the model reproduce the clean timetable at every 15-minute slot?
    slots = np.arange(START, END + 1e-9, STEP)
    hit = tot = 0
    for name, d in nodes.items():
        for ev in (0, 1):
            truth = [level_at(kind(name), t, ev) for t in slots]
            pred = model.predict(pd.DataFrame({"hour": slots, "location_id": d["id"], "is_event": ev}))
            hit += sum(int(a == b) for a, b in zip(truth, pred))
            tot += len(slots)
    print(f"Matches the timetable at {hit / tot:.1%} of 15-minute slots")

    with open("ml_pipeline/crowd_model.pkl", "wb") as f:
        pickle.dump(model, f)
    print("Saved ml_pipeline/crowd_model.pkl\n")

    # Sanity table (no event): L / M / H at key times
    show = [8.0, 8.5, 9.0, 9.5, 11.0, 12.0, 13.0, 14.0, 15.0, 15.25, 16.0, 17.0, 18.0]
    print("Time:".ljust(34) + " ".join(f"{fmt(t):>5s}" for t in show))
    for name, d in nodes.items():
        p = model.predict(pd.DataFrame({"hour": show, "location_id": d["id"], "is_event": 0}))
        print(name[:32].ljust(34) + " ".join(f"{'LMH'[int(v)]:>5s}" for v in p))