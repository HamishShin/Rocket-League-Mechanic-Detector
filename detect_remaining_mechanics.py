import csv
import math
import statistics
from collections import defaultdict, Counter
from pathlib import Path


BASE = Path("data/replays")

TIMELINE_FILE = BASE / "timeline.csv"
CONTACTS_FILE = BASE / "ball_contacts.csv"
EVENTS_FILE = BASE / "mechanic_events.csv"

OUTPUTS = {
    "ground": BASE / "ground_dribble_candidates.csv",
    "musty": BASE / "musty_flick_candidates.csv",
    "half": BASE / "half_flip_candidates.csv",
    "reset": BASE / "flip_reset_candidates.csv",
    "double": BASE / "double_flip_reset_candidates.csv",
}


# ============================================================
# HELPERS
# ============================================================

def num(value):
    try:
        if value is None or value == "":
            return None

        value = float(value)

        return value if math.isfinite(value) else None

    except (ValueError, TypeError):
        return None


def integer(value):
    value = num(value)

    return int(value) if value is not None else None


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


def distance(a, b):
    if a is None or b is None:
        return None

    return math.sqrt(
        sum((a[i] - b[i]) ** 2 for i in range(3))
    )


def dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def norm(v):
    if v is None:
        return 0.0

    return math.sqrt(dot(v, v))


def normalize(v):
    length = norm(v)

    if length < 1e-9:
        return None

    return tuple(
        component / length
        for component in v
    )


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def quat(row, car):
    values = [
        num(row.get(f"{car}_rw")),
        num(row.get(f"{car}_rx")),
        num(row.get(f"{car}_ry")),
        num(row.get(f"{car}_rz")),
    ]

    if any(value is None for value in values):
        return None

    length = math.sqrt(
        sum(value * value for value in values)
    )

    if length < 1e-9:
        return None

    return tuple(
        value / length
        for value in values
    )


def rotate_vector(q, vector):
    """
    Rotate a vector by a quaternion (w, x, y, z).
    """

    if q is None:
        return None

    w, x, y, z = q
    qv = (x, y, z)

    first = cross(qv, vector)

    second = tuple(
        first[i] + w * vector[i]
        for i in range(3)
    )

    third = cross(qv, second)

    return tuple(
        vector[i] + 2.0 * third[i]
        for i in range(3)
    )


def orientation(row, car):
    q = quat(row, car)

    if q is None:
        return None

    forward = rotate_vector(q, (1.0, 0.0, 0.0))
    up = rotate_vector(q, (0.0, 0.0, 1.0))

    return {
        "forward": normalize(forward),
        "up": normalize(up),
    }


def position(row, prefix):
    values = (
        num(row.get(f"{prefix}_x")),
        num(row.get(f"{prefix}_y")),
        num(row.get(f"{prefix}_z")),
    )

    return None if any(v is None for v in values) else values


def local_ball_offset(row, car):
    """
    Ball position relative to the car, transformed into the
    car's local coordinate frame. This accounts for car rotation.
    """

    car_pos = position(row, car)
    ball_pos = position(row, "ball")
    q = quat(row, car)

    if car_pos is None or ball_pos is None or q is None:
        return None

    world_offset = tuple(
        ball_pos[i] - car_pos[i]
        for i in range(3)
    )

    w, x, y, z = q

    inverse_q = (w, -x, -y, -z)

    return rotate_vector(
        inverse_q,
        world_offset
    )


def contact_frame(contact):
    return integer(
        contact.get("frame_after")
    )


def contact_time(contact):
    return num(
        contact.get("time_after")
    )


def contact_car(contact):
    car = str(
        contact.get("car", "")
    ).strip().lower()

    return car if car in {
        "car1", "car2", "car3", "car4"
    } else None


def near_times(times, t, before, after=0.0):
    return [
        event_time
        for event_time in times
        if t - before <= event_time <= t + after
    ]


def save_rows(path, rows, fields):
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


def nearest_active_row(frame, car):
    row = timeline.get(frame)

    if row is None:
        return None

    if integer(row.get(f"{car}_active")) != 1:
        return None

    return row


# ============================================================
# LOAD DATA
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


print("Loading contacts...")

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
    key=lambda item: item["time"]
)

print("Contacts:", len(contacts))


print("Loading mechanic events...")

events = read_csv(
    EVENTS_FILE
)

jumps = defaultdict(list)
dodges = defaultdict(list)

for event in events:
    car = str(
        event.get("timeline_car", "")
    ).strip().lower()

    t = num(
        event.get("time")
    )

    component = str(
        event.get("component_type", "")
    )

    if (
        car not in {"car1", "car2", "car3", "car4"}
        or t is None
    ):
        continue

    if component == "Jump":
        jumps[car].append(t)

    elif component == "Dodge":
        dodges[car].append(t)

for car in jumps:
    jumps[car].sort()

for car in dodges:
    dodges[car].sort()


# Map replay time to nearest timeline frame.
ordered_frames = sorted(timeline)
ordered_times = [
    num(timeline[frame].get("time"))
    for frame in ordered_frames
]


def frame_at_time(t):
    best_frame = None
    best_diff = float("inf")

    for frame, frame_time in zip(
        ordered_frames,
        ordered_times
    ):
        if frame_time is None:
            continue

        diff = abs(frame_time - t)

        if diff < best_diff:
            best_diff = diff
            best_frame = frame

        if frame_time > t and diff > best_diff:
            break

    return best_frame


# ============================================================
# 1. GROUND DRIBBLE CANDIDATES
# ============================================================

print()
print("Detecting ground dribble candidates...")

ground_results = []

GROUND_WINDOW = 20

for contact in contacts:
    frame = contact["frame"]
    car = contact["car"]

    offsets = []
    distances = []
    car_heights = []
    ball_heights = []

    for f in range(
        frame - GROUND_WINDOW,
        frame
    ):
        row = timeline.get(f)

        if row is None:
            continue

        if integer(row.get(f"{car}_active")) != 1:
            continue

        offset = local_ball_offset(row, car)
        cp = position(row, car)
        bp = position(row, "ball")

        if offset is None or cp is None or bp is None:
            continue

        d = distance(cp, bp)

        if d is None:
            continue

        offsets.append(offset)
        distances.append(d)
        car_heights.append(cp[2])
        ball_heights.append(bp[2])

    if len(offsets) < 10:
        continue

    spread_x = statistics.pstdev(
        p[0] for p in offsets
    )

    spread_y = statistics.pstdev(
        p[1] for p in offsets
    )

    spread_z = statistics.pstdev(
        p[2] for p in offsets
    )

    spread = math.sqrt(
        spread_x ** 2
        + spread_y ** 2
        + spread_z ** 2
    )

    mean_dist = statistics.mean(distances)
    mean_car_z = statistics.mean(car_heights)
    mean_ball_z = statistics.mean(ball_heights)

    stable = spread <= 140.0

    grounded = mean_car_z <= 100.0

    near_car = (
        80.0 <= mean_dist <= 500.0
    )

    low_ball = mean_ball_z <= 300.0

    candidate = (
        stable and grounded and near_car and low_ball
    )

    score = (
        0.35 * max(0.0, min(1.0, 1.0 - spread / 250.0))
        + 0.25 * (1.0 if grounded else 0.0)
        + 0.25 * (1.0 if near_car else 0.0)
        + 0.15 * (1.0 if low_ball else 0.0)
    )

    ground_results.append({
        "contact_id": contact["contact_id"],
        "frame": frame,
        "time": round(contact["time"], 4),
        "car": car,
        "samples": len(offsets),
        "relative_position_spread": round(spread, 2),
        "mean_car_ball_distance": round(mean_dist, 2),
        "mean_car_z": round(mean_car_z, 2),
        "mean_ball_z": round(mean_ball_z, 2),
        "ground_dribble_proxy": int(candidate),
        "heuristic_score": round(score, 3),
    })


# ============================================================
# 2. MUSTY-LIKE FLICK CANDIDATES
# ============================================================

print("Detecting Musty-like flick candidates...")

musty_results = []

for contact in contacts:
    frame = contact["frame"]
    t = contact["time"]
    car = contact["car"]

    recent_jump = near_times(
        jumps[car],
        t,
        before=2.0,
        after=0.05
    )

    recent_dodge = near_times(
        dodges[car],
        t,
        before=0.9,
        after=0.05
    )

    inverted_samples = 0
    backwards_samples = 0
    alignments = []

    for f in range(
        frame - 25,
        frame
    ):
        row = nearest_active_row(f, car)

        if row is None:
            continue

        orient = orientation(row, car)

        if orient is None:
            continue

        up = orient["up"]
        forward = orient["forward"]

        cp = position(row, car)

        vx = num(row.get(f"{car}_vx"))
        vy = num(row.get(f"{car}_vy"))
        vz = num(row.get(f"{car}_vz"))

        if cp is None or any(
            v is None for v in (vx, vy, vz)
        ):
            continue

        if up[2] < -0.25:
            inverted_samples += 1

            velocity = (vx, vy, vz)
            speed = norm(velocity)

            if speed > 500.0:
                alignment = dot(
                    forward,
                    normalize(velocity)
                )

                alignments.append(alignment)

                if alignment < -0.15:
                    backwards_samples += 1

    inverted = inverted_samples >= 2

    moving_backward = backwards_samples >= 2

    ball_dv = contact["ball_dv"]

    velocity_gain = (
        ball_dv is not None
        and ball_dv >= 1500.0
    )

    has_jump = bool(recent_jump)
    has_dodge = bool(recent_dodge)

    candidate = (
        inverted
        and moving_backward
        and has_jump
        and has_dodge
        and velocity_gain
    )

    score = (
        0.20 * has_jump
        + 0.20 * has_dodge
        + 0.20 * inverted
        + 0.20 * moving_backward
        + 0.20 * velocity_gain
    )

    musty_results.append({
        "contact_id": contact["contact_id"],
        "frame": frame,
        "time": round(t, 4),
        "car": car,
        "recent_jump": int(has_jump),
        "recent_dodge": int(has_dodge),
        "inverted_orientation_proxy": int(inverted),
        "backward_motion_proxy": int(moving_backward),
        "inverted_samples": inverted_samples,
        "backward_samples": backwards_samples,
        "ball_velocity_change": (
            round(ball_dv, 2)
            if ball_dv is not None else ""
        ),
        "heuristic_score": round(score, 3),
        "status": (
            "Musty-like candidate; flip direction unverified"
            if candidate
            else "Insufficient evidence"
        ),
    })


# ============================================================
# 3. HALF-FLIP CANDIDATES
# ============================================================

print("Detecting half-flip candidates...")

half_results = []

for car in ("car1", "car2", "car3", "car4"):
    for jump_time in jumps[car]:

        jump_frame = frame_at_time(
            jump_time
        )

        if jump_frame is None:
            continue

        dodge_times = [
            dt for dt in dodges[car]
            if jump_time <= dt <= jump_time + 0.8
        ]

        if not dodge_times:
            continue

        # Start orientation just before the jump.
        start_row = nearest_active_row(
            max(min(ordered_frames), jump_frame - 2),
            car
        )

        if start_row is None:
            start_row = nearest_active_row(
                jump_frame,
                car
            )

        if start_row is None:
            continue

        start_orientation = orientation(
            start_row,
            car
        )

        if start_orientation is None:
            continue

        start_forward = start_orientation["forward"]
        start_up = start_orientation["up"]

        # A half-flip typically ends upright but facing
        # substantially opposite its starting direction.
        if start_up[2] < 0.25:
            continue

        for dodge_time in dodge_times:

            dodge_frame = frame_at_time(
                dodge_time
            )

            if dodge_frame is None:
                continue

            best = None

            start_search_time = dodge_time + 0.35
            end_search_time = dodge_time + 1.6

            for f in ordered_frames:
                row = timeline[f]
                t = num(row.get("time"))

                if t is None:
                    continue

                if t < start_search_time or t > end_search_time:
                    continue

                if integer(row.get(f"{car}_active")) != 1:
                    continue

                orient = orientation(
                    row,
                    car
                )

                if orient is None:
                    continue

                end_forward = orient["forward"]
                end_up = orient["up"]

                facing_dot = dot(
                    start_forward,
                    end_forward
                )

                upright = end_up[2] > 0.35

                # Dot < -0.5 means the horizontal facing
                # direction changed substantially.
                if upright and facing_dot < -0.5:
                    candidate = {
                        "jump_time": jump_time,
                        "jump_frame": jump_frame,
                        "dodge_time": dodge_time,
                        "dodge_frame": dodge_frame,
                        "end_frame": f,
                        "end_time": t,
                        "facing_dot": facing_dot,
                        "end_up_z": end_up[2],
                    }

                    if (
                        best is None
                        or abs(t - (dodge_time + 0.8))
                        < abs(best["end_time"] - (dodge_time + 0.8))
                    ):
                        best = candidate

            if best is not None:
                half_results.append({
                    "car": car,
                    "jump_frame": jump_frame,
                    "jump_time": round(jump_time, 4),
                    "dodge_frame": dodge_frame,
                    "dodge_time": round(dodge_time, 4),
                    "end_frame": best["end_frame"],
                    "end_time": round(best["end_time"], 4),
                    "facing_direction_dot": round(
                        best["facing_dot"], 3
                    ),
                    "upright_up_z": round(
                        best["end_up_z"], 3
                    ),
                    "status": (
                        "Half-flip-like candidate; flip direction unverified"
                    ),
                })


# Deduplicate similar candidates from nearby events.
half_results.sort(
    key=lambda row: (
        row["car"],
        row["jump_time"]
    )
)

deduped_half = []

for event in half_results:
    duplicate = any(
        old["car"] == event["car"]
        and abs(old["jump_time"] - event["jump_time"]) < 0.6
        for old in deduped_half
    )

    if not duplicate:
        deduped_half.append(event)

half_results = deduped_half


# ============================================================
# 4. FLIP-RESET-LIKE CANDIDATES
# ============================================================

print("Detecting flip-reset-like candidates...")

reset_results = []

for contact in contacts:
    frame = contact["frame"]
    t = contact["time"]
    car = contact["car"]

    row = timeline.get(frame)

    if row is None:
        continue

    car_z_values = []

    for f in range(frame - 4, frame + 2):
        sample = nearest_active_row(f, car)

        if sample is None:
            continue

        z = num(
            sample.get(f"{car}_z")
        )

        if z is not None:
            car_z_values.append(z)

    if not car_z_values:
        continue

    max_car_z = max(car_z_values)

    # A contact while the car is well above the ground.
    aerial_contact = max_car_z >= 250.0

    car_pos = position(row, car)
    ball_pos = position(row, "ball")

    car_above_ball = (
        car_pos is not None
        and ball_pos is not None
        and car_pos[2] >= ball_pos[2] - 20.0
    )

    recent_jump = near_times(
        jumps[car],
        t,
        before=3.0,
        after=0.05
    )

    # Look for a later Dodge event that could be consistent
    # with a flip being used after this aerial contact.
    later_dodges = [
        dt for dt in dodges[car]
        if t + 0.08 <= dt <= t + 1.8
    ]

    dodge_after = (
        min(later_dodges)
        if later_dodges else None
    )

    ball_dv = contact["ball_dv"]

    contact_strength = (
        ball_dv is not None
        and ball_dv >= 500.0
    )

    candidate = (
        aerial_contact
        and car_above_ball
        and bool(recent_jump)
        and dodge_after is not None
        and contact_strength
    )

    reset_results.append({
        "contact_id": contact["contact_id"],
        "contact_frame": frame,
        "contact_time": round(t, 4),
        "car": car,
        "max_car_z_near_contact": round(max_car_z, 2),
        "aerial_contact_proxy": int(aerial_contact),
        "car_above_ball_proxy": int(car_above_ball),
        "recent_jump": int(bool(recent_jump)),
        "dodge_after_contact_time": (
            round(dodge_after, 4)
            if dodge_after is not None else ""
        ),
        "ball_velocity_change": (
            round(ball_dv, 2)
            if ball_dv is not None else ""
        ),
        "candidate": int(candidate),
        "status": (
            "Possible flip-reset sequence; flip gain unverified"
            if candidate
            else "Insufficient evidence"
        ),
    })


# ============================================================
# 5. DOUBLE-FLIP-RESET-LIKE SEQUENCES
# ============================================================

print("Searching for possible double flip resets...")

double_results = []

possible_resets = [
    event
    for event in reset_results
    if event["candidate"] == 1
    and event["dodge_after_contact_time"] != ""
]

for first in possible_resets:
    first_dodge_time = num(
        first["dodge_after_contact_time"]
    )

    if first_dodge_time is None:
        continue

    for second in possible_resets:
        if second is first:
            continue

        if second["car"] != first["car"]:
            continue

        second_time = num(
            second["contact_time"]
        )

        second_dodge_time = num(
            second["dodge_after_contact_time"]
        )

        if (
            second_time is None
            or second_dodge_time is None
        ):
            continue

        # The second contact should occur after the first
        # contact's apparent flip-use event.
        if not (
            first_dodge_time + 0.08
            < second_time
            < first_dodge_time + 3.0
        ):
            continue

        if second_time <= num(first["contact_time"]):
            continue

        double_results.append({
            "car": first["car"],
            "first_contact_frame": first["contact_frame"],
            "first_contact_time": first["contact_time"],
            "first_dodge_time": first_dodge_time,
            "second_contact_frame": second["contact_frame"],
            "second_contact_time": second_time,
            "second_dodge_time": second_dodge_time,
            "status": (
                "Possible double-reset sequence; "
                "both flip gains unverified"
            ),
        })


# Deduplicate identical pairs.
unique_double = []
seen_pairs = set()

for event in double_results:
    key = (
        event["car"],
        event["first_contact_frame"],
        event["second_contact_frame"],
    )

    if key in seen_pairs:
        continue

    seen_pairs.add(key)
    unique_double.append(event)

double_results = unique_double


# ============================================================
# SAVE OUTPUTS
# ============================================================

save_rows(
    OUTPUTS["ground"],
    ground_results,
    [
        "contact_id",
        "frame",
        "time",
        "car",
        "samples",
        "relative_position_spread",
        "mean_car_ball_distance",
        "mean_car_z",
        "mean_ball_z",
        "ground_dribble_proxy",
        "heuristic_score",
    ]
)

save_rows(
    OUTPUTS["musty"],
    musty_results,
    [
        "contact_id",
        "frame",
        "time",
        "car",
        "recent_jump",
        "recent_dodge",
        "inverted_orientation_proxy",
        "backward_motion_proxy",
        "inverted_samples",
        "backward_samples",
        "ball_velocity_change",
        "heuristic_score",
        "status",
    ]
)

save_rows(
    OUTPUTS["half"],
    half_results,
    [
        "car",
        "jump_frame",
        "jump_time",
        "dodge_frame",
        "dodge_time",
        "end_frame",
        "end_time",
        "facing_direction_dot",
        "upright_up_z",
        "status",
    ]
)

save_rows(
    OUTPUTS["reset"],
    reset_results,
    [
        "contact_id",
        "contact_frame",
        "contact_time",
        "car",
        "max_car_z_near_contact",
        "aerial_contact_proxy",
        "car_above_ball_proxy",
        "recent_jump",
        "dodge_after_contact_time",
        "ball_velocity_change",
        "candidate",
        "status",
    ]
)

save_rows(
    OUTPUTS["double"],
    double_results,
    [
        "car",
        "first_contact_frame",
        "first_contact_time",
        "first_dodge_time",
        "second_contact_frame",
        "second_contact_time",
        "second_dodge_time",
        "status",
    ]
)


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 72)
print("REMAINING MECHANIC CANDIDATE REPORT")
print("=" * 72)

print(
    "Ground dribble proxy candidates:",
    sum(
        r["ground_dribble_proxy"]
        for r in ground_results
    ),
    "/",
    len(ground_results)
)

print(
    "Musty-like candidates:",
    sum(
        "candidate" in r["status"].lower()
        and "Musty-like" in r["status"]
        for r in musty_results
    ),
    "/",
    len(musty_results)
)

print(
    "Half-flip-like candidates:",
    len(half_results)
)

print(
    "Flip-reset-like candidates:",
    sum(r["candidate"] for r in reset_results),
    "/",
    len(reset_results)
)

print(
    "Possible double-reset sequences:",
    len(double_results)
)

print()
print("Saved files:")

for key in OUTPUTS:
    print(" ", OUTPUTS[key])

print()
print(
    "These are heuristic candidates. "
    "Flip direction and flip gain are not directly verified."
)