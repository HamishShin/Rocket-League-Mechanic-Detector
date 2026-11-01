import csv
import math
from collections import defaultdict, Counter
from pathlib import Path


BASE = Path("data/replays")

TIMELINE_FILE = BASE / "timeline.csv"
CONTACTS_FILE = BASE / "ball_contacts.csv"
EVENTS_FILE = BASE / "mechanic_events.csv"
BOOST_FILE = BASE / "boost_amount_changes.csv"

OUTPUT_FILE = BASE / "air_dribble_sequence_candidates.csv"
LABEL_FILE = BASE / "manual_air_dribble_labels.csv"

# Sequence thresholds. These are initial settings for validation,
# not universal Rocket League mechanics thresholds.
MIN_CONTACT_GAP = 0.15
MAX_CONTACT_GAP = 2.05
JUMP_LOOKBACK = 3.0
BOOST_LOOKBACK = 1.5

NEAR_DISTANCE = 600.0
ABOVE_MARGIN = 25.0
AIRBORNE_Z = 120.0
MIN_AIRBORNE_FRACTION = 0.30
MIN_ABOVE_NEAR_FRACTION = 0.50
MIN_MAX_CAR_Z = 180.0


# ============================================================
# MANUALLY REVIEWED EXAMPLES
# These are labels from your visual review, not predictions.
# ============================================================

MANUAL_REVIEWS = [
    {
        "start": 331.7647,
        "end": 331.7647,
        "car": "car4",
        "label": "not_air_dribble",
        "note": "Jump and feathering, but insufficient height and no multiple aerial touches.",
    },
    {
        "start": 35.6640,
        "end": 35.6640,
        "car": "car3",
        "label": "flip_reset_touch_not_air_dribble",
        "note": "Flip-reset touch; no subsequent ball hit. Not an air dribble.",
    },
    {
        "start": 209.4422,
        "end": 209.4422,
        "car": "car2",
        "label": "not_air_dribble",
        "note": "Single aerial hit followed by a goal.",
    },
    {
        "start": 277.7520,
        "end": 277.7520,
        "car": "car2",
        "label": "not_air_dribble",
        "note": "Boosting and elevated, but only one ball contact.",
    },
    {
        "start": 163.4054,
        "end": 163.4054,
        "car": "car4",
        "label": "not_air_dribble",
        "note": "Kickoff.",
    },
    {
        "start": 285.0585,
        "end": 287.0417,
        "car": "car4",
        "label": "air_dribble",
        "note": "Visually reviewed air dribble sequence.",
    },
    {
        "start": 158.4058,
        "end": 158.8224,
        "car": "car1",
        "label": "not_air_dribble",
        "note": "Goal-scoring sequence, not an air dribble.",
    },
    {
        "start": 97.3431,
        "end": 97.3431,
        "car": "car2",
        "label": "not_air_dribble",
        "note": "Kickoff.",
    },
    {
        "start": 211.5255,
        "end": 211.5255,
        "car": "car1",
        "label": "not_air_dribble",
        "note": "Single aerial hit followed by a goal.",
    },
    {
        "start": 51.3991,
        "end": 51.3991,
        "car": "car1",
        "label": "not_air_dribble",
        "note": "One aerial hit; ball did not remain high enough.",
    },
    {
        "start": 313.1856,
        "end": 313.4640,
        "car": "car1",
        "label": "not_air_dribble",
        "note": "Kickoff, not an air dribble.",
    },
    {
        "start": 238.5090,
        "end": 240.4880,
        "car": "car4",
        "label": "not_air_dribble",
        "note": "Ground dribble, not an air dribble.",
    },
    {
        "start": 129.1309,
        "end": 129.6517,
        "car": "car2",
        "label": "not_air_dribble",
        "note": "50/50 challenge, not an air dribble.",
    },
]

# ============================================================
# HELPERS
# ============================================================

def num(value):
    if value is None or value == "":
        return None

    try:
        value = float(value)

        if math.isfinite(value):
            return value

    except (TypeError, ValueError):
        pass

    return None


def integer(value):
    value = num(value)

    return int(value) if value is not None else None


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(
            f"Required file not found: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        return list(csv.DictReader(f))


def position(row, prefix):
    x = num(row.get(f"{prefix}_x"))
    y = num(row.get(f"{prefix}_y"))
    z = num(row.get(f"{prefix}_z"))

    if x is None or y is None or z is None:
        return None

    return (x, y, z)


def distance(a, b):
    if a is None or b is None:
        return None

    return math.sqrt(
        (a[0] - b[0]) ** 2
        + (a[1] - b[1]) ** 2
        + (a[2] - b[2]) ** 2
    )


def contact_car(row):
    car = str(
        row.get("car", "")
    ).strip().lower()

    if car in {"car1", "car2", "car3", "car4"}:
        return car

    return None


def contact_time(row):
    return num(row.get("time_after"))


def contact_frame(row):
    return integer(row.get("frame_after"))


def nearby_manual_review(car, start_time, end_time):
    """
    Attach a manual label only when a sequence overlaps its
    reviewed time window, with a small tolerance.
    """

    tolerance = 0.40

    matches = []

    for review in MANUAL_REVIEWS:
        if review["car"] != car:
            continue

        review_start = review["start"]
        review_end = review["end"]

        gap = max(
            review_start - end_time,
            start_time - review_end,
            0.0
        )

        if gap <= tolerance:
            matches.append((gap, review))

    if not matches:
        return None

    matches.sort(key=lambda item: item[0])

    return matches[0][1]


def write_csv(path, rows, fields):
    with path.open(
        "w",
        encoding="utf-8",
        newline=""
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            extrasaction="ignore"
        )

        writer.writeheader()
        writer.writerows(rows)


# ============================================================
# LOAD TIMELINE
# ============================================================

print("Loading timeline...")

timeline_rows = read_csv(TIMELINE_FILE)

timeline = {}

for row in timeline_rows:
    frame = integer(row.get("frame"))

    if frame is not None:
        timeline[frame] = row

print("Timeline frames:", len(timeline))


# ============================================================
# LOAD CONTACTS
# ============================================================

print("Loading clustered ball contacts...")

contacts = []

for row in read_csv(CONTACTS_FILE):
    frame = contact_frame(row)
    t = contact_time(row)
    car = contact_car(row)

    if frame is None or t is None or car is None:
        continue

    contacts.append({
        "contact_id": row.get("contact_id", ""),
        "frame": frame,
        "time": t,
        "car": car,
        "min_distance": num(row.get("min_distance")),
        "ball_dv": num(row.get("ball_dv")),
    })

contacts.sort(
    key=lambda item: (item["time"], item["frame"])
)

contacts_by_car = defaultdict(list)

for contact in contacts:
    contacts_by_car[contact["car"]].append(contact)

print("Usable contacts:", len(contacts))


# ============================================================
# LOAD JUMP / BOOST STATE EVENTS
# ============================================================

print("Loading mechanic events...")

jumps = defaultdict(list)
boost_state_changes = defaultdict(list)

for row in read_csv(EVENTS_FILE):
    car = str(
        row.get("timeline_car", "")
    ).strip().lower()

    t = num(row.get("time"))
    component = str(
        row.get("component_type", "")
    ).strip()

    if car not in {"car1", "car2", "car3", "car4"}:
        continue

    if t is None:
        continue

    if component == "Jump":
        jumps[car].append(t)

    elif component == "Boost":
        boost_state_changes[car].append(t)

for car in jumps:
    jumps[car].sort()

for car in boost_state_changes:
    boost_state_changes[car].sort()


# ============================================================
# LOAD BOOST RESOURCE CHANGES
# ============================================================

print("Loading boost amount changes...")

boost_drops = defaultdict(list)

for row in read_csv(BOOST_FILE):
    car = str(
        row.get("timeline_car", "")
    ).strip().lower()

    t = num(row.get("time"))
    previous = num(row.get("previous_byte"))
    current = num(row.get("current_byte"))

    if (
        car not in {"car1", "car2", "car3", "car4"}
        or t is None
        or previous is None
        or current is None
    ):
        continue

    if current < previous:
        boost_drops[car].append(t)

for car in boost_drops:
    boost_drops[car].sort()


# ============================================================
# GEOMETRY FOR A CONTACT-TO-CONTACT SEQUENCE
# ============================================================

def analyze_geometry(car, first_frame, second_frame):
    distances = []
    heights = []
    ball_heights = []

    near_count = 0
    above_count = 0
    above_near_count = 0
    airborne_count = 0

    samples = 0

    for frame in range(
        first_frame,
        second_frame + 1
    ):
        row = timeline.get(frame)

        if row is None:
            continue

        if integer(row.get(f"{car}_active")) != 1:
            continue

        car_pos = position(row, car)
        ball_pos = position(row, "ball")

        if car_pos is None or ball_pos is None:
            continue

        d = distance(car_pos, ball_pos)

        if d is None:
            continue

        car_z = car_pos[2]
        ball_z = ball_pos[2]

        near = d <= NEAR_DISTANCE
        above = ball_z > car_z + ABOVE_MARGIN
        airborne = car_z >= AIRBORNE_Z

        samples += 1
        distances.append(d)
        heights.append(car_z)
        ball_heights.append(ball_z)

        if near:
            near_count += 1

        if above:
            above_count += 1

        if near and above:
            above_near_count += 1

        if airborne:
            airborne_count += 1

    if samples == 0:
        return {
            "samples": 0,
            "near_fraction": 0.0,
            "above_fraction": 0.0,
            "above_near_fraction": 0.0,
            "airborne_fraction": 0.0,
            "mean_distance": None,
            "mean_car_z": None,
            "max_car_z": None,
            "mean_ball_z": None,
        }

    return {
        "samples": samples,

        "near_fraction":
            near_count / samples,

        "above_fraction":
            above_count / samples,

        "above_near_fraction":
            above_near_count / samples,

        "airborne_fraction":
            airborne_count / samples,

        "mean_distance":
            sum(distances) / len(distances),

        "mean_car_z":
            sum(heights) / len(heights),

        "max_car_z":
            max(heights),

        "mean_ball_z":
            sum(ball_heights) / len(ball_heights),
    }


# ============================================================
# DETECT CONTACT PAIRS
# ============================================================

print()
print("Searching for repeated aerial contacts...")

results = []

for car, car_contacts in contacts_by_car.items():

    for i, first in enumerate(car_contacts):

        for second in car_contacts[i + 1:]:

            gap = second["time"] - first["time"]

            if gap < MIN_CONTACT_GAP:
                continue

            if gap > MAX_CONTACT_GAP:
                break

            # The second contact must occur in a later frame.
            if second["frame"] <= first["frame"]:
                continue

            geometry = analyze_geometry(
                car,
                first["frame"],
                second["frame"]
            )

            if geometry["samples"] < 5:
                continue

            # Jump should occur shortly before the first contact.
            recent_jump = any(
                first["time"] - JUMP_LOOKBACK
                <= t
                <= first["time"] + 0.10
                for t in jumps[car]
            )

            # Boost evidence in the approach/contact sequence.
            # Amount decreases indicate consumption, not proof
            # of exact feathered-button timing.
            resource_drops = [
                t
                for t in boost_drops[car]
                if (
                    first["time"] - BOOST_LOOKBACK
                    <= t
                    <= second["time"] + 0.05
                )
            ]

            recent_boost_state_changes = [
                t
                for t in boost_state_changes[car]
                if (
                    first["time"] - BOOST_LOOKBACK
                    <= t
                    <= second["time"] + 0.05
                )
            ]

            boost_evidence = (
                len(resource_drops) >= 1
                or len(recent_boost_state_changes) >= 2
            )

            # Both touches should be spatially plausible.
            close_first = (
                first["min_distance"] is not None
                and first["min_distance"] <= 350
            )

            close_second = (
                second["min_distance"] is not None
                and second["min_distance"] <= 350
            )

            high_enough = (
                geometry["mean_car_z"] is not None
                and geometry["max_car_z"] is not None
                and geometry["max_car_z"] >= MIN_MAX_CAR_Z
                and geometry["mean_car_z"] >= 100.0
            )

            near_and_above = (
                geometry["above_near_fraction"]
                >= MIN_ABOVE_NEAR_FRACTION
            )

            airborne_enough = (
                geometry["airborne_fraction"]
                >= MIN_AIRBORNE_FRACTION
            )

            passes_sequence = (
                recent_jump
                and boost_evidence
                and close_first
                and close_second
                and high_enough
                and near_and_above
                and airborne_enough
            )

            # Score is a ranking aid, not a probability.
            score = (
                0.15 * (1.0 if recent_jump else 0.0)
                + 0.15 * (1.0 if boost_evidence else 0.0)
                + 0.15 * (1.0 if close_first and close_second else 0.0)
                + 0.20 * geometry["above_near_fraction"]
                + 0.15 * geometry["airborne_fraction"]
                + 0.10 * geometry["near_fraction"]
                + 0.10 * (
                    1.0 if high_enough else 0.0
                )
            )

            manual = nearby_manual_review(
                car,
                first["time"],
                second["time"]
            )

            results.append({
                "car": car,

                "first_contact_id":
                    first["contact_id"],

                "first_frame":
                    first["frame"],

                "first_time":
                    round(first["time"], 4),

                "first_contact_distance":
                    (
                        round(first["min_distance"], 2)
                        if first["min_distance"] is not None
                        else ""
                    ),

                "second_contact_id":
                    second["contact_id"],

                "second_frame":
                    second["frame"],

                "second_time":
                    round(second["time"], 4),

                "second_contact_distance":
                    (
                        round(second["min_distance"], 2)
                        if second["min_distance"] is not None
                        else ""
                    ),

                "gap_seconds":
                    round(gap, 3),

                "samples_between_contacts":
                    geometry["samples"],

                "near_fraction":
                    round(geometry["near_fraction"], 3),

                "above_fraction":
                    round(geometry["above_fraction"], 3),

                "above_near_fraction":
                    round(geometry["above_near_fraction"], 3),

                "airborne_fraction":
                    round(geometry["airborne_fraction"], 3),

                "mean_car_z":
                    (
                        round(geometry["mean_car_z"], 2)
                        if geometry["mean_car_z"] is not None
                        else ""
                    ),

                "max_car_z":
                    (
                        round(geometry["max_car_z"], 2)
                        if geometry["max_car_z"] is not None
                        else ""
                    ),

                "mean_ball_z":
                    (
                        round(geometry["mean_ball_z"], 2)
                        if geometry["mean_ball_z"] is not None
                        else ""
                    ),

                "jump_evidence":
                    int(recent_jump),

                "boost_resource_drops":
                    len(resource_drops),

                "boost_state_changes":
                    len(recent_boost_state_changes),

                "boost_evidence":
                    int(boost_evidence),

                "high_enough_proxy":
                    int(high_enough),

                "sequence_pass":
                    int(passes_sequence),

                "heuristic_score":
                    round(min(score, 1.0), 3),

                "manual_label":
                    manual["label"] if manual else "",

                "manual_note":
                    manual["note"] if manual else "",

                "status": (
                    "Multi-touch aerial sequence candidate - review"
                    if passes_sequence
                    else "Rejected by sequence criteria"
                ),
            })


# ============================================================
# WRITE MANUAL VALIDATION FILE
# ============================================================

manual_fields = [
    "start_time",
    "end_time",
    "car",
    "label",
    "note",
]

manual_rows = [
    {
        "start_time": row["start"],
        "end_time": row["end"],
        "car": row["car"],
        "label": row["label"],
        "note": row["note"],
    }
    for row in MANUAL_REVIEWS
]

write_csv(
    LABEL_FILE,
    manual_rows,
    manual_fields
)


# ============================================================
# SAVE SEQUENCE CANDIDATES
# ============================================================

results.sort(
    key=lambda row: (
        -row["sequence_pass"],
        -row["heuristic_score"],
        row["first_time"],
    )
)

fields = [
    "car",
    "first_contact_id",
    "first_frame",
    "first_time",
    "first_contact_distance",
    "second_contact_id",
    "second_frame",
    "second_time",
    "second_contact_distance",
    "gap_seconds",
    "samples_between_contacts",
    "near_fraction",
    "above_fraction",
    "above_near_fraction",
    "airborne_fraction",
    "mean_car_z",
    "max_car_z",
    "mean_ball_z",
    "jump_evidence",
    "boost_resource_drops",
    "boost_state_changes",
    "boost_evidence",
    "high_enough_proxy",
    "sequence_pass",
    "heuristic_score",
    "manual_label",
    "manual_note",
    "status",
]

write_csv(
    OUTPUT_FILE,
    results,
    fields
)


# ============================================================
# SUMMARY
# ============================================================

passed = [
    row for row in results
    if row["sequence_pass"] == 1
]

positive_review = [
    row for row in passed
    if row["manual_label"] == "air_dribble"
]

negative_review = [
    row for row in passed
    if row["manual_label"] in {
        "not_air_dribble",
        "flip_reset_touch_not_air_dribble",
    }
]

print()
print("=" * 72)
print("SEQUENCE-BASED AIR-DRIBBLE REPORT")
print("=" * 72)

print("Manual reviews:", len(MANUAL_REVIEWS))
print("Distinct contacts:", len(contacts))
print("Contact-pair sequences evaluated:", len(results))
print("Sequences passing the current rules:", len(passed))

print()
print("Your confirmed air-dribble window:")

if positive_review:
    for row in positive_review:
        print(
            f"  car={row['car']} "
            f"{row['first_time']} -> {row['second_time']} "
            f"near={row['near_fraction']} "
            f"above_near={row['above_near_fraction']} "
            f"airborne={row['airborne_fraction']} "
            f"score={row['heuristic_score']}"
        )
else:
    print(
        "  No passing sequence matched the manually confirmed "
        "285-287 second air dribble yet."
    )
    print(
        "  Check all pair rows around that time before "
        "tightening the thresholds."
    )

print()
print(
    "Passing sequences overlapping reviewed non-air-dribble scenes:",
    len(negative_review)
)

print()
print("Top passing sequences:")

for row in passed[:20]:
    print(
        f"car={row['car']:5} "
        f"{row['first_time']:8} -> {row['second_time']:8} "
        f"gap={row['gap_seconds']} "
        f"near={row['near_fraction']} "
        f"above_near={row['above_near_fraction']} "
        f"airborne={row['airborne_fraction']} "
        f"jump={row['jump_evidence']} "
        f"boost={row['boost_evidence']} "
        f"score={row['heuristic_score']} "
        f"manual={row['manual_label'] or '-'}"
    )

print()
print("Saved:")
print(" ", OUTPUT_FILE)
print(" ", LABEL_FILE)

print()
print(
    "Reminder: passing a heuristic rule is not proof of a trick. "
    "Use the manual labels to check false positives and false negatives."
)
