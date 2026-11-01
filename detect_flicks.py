import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path


BASE = Path("data/replays")

TIMELINE_FILE = BASE / "timeline.csv"
CONTACTS_FILE = BASE / "ball_contacts.csv"
EVENTS_FILE = BASE / "mechanic_events.csv"

OUTPUT_FILE = BASE / "flick_candidates.csv"

# Approximate windows, to be tuned against real examples.
GROUND_DRIBBLE_FRAMES = 20
JUMP_WINDOW = 0.9
DODGE_WINDOW_BEFORE = 0.8
DODGE_WINDOW_AFTER = 0.2

MAX_RELATIVE_SPREAD = 160.0
MAX_GROUND_CAR_Z = 100.0
MAX_GROUND_BALL_Z = 260.0
MAX_DRIBBLE_DISTANCE = 450.0
MIN_DRIBBLE_DISTANCE = 80.0
MIN_BALL_VELOCITY_CHANGE = 1500.0


# ============================================================
# HELPERS
# ============================================================

def number(value):
    try:
        if value is None or value == "":
            return None

        result = float(value)

        if not math.isfinite(result):
            return None

        return result

    except (ValueError, TypeError):
        return None


def integer(value):
    value = number(value)

    if value is None:
        return None

    return int(value)


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(
            f"Missing input file: {path}"
        )

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        return list(csv.DictReader(f))


def position(row, prefix):
    x = number(row.get(f"{prefix}_x"))
    y = number(row.get(f"{prefix}_y"))
    z = number(row.get(f"{prefix}_z"))

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


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


# ============================================================
# LOAD INPUTS
# ============================================================

print("Loading timeline...")

timeline_rows = read_csv(
    TIMELINE_FILE
)

timeline = {}

for row in timeline_rows:
    frame = integer(row.get("frame"))

    if frame is not None:
        timeline[frame] = row

print("Timeline frames:", len(timeline))


print("Loading clustered contacts...")

contacts = read_csv(
    CONTACTS_FILE
)

print("Contacts:", len(contacts))


print("Loading mechanic events...")

events = read_csv(
    EVENTS_FILE
)

jumps_by_car = defaultdict(list)
dodges_by_car = defaultdict(list)

for event in events:
    car = str(
        event.get("timeline_car", "")
    ).strip().lower()

    t = number(
        event.get("time")
    )

    component = event.get(
        "component_type",
        ""
    )

    if car not in {
        "car1", "car2", "car3", "car4"
    }:
        continue

    if t is None:
        continue

    if component == "Jump":
        jumps_by_car[car].append(t)

    elif component == "Dodge":
        dodges_by_car[car].append(t)


for car in jumps_by_car:
    jumps_by_car[car].sort()

for car in dodges_by_car:
    dodges_by_car[car].sort()


# ============================================================
# ESTIMATE GROUND-DRIBBLE EVIDENCE
# ============================================================

def inspect_ground_dribble(frame, car):
    """
    Estimate whether the ball stayed near the same relative
    position in front of a relatively low car before contact.

    This is a geometric proxy, not a confirmed ground dribble.
    """

    relative_positions = []
    distances = []
    car_heights = []
    ball_heights = []

    start_frame = (
        frame - GROUND_DRIBBLE_FRAMES
    )

    end_frame = frame - 1

    for sample_frame in range(
        start_frame,
        end_frame + 1
    ):
        row = timeline.get(sample_frame)

        if row is None:
            continue

        active = integer(
            row.get(f"{car}_active")
        )

        if active != 1:
            continue

        car_pos = position(
            row,
            car
        )

        ball_pos = position(
            row,
            "ball"
        )

        if car_pos is None or ball_pos is None:
            continue

        d = distance(
            car_pos,
            ball_pos
        )

        if d is None:
            continue

        # Ball position relative to car position.
        relative_positions.append((
            ball_pos[0] - car_pos[0],
            ball_pos[1] - car_pos[1],
            ball_pos[2] - car_pos[2],
        ))

        distances.append(d)
        car_heights.append(car_pos[2])
        ball_heights.append(ball_pos[2])

    if len(relative_positions) < 8:
        return {
            "samples": len(relative_positions),
            "relative_spread": "",
            "mean_distance": "",
            "mean_car_z": "",
            "mean_ball_z": "",
            "ground_dribble_proxy": False,
        }

    spread_x = statistics.pstdev(
        p[0] for p in relative_positions
    )

    spread_y = statistics.pstdev(
        p[1] for p in relative_positions
    )

    spread_z = statistics.pstdev(
        p[2] for p in relative_positions
    )

    relative_spread = math.sqrt(
        spread_x ** 2
        + spread_y ** 2
        + spread_z ** 2
    )

    mean_distance = statistics.mean(
        distances
    )

    mean_car_z = statistics.mean(
        car_heights
    )

    mean_ball_z = statistics.mean(
        ball_heights
    )

    ground_proxy = (
        relative_spread <= MAX_RELATIVE_SPREAD
        and MIN_DRIBBLE_DISTANCE <= mean_distance
        <= MAX_DRIBBLE_DISTANCE
        and mean_car_z <= MAX_GROUND_CAR_Z
        and mean_ball_z <= MAX_GROUND_BALL_Z
    )

    return {
        "samples": len(relative_positions),

        "relative_spread": round(
            relative_spread, 2
        ),

        "mean_distance": round(
            mean_distance, 2
        ),

        "mean_car_z": round(
            mean_car_z, 2
        ),

        "mean_ball_z": round(
            mean_ball_z, 2
        ),

        "ground_dribble_proxy": ground_proxy,
    }


# ============================================================
# EVALUATE CONTACTS
# ============================================================

print()
print("Evaluating flick candidates...")

results = []
skipped = 0

for contact in contacts:

    frame = integer(
        contact.get("frame_after")
    )

    t = number(
        contact.get("time_after")
    )

    car = str(
        contact.get("car", "")
    ).strip().lower()

    if (
        frame is None
        or t is None
        or car not in {
            "car1", "car2", "car3", "car4"
        }
    ):
        skipped += 1
        continue

    # Require the associated timeline frame.
    if frame not in timeline:
        skipped += 1
        continue

    ball_dv = number(
        contact.get("ball_dv")
    )

    min_distance = number(
        contact.get("min_distance")
    )

    # --------------------------------------------------------
    # Jump before contact
    # --------------------------------------------------------

    recent_jumps = [
        jt for jt in jumps_by_car[car]
        if t - JUMP_WINDOW <= jt <= t + 0.05
    ]

    jump_recent = bool(
        recent_jumps
    )

    jump_age = ""

    if recent_jumps:
        jump_age = round(
            t - max(recent_jumps),
            3
        )

    # --------------------------------------------------------
    # Dodge/flip near the contact
    # --------------------------------------------------------

    recent_dodges = [
        dt for dt in dodges_by_car[car]
        if (
            t - DODGE_WINDOW_BEFORE
            <= dt
            <= t + DODGE_WINDOW_AFTER
        )
    ]

    dodge_near_contact = bool(
        recent_dodges
    )

    dodge_age = ""

    if recent_dodges:
        closest_dodge = min(
            recent_dodges,
            key=lambda dt: abs(t - dt)
        )

        dodge_age = round(
            t - closest_dodge,
            3
        )

    # --------------------------------------------------------
    # Ground-dribble proxy immediately before contact
    # --------------------------------------------------------

    dribble = inspect_ground_dribble(
        frame,
        car
    )

    # --------------------------------------------------------
    # Ball acceleration evidence
    # --------------------------------------------------------

    velocity_evidence = (
        ball_dv is not None
        and ball_dv >= MIN_BALL_VELOCITY_CHANGE
    )

    close_contact = (
        min_distance is not None
        and min_distance <= 300.0
    )

    velocity_score = (
        clamp(
            ball_dv / 3000.0
        )
        if ball_dv is not None
        else 0.0
    )

    dribble_score = (
        1.0
        if dribble["ground_dribble_proxy"]
        else 0.0
    )

    jump_score = (
        1.0
        if jump_recent
        else 0.0
    )

    dodge_score = (
        1.0
        if dodge_near_contact
        else 0.0
    )

    contact_score = (
        1.0
        if close_contact
        else 0.0
    )

    score = (
        0.20 * jump_score
        + 0.25 * dodge_score
        + 0.25 * dribble_score
        + 0.20 * velocity_score
        + 0.10 * contact_score
    )

    score = clamp(score)

    # --------------------------------------------------------
    # Conservative candidate label
    # --------------------------------------------------------

    if (
        jump_recent
        and dodge_near_contact
        and dribble["ground_dribble_proxy"]
        and velocity_evidence
        and close_contact
    ):
        status = "Strong heuristic candidate"

    elif (
        jump_recent
        and dodge_near_contact
        and velocity_evidence
    ):
        status = "Review candidate"

    else:
        status = "Insufficient evidence"

    results.append({
        "contact_id": contact.get("contact_id", ""),
        "frame": frame,
        "time": round(t, 4),
        "car": car,

        "ball_dv": (
            round(ball_dv, 2)
            if ball_dv is not None else ""
        ),

        "min_distance": (
            round(min_distance, 2)
            if min_distance is not None else ""
        ),

        "jump_recent": int(jump_recent),
        "jump_age_seconds": jump_age,

        "dodge_near_contact": int(
            dodge_near_contact
        ),

        "dodge_age_seconds": dodge_age,

        "ground_dribble_proxy": int(
            dribble["ground_dribble_proxy"]
        ),

        "ground_samples": dribble["samples"],
        "relative_spread": dribble["relative_spread"],
        "mean_distance_before": dribble["mean_distance"],
        "mean_car_z_before": dribble["mean_car_z"],
        "mean_ball_z_before": dribble["mean_ball_z"],

        "velocity_evidence": int(
            velocity_evidence
        ),

        "heuristic_score": round(
            score, 3
        ),

        "status": status,
    })


# ============================================================
# SAVE RESULTS
# ============================================================

results.sort(
    key=lambda row: row["heuristic_score"],
    reverse=True
)

fields = [
    "contact_id",
    "frame",
    "time",
    "car",

    "ball_dv",
    "min_distance",

    "jump_recent",
    "jump_age_seconds",

    "dodge_near_contact",
    "dodge_age_seconds",

    "ground_dribble_proxy",
    "ground_samples",
    "relative_spread",
    "mean_distance_before",
    "mean_car_z_before",
    "mean_ball_z_before",

    "velocity_evidence",
    "heuristic_score",
    "status",
]

with OUTPUT_FILE.open(
    "w",
    encoding="utf-8",
    newline=""
) as f:
    writer = csv.DictWriter(
        f,
        fieldnames=fields
    )

    writer.writeheader()
    writer.writerows(results)


# ============================================================
# SUMMARY
# ============================================================

from collections import Counter

counts = Counter(
    row["status"]
    for row in results
)

print()
print("=" * 72)
print("FLICK CANDIDATE REPORT")
print("=" * 72)

print("Contacts loaded:", len(contacts))
print("Analyzed:", len(results))
print("Skipped:", skipped)

print()
print("Status counts:")

for label in [
    "Strong heuristic candidate",
    "Review candidate",
    "Insufficient evidence",
]:
    print(
        f"  {label}: {counts[label]}"
    )

print()
print("Top 15 candidates:")

for row in results[:15]:
    print(
        f"time={row['time']:8} "
        f"frame={row['frame']:5} "
        f"car={row['car']:5} "
        f"score={row['heuristic_score']:.3f} "
        f"jump={row['jump_recent']} "
        f"dodge={row['dodge_near_contact']} "
        f"ground={row['ground_dribble_proxy']} "
        f"ball_dv={row['ball_dv']} "
        f"{row['status']}"
    )

print()
print("Saved:", OUTPUT_FILE)
print(
    "These are heuristic candidates, "
    "not confirmed flicks."
)