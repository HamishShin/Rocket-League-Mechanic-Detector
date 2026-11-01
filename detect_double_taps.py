import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median


BASE = Path("data/replays")

REPLAY_FILE = BASE / "new_test_network.json"
TIMELINE_FILE = BASE / "timeline.csv"
CONTACTS_FILE = BASE / "ball_contacts.csv"
MECHANIC_FILE = BASE / "mechanic_events.csv"

OUTPUT_FILE = BASE / "double_tap_candidates.csv"
WALL_FILE = BASE / "wall_bounce_candidates.csv"

# Goal event confirmed in this replay's object table.
STAT_EVENT_OBJECT_ID = 48
GOAL_STAT_ID = 374

# Approximate field geometry; checked against both possible
# longitudinal coordinate axes.
END_WALL_Y = 4700.0
END_WALL_X = 3700.0
GOAL_CENTRE_LIMIT = 1500.0
MIN_WALL_HEIGHT = 650.0

# Candidate timing windows.
MAX_FIRST_CONTACT_TO_WALL = 4.0
MAX_WALL_TO_SECOND_CONTACT = 2.0
MAX_SECOND_CONTACT_TO_GOAL = 2.5

# Local trajectory samples used to look for a velocity reversal.
VELOCITY_WINDOW = 5
MIN_REVERSAL_SPEED = 200.0

# Approximate airborne proxy.
AIRBORNE_CAR_Z = 120.0
JUMP_LOOKBACK_SECONDS = 2.5


# ============================================================
# HELPERS
# ============================================================

def num(value):
    if value is None or value == "":
        return None

    try:
        result = float(value)

        if math.isfinite(result):
            return result

    except (ValueError, TypeError):
        pass

    return None


def integer(value):
    result = num(value)

    if result is None:
        return None

    return int(result)


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


def pos(row, prefix="ball"):
    x = num(row.get(f"{prefix}_x"))
    y = num(row.get(f"{prefix}_y"))
    z = num(row.get(f"{prefix}_z"))

    if x is None or y is None or z is None:
        return None

    return (x, y, z)


def dist(a, b):
    if a is None or b is None:
        return None

    return math.sqrt(
        (a[0] - b[0]) ** 2
        + (a[1] - b[1]) ** 2
        + (a[2] - b[2]) ** 2
    )


def sign(value):
    if value > 0:
        return 1

    if value < 0:
        return -1

    return 0


def median_valid(values):
    values = [
        value
        for value in values
        if value is not None
        and math.isfinite(value)
    ]

    if not values:
        return None

    return median(values)


# ============================================================
# LOAD TIMELINE
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

if not timeline:
    raise RuntimeError("The timeline is empty.")

print("Timeline frames:", len(timeline))


# ============================================================
# LOAD CONTACTS
# ============================================================

print("Loading ball contacts...")

contacts = []

for row in read_csv(CONTACTS_FILE):
    frame = integer(row.get("frame_after"))
    t = num(row.get("time_after"))
    car = str(row.get("car", "")).strip().lower()

    if (
        frame is None
        or t is None
        or car not in {"car1", "car2", "car3", "car4"}
    ):
        continue

    contacts.append({
        "contact_id": row.get("contact_id", ""),
        "frame": frame,
        "time": t,
        "car": car,
        "distance": num(row.get("min_distance")),
        "ball_dv": num(row.get("ball_dv")),
    })

contacts.sort(key=lambda row: (row["time"], row["frame"]))

print("Usable contacts:", len(contacts))


# ============================================================
# LOAD JUMP EVENTS
# ============================================================

print("Loading jump events...")

jump_times = defaultdict(list)

for row in read_csv(MECHANIC_FILE):
    component = str(
        row.get("component_type", "")
    ).strip()

    if component != "Jump":
        continue

    car = str(
        row.get("timeline_car", "")
    ).strip().lower()

    t = num(row.get("time"))

    if (
        car in {"car1", "car2", "car3", "car4"}
        and t is not None
    ):
        jump_times[car].append(t)

for car in jump_times:
    jump_times[car].sort()


# ============================================================
# EXTRACT GOAL EVENTS
# ============================================================

print("Extracting goal events from the replay...")

with REPLAY_FILE.open(
    "r",
    encoding="utf-8"
) as f:
    replay = json.load(f)

frames = (
    replay.get("network_frames", {})
    .get("frames", [])
)

raw_goals = []

for frame_number, frame in enumerate(frames):
    for update in frame.get("updated_actors", []):
        if integer(update.get("object_id")) != STAT_EVENT_OBJECT_ID:
            continue

        attribute = update.get("attribute", {})

        if not isinstance(attribute, dict):
            continue

        stat_event = attribute.get("StatEvent")

        if not isinstance(stat_event, dict):
            continue

        if integer(stat_event.get("object_id")) != GOAL_STAT_ID:
            continue

        t = num(frame.get("time"))

        if t is None:
            continue

        raw_goals.append({
            "frame": frame_number,
            "time": t,
            "actor": integer(update.get("actor_id")),
        })


# Deduplicate repeated goal notifications close together.
goals = []

for goal in sorted(raw_goals, key=lambda item: item["frame"]):
    if (
        goals
        and goal["frame"] - goals[-1]["frame"] < 30
    ):
        continue

    goals.append(goal)

print("Raw goal notifications:", len(raw_goals))
print("Deduplicated goal events:", len(goals))


# ============================================================
# FIND HIGH WALL-BOUNCE CANDIDATES
# ============================================================

def position_velocity(frame, axis, side):
    """
    Estimate velocity from positions several frames apart.
    side = 'before' or 'after'.
    """

    if side == "before":
        f1 = frame - VELOCITY_WINDOW
        f2 = frame - 1
    else:
        f1 = frame + 1
        f2 = frame + VELOCITY_WINDOW

    r1 = timeline.get(f1)
    r2 = timeline.get(f2)

    if r1 is None or r2 is None:
        return None

    p1 = pos(r1)
    p2 = pos(r2)

    t1 = num(r1.get("time"))
    t2 = num(r2.get("time"))

    if p1 is None or p2 is None:
        return None

    if t1 is None or t2 is None or t2 == t1:
        return None

    axis_index = 0 if axis == "x" else 1

    return (
        p2[axis_index] - p1[axis_index]
    ) / (t2 - t1)


def reported_velocity(frame, axis, side):
    """
    Median replicated ball velocity on the approach/departure
    side of the candidate frame.
    """

    velocity_key = f"ball_v{axis}"

    if side == "before":
        frame_range = range(
            frame - VELOCITY_WINDOW,
            frame
        )
    else:
        frame_range = range(
            frame + 1,
            frame + VELOCITY_WINDOW + 1
        )

    values = []

    for f in frame_range:
        row = timeline.get(f)

        if row is not None:
            value = num(row.get(velocity_key))

            if value is not None:
                values.append(value)

    return median_valid(values)


def get_reversal(frame, axis):
    """
    First try replicated velocity. If unavailable or inconclusive,
    try velocity inferred from ball positions.
    """

    methods = [
        (
            reported_velocity(frame, axis, "before"),
            reported_velocity(frame, axis, "after"),
            "replicated_velocity",
        ),
        (
            position_velocity(frame, axis, "before"),
            position_velocity(frame, axis, "after"),
            "position_difference",
        ),
    ]

    for before, after, method in methods:

        if before is None or after is None:
            continue

        if (
            abs(before) >= MIN_REVERSAL_SPEED
            and abs(after) >= MIN_REVERSAL_SPEED
            and sign(before) != sign(after)
        ):
            return before, after, method

    return None


print("Scanning for high wall-bounce candidates...")

wall_raw = []

min_frame = min(timeline)
max_frame = max(timeline)

for frame in range(
    min_frame + VELOCITY_WINDOW,
    max_frame - VELOCITY_WINDOW
):

    row = timeline.get(frame)

    if row is None:
        continue

    ball = pos(row)

    if ball is None:
        continue

    x, y, z = ball

    if z < MIN_WALL_HEIGHT:
        continue

    # Candidate bounce off a goal-end/backboard wall with
    # longitudinal axis Y.
    if (
        abs(y) >= END_WALL_Y
        and abs(x) <= GOAL_CENTRE_LIMIT
    ):

        reversal = get_reversal(frame, "y")

        if reversal is not None:
            before, after, method = reversal

            wall_raw.append({
                "frame": frame,
                "time": num(row.get("time")),
                "axis": "y",
                "x": x,
                "y": y,
                "z": z,
                "velocity_before": before,
                "velocity_after": after,
                "method": method,
            })


    # Also test the alternative X-axis orientation. This helps
    # expose a coordinate-orientation mismatch instead of silently
    # assuming the wrong direction.
    if (
        abs(x) >= END_WALL_X
        and abs(y) <= GOAL_CENTRE_LIMIT
    ):

        reversal = get_reversal(frame, "x")

        if reversal is not None:
            before, after, method = reversal

            wall_raw.append({
                "frame": frame,
                "time": num(row.get("time")),
                "axis": "x",
                "x": x,
                "y": y,
                "z": z,
                "velocity_before": before,
                "velocity_after": after,
                "method": method,
            })


# Merge consecutive frames describing the same bounce.
wall_raw.sort(
    key=lambda item: (item["axis"], item["frame"])
)

wall_bounces = []

for event in wall_raw:
    nearby_index = None

    for i in range(
        len(wall_bounces) - 1,
        max(-1, len(wall_bounces) - 8),
        -1
    ):
        previous = wall_bounces[i]

        if previous["axis"] != event["axis"]:
            continue

        if event["frame"] - previous["frame"] <= 8:
            nearby_index = i

        break

    if nearby_index is None:
        wall_bounces.append(event)
    else:
        previous = wall_bounces[nearby_index]

        # Retain the sample with the greater height as the
        # representative point for this short bounce window.
        if event["z"] > previous["z"]:
            wall_bounces[nearby_index] = event


wall_bounces.sort(key=lambda item: item["frame"])


# Save wall-bounce diagnostics separately.
wall_fields = [
    "frame",
    "time",
    "axis",
    "x",
    "y",
    "z",
    "velocity_before",
    "velocity_after",
    "method",
]

with WALL_FILE.open(
    "w",
    encoding="utf-8",
    newline=""
) as f:
    writer = csv.DictWriter(
        f,
        fieldnames=wall_fields
    )

    writer.writeheader()
    writer.writerows(wall_bounces)


print("Wall-bounce candidates:", len(wall_bounces))

print(
    "Wall candidates by axis:",
    dict(Counter(item["axis"] for item in wall_bounces))
)


# ============================================================
# AIRBORNE PROXY FOR SECOND CONTACT
# ============================================================

def car_airborne_proxy(contact):
    frame = contact["frame"]
    t = contact["time"]
    car = contact["car"]

    # Check car height near the second contact.
    heights = []

    for f in range(frame - 5, frame + 6):
        row = timeline.get(f)

        if row is None:
            continue

        active = integer(
            row.get(f"{car}_active")
        )

        z = num(
            row.get(f"{car}_z")
        )

        if active == 1 and z is not None:
            heights.append(z)

    high_car = any(
        z > AIRBORNE_CAR_Z
        for z in heights
    )

    # A recent Jump event is a second, weaker source of evidence.
    recent_jump = any(
        t - JUMP_LOOKBACK_SECONDS <= jt <= t + 0.05
        for jt in jump_times[car]
    )

    return high_car or recent_jump, high_car, recent_jump


# ============================================================
# MATCH CONTACT -> WALL -> AIR CONTACT -> GOAL
# ============================================================

print("Searching for double-tap sequences...")

results = []

for goal in goals:
    goal_frame = goal["frame"]
    goal_time = goal["time"]

    # Second contact must immediately precede the goal within
    # the configured time window.
    second_contacts = [
        contact
        for contact in contacts
        if (
            0 < goal_time - contact["time"]
            <= MAX_SECOND_CONTACT_TO_GOAL
            and contact["frame"] < goal_frame
        )
    ]

    chains = []

    for second in second_contacts:

        airborne, high_car, recent_jump = (
            car_airborne_proxy(second)
        )

        for wall in wall_bounces:

            wall_time = wall["time"]
            wall_frame = wall["frame"]

            if wall_time is None:
                continue

            wall_to_second = (
                second["time"] - wall_time
            )

            if not (
                0.0 < wall_to_second
                <= MAX_WALL_TO_SECOND_CONTACT
            ):
                continue

            if not (
                wall_frame < second["frame"] < goal_frame
            ):
                continue

            first_contacts = [
                contact
                for contact in contacts
                if (
                    0.0 < wall_time - contact["time"]
                    <= MAX_FIRST_CONTACT_TO_WALL
                    and contact["frame"] < wall_frame
                    and (
                        second["frame"] - contact["frame"]
                    ) >= 5
                )
            ]

            for first in first_contacts:

                first_to_wall = (
                    wall_time - first["time"]
                )

                second_to_goal = (
                    goal_time - second["time"]
                )

                # Transparent ranking score, not a probability.
                score = 0.20

                # High bounce near the goal-end central corridor.
                score += 0.25

                # A recent contact followed by a plausible goal.
                score += 0.15

                if second_to_goal <= 1.2:
                    score += 0.15

                if airborne:
                    score += 0.25

                score = min(score, 1.0)

                if airborne:
                    status = (
                        "Potential double tap sequence - review"
                    )
                else:
                    status = (
                        "Possible sequence - airborne unconfirmed"
                    )

                chains.append({
                    "goal_frame": goal_frame,
                    "goal_time": goal_time,

                    "first_contact_id": first["contact_id"],
                    "first_contact_frame": first["frame"],
                    "first_contact_time": first["time"],
                    "first_contact_car": first["car"],

                    "wall_frame": wall_frame,
                    "wall_time": wall_time,
                    "wall_axis": wall["axis"],
                    "wall_x": round(wall["x"], 2),
                    "wall_y": round(wall["y"], 2),
                    "wall_z": round(wall["z"], 2),
                    "wall_velocity_before": round(
                        wall["velocity_before"], 2
                    ),
                    "wall_velocity_after": round(
                        wall["velocity_after"], 2
                    ),

                    "second_contact_id": second["contact_id"],
                    "second_contact_frame": second["frame"],
                    "second_contact_time": second["time"],
                    "second_contact_car": second["car"],

                    "second_contact_car_high": int(high_car),
                    "recent_jump_proxy": int(recent_jump),
                    "airborne_proxy": int(airborne),

                    "seconds_first_to_wall": round(
                        first_to_wall, 3
                    ),
                    "seconds_wall_to_second": round(
                        wall_to_second, 3
                    ),
                    "seconds_second_to_goal": round(
                        second_to_goal, 3
                    ),

                    "heuristic_score": round(score, 3),
                    "status": status,
                })


    if chains:
        # Prefer airborne evidence, then a score close in time
        # to the second contact and goal.
        best = max(
            chains,
            key=lambda item: (
                item["heuristic_score"],
                -item["seconds_second_to_goal"],
                -item["seconds_wall_to_second"],
            )
        )
        results.append(best)

    else:
        results.append({
            "goal_frame": goal_frame,
            "goal_time": goal_time,

            "first_contact_id": "",
            "first_contact_frame": "",
            "first_contact_time": "",
            "first_contact_car": "",

            "wall_frame": "",
            "wall_time": "",
            "wall_axis": "",
            "wall_x": "",
            "wall_y": "",
            "wall_z": "",
            "wall_velocity_before": "",
            "wall_velocity_after": "",

            "second_contact_id": "",
            "second_contact_frame": "",
            "second_contact_time": "",
            "second_contact_car": "",

            "second_contact_car_high": "",
            "recent_jump_proxy": "",
            "airborne_proxy": "",

            "seconds_first_to_wall": "",
            "seconds_wall_to_second": "",
            "seconds_second_to_goal": "",

            "heuristic_score": 0.0,
            "status": "No complete sequence found",
        })


# ============================================================
# SAVE RESULTS
# ============================================================

result_fields = [
    "goal_frame",
    "goal_time",

    "first_contact_id",
    "first_contact_frame",
    "first_contact_time",
    "first_contact_car",

    "wall_frame",
    "wall_time",
    "wall_axis",
    "wall_x",
    "wall_y",
    "wall_z",
    "wall_velocity_before",
    "wall_velocity_after",

    "second_contact_id",
    "second_contact_frame",
    "second_contact_time",
    "second_contact_car",

    "second_contact_car_high",
    "recent_jump_proxy",
    "airborne_proxy",

    "seconds_first_to_wall",
    "seconds_wall_to_second",
    "seconds_second_to_goal",

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
        fieldnames=result_fields
    )

    writer.writeheader()
    writer.writerows(
        results
    )


# ============================================================
# REPORT
# ============================================================

counts = Counter(
    row["status"]
    for row in results
)

print()
print("=" * 72)
print("DOUBLE-TAP CANDIDATE REPORT")
print("=" * 72)

print("Goals found:", len(goals))
print("Wall-bounce candidates:", len(wall_bounces))
print("Goals analyzed:", len(results))

print()
print("Results by status:")

for label, count in counts.items():
    print(f"  {label}: {count}")

print()
print("Per-goal results:")

for row in results:
    print(
        f"goal_time={row['goal_time']:8.3f} "
        f"goal_frame={row['goal_frame']:5} "
        f"score={row['heuristic_score']:.3f} "
        f"wall={row['wall_frame'] or '-'} "
        f"first={row['first_contact_frame'] or '-'} "
        f"second={row['second_contact_frame'] or '-'} "
        f"{row['status']}"
    )

print()
print("Saved:")
print(" ", OUTPUT_FILE)
print(" ", WALL_FILE)
print()
print(
    "These are sequence candidates; they are not "
    "confirmed double taps."
)
