import csv
import math
from collections import defaultdict


TIMELINE_FILE = "data/replays/timeline.csv"
OUTPUT_FILE = "data/replays/ball_contact_candidates.csv"


# ============================================================
# SETTINGS
# ============================================================

# A large sudden change in ball velocity is a useful contact
# candidate, but NOT proof of a car-ball touch.
BALL_VELOCITY_CHANGE_THRESHOLD = 250.0

# Candidate car-ball distance in Rocket League unreal units.
CONTACT_DISTANCE_THRESHOLD = 260.0

# Ignore extremely slow cars.
MIN_CAR_SPEED = 150.0


# ============================================================
# HELPERS
# ============================================================

def to_float(value):

    if value is None or value == "":
        return None

    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def speed(vx, vy, vz):

    if (
        vx is None
        or vy is None
        or vz is None
    ):
        return None

    return math.sqrt(
        vx * vx
        + vy * vy
        + vz * vz
    )


def distance(
    x1, y1, z1,
    x2, y2, z2
):

    values = [
        x1, y1, z1,
        x2, y2, z2
    ]

    if any(
        value is None
        for value in values
    ):
        return None

    dx = x2 - x1
    dy = y2 - y1
    dz = z2 - z1

    return math.sqrt(
        dx * dx
        + dy * dy
        + dz * dz
    )


def dot(
    ax, ay, az,
    bx, by, bz
):

    if any(
        value is None
        for value in [
            ax, ay, az,
            bx, by, bz
        ]
    ):
        return None

    return (
        ax * bx
        + ay * by
        + az * bz
    )


# ============================================================
# LOAD TIMELINE
# ============================================================

print("Loading timeline...")

with open(
    TIMELINE_FILE,
    "r",
    encoding="utf-8",
    newline=""
) as f:

    reader = csv.DictReader(f)

    fields = reader.fieldnames

    if not fields:
        raise RuntimeError(
            "timeline.csv has no header."
        )

    rows = list(reader)


print(
    "Timeline rows:",
    len(rows)
)


required_ball_columns = [
    "ball_x",
    "ball_y",
    "ball_z",
    "ball_vx",
    "ball_vy",
    "ball_vz",
]


for column in required_ball_columns:

    if column not in fields:

        raise RuntimeError(
            f"Missing ball column: {column}"
        )


# ============================================================
# DISCOVER CAR COLUMNS
# ============================================================

cars = []

for car_number in range(1, 26):

    prefix = f"car{car_number}_"

    required = [
        prefix + "x",
        prefix + "y",
        prefix + "z",
        prefix + "vx",
        prefix + "vy",
        prefix + "vz",
    ]

    if all(
        column in fields
        for column in required
    ):

        cars.append(
            f"car{car_number}"
        )


print(
    "Cars found:",
    len(cars)
)


# ============================================================
# DETECT CANDIDATES
# ============================================================

print()
print("Scanning for car-ball contact candidates...")

candidates = []


for i in range(
    len(rows) - 1
):

    before = rows[i]
    after = rows[i + 1]

    frame_before = int(
        float(before["frame"])
    )

    frame_after = int(
        float(after["frame"])
    )

    # We only compare adjacent replay frames.
    if frame_after != frame_before + 1:
        continue

    time_before = to_float(
        before.get("time")
    )

    time_after = to_float(
        after.get("time")
    )

    # --------------------------------------------------------
    # Ball before / after
    # --------------------------------------------------------

    bx0 = to_float(
        before["ball_x"]
    )
    by0 = to_float(
        before["ball_y"]
    )
    bz0 = to_float(
        before["ball_z"]
    )

    bvx0 = to_float(
        before["ball_vx"]
    )
    bvy0 = to_float(
        before["ball_vy"]
    )
    bvz0 = to_float(
        before["ball_vz"]
    )

    bx1 = to_float(
        after["ball_x"]
    )
    by1 = to_float(
        after["ball_y"]
    )
    bz1 = to_float(
        after["ball_z"]
    )

    bvx1 = to_float(
        after["ball_vx"]
    )
    bvy1 = to_float(
        after["ball_vy"]
    )
    bvz1 = to_float(
        after["ball_vz"]
    )

    if any(
        value is None
        for value in [
            bx0, by0, bz0,
            bvx0, bvy0, bvz0,
            bx1, by1, bz1,
            bvx1, bvy1, bvz1
        ]
    ):
        continue

    # Ball velocity change
    dvx = bvx1 - bvx0
    dvy = bvy1 - bvy0
    dvz = bvz1 - bvz0

    ball_dv = speed(
        dvx,
        dvy,
        dvz
    )

    if ball_dv is None:
        continue

    if ball_dv < BALL_VELOCITY_CHANGE_THRESHOLD:
        continue

    # --------------------------------------------------------
    # Check every car
    # --------------------------------------------------------

    for car in cars:

        prefix = car + "_"

        cx0 = to_float(
            before.get(prefix + "x")
        )
        cy0 = to_float(
            before.get(prefix + "y")
        )
        cz0 = to_float(
            before.get(prefix + "z")
        )

        cvx0 = to_float(
            before.get(prefix + "vx")
        )
        cvy0 = to_float(
            before.get(prefix + "vy")
        )
        cvz0 = to_float(
            before.get(prefix + "vz")
        )

        cx1 = to_float(
            after.get(prefix + "x")
        )
        cy1 = to_float(
            after.get(prefix + "y")
        )
        cz1 = to_float(
            after.get(prefix + "z")
        )

        cvx1 = to_float(
            after.get(prefix + "vx")
        )
        cvy1 = to_float(
            after.get(prefix + "vy")
        )
        cvz1 = to_float(
            after.get(prefix + "vz")
        )

        if any(
            value is None
            for value in [
                cx0, cy0, cz0,
                cvx0, cvy0, cvz0,
                cx1, cy1, cz1,
                cvx1, cvy1, cvz1
            ]
        ):
            continue

        car_speed = speed(
            cvx0,
            cvy0,
            cvz0
        )

        if (
            car_speed is None
            or car_speed < MIN_CAR_SPEED
        ):
            continue

        distance_before = distance(
            cx0, cy0, cz0,
            bx0, by0, bz0
        )

        distance_after = distance(
            cx1, cy1, cz1,
            bx1, by1, bz1
        )

        if (
            distance_before is None
            or distance_after is None
        ):
            continue

        min_distance = min(
            distance_before,
            distance_after
        )

        if min_distance > CONTACT_DISTANCE_THRESHOLD:
            continue

        # ----------------------------------------------------
        # Direction of ball velocity change relative to the
        # car -> ball direction.
        #
        # This is only a feature, not a verdict.
        # ----------------------------------------------------

        rx = bx0 - cx0
        ry = by0 - cy0
        rz = bz0 - cz0

        distance_length = math.sqrt(
            rx * rx
            + ry * ry
            + rz * rz
        )

        dv_length = math.sqrt(
            dvx * dvx
            + dvy * dvy
            + dvz * dvz
        )

        alignment = None

        if (
            distance_length > 0
            and dv_length > 0
        ):

            alignment = (
                (
                    dvx * rx
                    + dvy * ry
                    + dvz * rz
                )
                /
                (
                    distance_length
                    * dv_length
                )
            )

        # ----------------------------------------------------
        # Relative car/ball velocity
        # ----------------------------------------------------

        rvx = bvx0 - cvx0
        rvy = bvy0 - cvy0
        rvz = bvz0 - cvz0

        relative_speed = speed(
            rvx,
            rvy,
            rvz
        )

        # ----------------------------------------------------
        # Candidate
        # ----------------------------------------------------

        candidates.append({

            "frame_before":
                frame_before,

            "frame_after":
                frame_after,

            "time_before":
                time_before,

            "time_after":
                time_after,

            "car":
                car,

            "distance_before":
                distance_before,

            "distance_after":
                distance_after,

            "min_distance":
                min_distance,

            "car_speed":
                car_speed,

            "ball_dv":
                ball_dv,

            "alignment":
                alignment,

            "relative_speed":
                relative_speed,

            "ball_vx_before":
                bvx0,

            "ball_vy_before":
                bvy0,

            "ball_vz_before":
                bvz0,

            "ball_vx_after":
                bvx1,

            "ball_vy_after":
                bvy1,

            "ball_vz_after":
                bvz1,

            "car_x":
                cx0,

            "car_y":
                cy0,

            "car_z":
                cz0,

            "ball_x":
                bx0,

            "ball_y":
                by0,

            "ball_z":
                bz0,
        })


# ============================================================
# REMOVE DUPLICATE NEARBY CANDIDATES
# ============================================================

# Several cars can occasionally satisfy the loose distance
# condition on the same frame. Keep the strongest candidate
# per frame.

best_by_frame = {}

for candidate in candidates:

    frame = candidate[
        "frame_before"
    ]

    existing = best_by_frame.get(
        frame
    )

    if existing is None:

        best_by_frame[
            frame
        ] = candidate

    else:

        candidate_score = (
            candidate["ball_dv"]
            /
            max(
                candidate["min_distance"],
                1.0
            )
        )

        existing_score = (
            existing["ball_dv"]
            /
            max(
                existing["min_distance"],
                1.0
            )
        )

        if candidate_score > existing_score:

            best_by_frame[
                frame
            ] = candidate


candidates = list(
    best_by_frame.values()
)

candidates.sort(
    key=lambda item:
        item["time_before"]
        if item["time_before"] is not None
        else item["frame_before"]
)


# ============================================================
# SAVE
# ============================================================

fieldnames = [
    "frame_before",
    "frame_after",

    "time_before",
    "time_after",

    "car",

    "distance_before",
    "distance_after",
    "min_distance",

    "car_speed",
    "ball_dv",
    "alignment",
    "relative_speed",

    "ball_vx_before",
    "ball_vy_before",
    "ball_vz_before",

    "ball_vx_after",
    "ball_vy_after",
    "ball_vz_after",

    "car_x",
    "car_y",
    "car_z",

    "ball_x",
    "ball_y",
    "ball_z",
]


with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8",
    newline=""
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fieldnames
    )

    writer.writeheader()

    writer.writerows(
        candidates
    )


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 72)
print("BALL CONTACT CANDIDATES")
print("=" * 72)

print(
    "Raw candidates     :",
    len(
        candidates
    )
)

print(
    "Saved candidates   :",
    len(
        candidates
    )
)

print()
print("Strongest candidates:")

strongest = sorted(
    candidates,
    key=lambda item:
        item["ball_dv"]
        /
        max(
            item["min_distance"],
            1.0
        ),
    reverse=True
)


for candidate in strongest[:40]:

    alignment = candidate[
        "alignment"
    ]

    alignment_text = (
        f"{alignment:.3f}"
        if alignment is not None
        else "N/A"
    )

    print(
        f"time={candidate['time_before']:8.3f} "
        f"frame={candidate['frame_before']:5d} "
        f"car={candidate['car']:6s} "
        f"dist={candidate['min_distance']:7.2f} "
        f"ball_dv={candidate['ball_dv']:8.2f} "
        f"align={alignment_text}"
    )


print()
print("Candidates by car:")

car_counts = defaultdict(int)

for candidate in candidates:

    car_counts[
        candidate["car"]
    ] += 1

for car in sorted(car_counts):

    print(
        f"  {car:6s}"
        f"{car_counts[car]:6d}"
    )


print()
print("Saved:")
print(OUTPUT_FILE)