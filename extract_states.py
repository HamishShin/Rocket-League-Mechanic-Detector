import csv
import json
import math


NETWORK_FILE = "data/replays/new_test_network.json"
TIMELINE_FILE = "data/replays/timeline.csv"
MAPPING_FILE = "data/replays/car_actor_mapping.csv"

MAX_ACTIVE_CARS = 4

def find_object_table_id(exact_name):
    with open(NETWORK_FILE, "r", encoding="utf-8") as f:
        network_data = json.load(f)

    object_table = network_data.get("objects", [])

    for index, entry in enumerate(object_table):
        if isinstance(entry, str) and entry == exact_name:
            return index

    raise RuntimeError(
        f"Could not find {exact_name!r} in the object table. "
        "Check the normalized network JSON and its object names."
    )


CAR_OBJECT_ID = find_object_table_id("Archetypes.Car.Car_Default")
BALL_OBJECT_ID = find_object_table_id("Archetypes.Ball.Ball_Default")

print(f"Detected car object ID: {CAR_OBJECT_ID}")
print(f"Detected ball object ID: {BALL_OBJECT_ID}")


# ============================================================
# HELPERS
# ============================================================

def safe_float(value):
    if value is None or value == "":
        return None

    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def safe_int(value):
    if value is None or value == "":
        return None

    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def parse_vector(value):
    if not isinstance(value, dict):
        return None

    x = safe_float(value.get("x"))
    y = safe_float(value.get("y"))
    z = safe_float(value.get("z"))

    if x is None or y is None or z is None:
        return None

    return (x, y, z)


def parse_quaternion(value):
    if not isinstance(value, dict):
        return None

    w = safe_float(value.get("w"))
    x = safe_float(value.get("x"))
    y = safe_float(value.get("y"))
    z = safe_float(value.get("z"))

    if (
        w is None
        or x is None
        or y is None
        or z is None
    ):
        return None

    return (w, x, y, z)


def empty_physics():
    return {
        "x": None,
        "y": None,
        "z": None,

        "rw": None,
        "rx": None,
        "ry": None,
        "rz": None,

        "vx": None,
        "vy": None,
        "vz": None,

        "avx": None,
        "avy": None,
        "avz": None,
    }


def extract_physics(value):
    """
    Recursively search for a physics structure.
    """

    if isinstance(value, dict):

        keys = set(
            str(k)
            for k in value.keys()
        )

        if (
            "location" in keys
            and (
                "rotation" in keys
                or "linear_velocity" in keys
            )
        ):

            location = parse_vector(
                value.get("location")
            )

            rotation = parse_quaternion(
                value.get("rotation")
            )

            linear_velocity = parse_vector(
                value.get("linear_velocity")
            )

            angular_velocity = parse_vector(
                value.get("angular_velocity")
            )

            return {
                "x":
                    location[0]
                    if location else None,

                "y":
                    location[1]
                    if location else None,

                "z":
                    location[2]
                    if location else None,

                "rw":
                    rotation[0]
                    if rotation else None,

                "rx":
                    rotation[1]
                    if rotation else None,

                "ry":
                    rotation[2]
                    if rotation else None,

                "rz":
                    rotation[3]
                    if rotation else None,

                "vx":
                    linear_velocity[0]
                    if linear_velocity else None,

                "vy":
                    linear_velocity[1]
                    if linear_velocity else None,

                "vz":
                    linear_velocity[2]
                    if linear_velocity else None,

                "avx":
                    angular_velocity[0]
                    if angular_velocity else None,

                "avy":
                    angular_velocity[1]
                    if angular_velocity else None,

                "avz":
                    angular_velocity[2]
                    if angular_velocity else None,
            }

        for nested in value.values():

            result = extract_physics(
                nested
            )

            if result is not None:
                return result

    elif isinstance(value, list):

        for nested in value:

            result = extract_physics(
                nested
            )

            if result is not None:
                return result

    return None


def position(physics):
    if physics is None:
        return None

    x = physics.get("x")
    y = physics.get("y")
    z = physics.get("z")

    if (
        x is None
        or y is None
        or z is None
    ):
        return None

    return (x, y, z)


def position_distance(a, b):

    if a is None or b is None:
        return float("inf")

    dx = a[0] - b[0]
    dy = a[1] - b[1]
    dz = a[2] - b[2]

    return math.sqrt(
        dx * dx
        + dy * dy
        + dz * dz
    )


# ============================================================
# LOAD REPLAY
# ============================================================

print("Loading network replay...")

with open(
    NETWORK_FILE,
    "r",
    encoding="utf-8"
) as f:

    replay = json.load(f)


frames = (
    replay
    .get("network_frames", {})
    .get("frames", [])
)


if not frames:
    raise RuntimeError(
        "No network frames found."
    )


print(
    "Network frames:",
    len(frames)
)


# ============================================================
# NAME TABLE
# ============================================================

names = replay.get(
    "names",
    []
)


def get_name(name_id):

    name_id = safe_int(
        name_id
    )

    if (
        name_id is None
        or name_id < 0
        or name_id >= len(names)
    ):
        return ""

    return str(
        names[name_id]
    )


# ============================================================
# LIVE ACTOR STATE
# ============================================================

actors = {}

slot_actor = {
    1: None,
    2: None,
    3: None,
    4: None,
}

slot_last_position = {
    1: None,
    2: None,
    3: None,
    4: None,
}

car_lifecycles = []

next_lifecycle_id = 1

active_ball_ids = set()

overflow_frames = 0

duplicate_new_actor_events = 0


# ============================================================
# REGISTER NEW ACTOR
# ============================================================

def register_new_actor(
    actor,
    frame_number,
    frame_time
):

    global next_lifecycle_id
    global duplicate_new_actor_events


    actor_id = safe_int(
        actor.get("actor_id")
    )

    object_id = safe_int(
        actor.get("object_id")
    )

    name_id = safe_int(
        actor.get("name_id")
    )


    if actor_id is None:
        return


    name = get_name(
        name_id
    )


    # --------------------------------------------------------
    # IMPORTANT:
    #
    # rrrocket can emit an already-live actor inside
    # new_actors again during replication refreshes.
    #
    # If the actor ID already exists in our live actor table,
    # DO NOT create another lifecycle.
    # --------------------------------------------------------

    if actor_id in actors:

        duplicate_new_actor_events += 1


        existing = actors[
            actor_id
        ]


        # Refresh any information provided by this packet.
        if object_id is not None:

            existing[
                "object_id"
            ] = object_id


        if name:

            existing[
                "name"
            ] = name


        physics = extract_physics(
            actor.get(
                "initial_trajectory"
            )
        )


        if physics is not None:

            existing[
                "physics"
            ] = physics


        return


    # --------------------------------------------------------
    # This is genuinely a new live actor.
    # --------------------------------------------------------

    is_car = (
        object_id == CAR_OBJECT_ID
        and name.startswith("Car_TA_")
    )


    is_ball = (
        object_id == BALL_OBJECT_ID
        and name.startswith("Ball_TA_")
    )


    physics = extract_physics(
        actor.get(
            "initial_trajectory"
        )
    )


    if physics is None:

        physics = empty_physics()


    actors[actor_id] = {

        "actor_id":
            actor_id,

        "object_id":
            object_id,

        "name":
            name,

        "is_car":
            is_car,

        "is_ball":
            is_ball,

        "physics":
            physics,

        "spawn_frame":
            frame_number,

        "spawn_time":
            frame_time,

        "lifecycle_id":
            None,
    }


    # --------------------------------------------------------
    # Ball
    # --------------------------------------------------------

    if is_ball:

        active_ball_ids.add(
            actor_id
        )


    # --------------------------------------------------------
    # Car lifecycle
    # --------------------------------------------------------

    if is_car:

        lifecycle = {

            "lifecycle_id":
                next_lifecycle_id,

            "actor_id":
                actor_id,

            "name":
                name,

            "spawn_frame":
                frame_number,

            "spawn_time":
                frame_time,

            "end_frame":
                "",

            "end_time":
                "",

            "timeline_car":
                "",
        }


        actors[
            actor_id
        ][
            "lifecycle_id"
        ] = next_lifecycle_id


        car_lifecycles.append(
            lifecycle
        )


        next_lifecycle_id += 1


# ============================================================
# UPDATE ACTOR
# ============================================================

def update_actor(update):

    actor_id = safe_int(
        update.get("actor_id")
    )


    if actor_id is None:
        return


    actor = actors.get(
        actor_id
    )


    if actor is None:
        return


    physics = extract_physics(
        update.get("attribute")
    )


    if physics is not None:

        actor[
            "physics"
        ] = physics


# ============================================================
# DELETE ACTOR
# ============================================================

def delete_actor(
    actor_id,
    frame_number,
    frame_time
):

    actor_id = safe_int(
        actor_id
    )


    if actor_id is None:
        return


    actor = actors.get(
        actor_id
    )


    if actor is None:
        return


    # --------------------------------------------------------
    # Ball
    # --------------------------------------------------------

    if actor.get("is_ball"):

        active_ball_ids.discard(
            actor_id
        )


    # --------------------------------------------------------
    # Car lifecycle
    # --------------------------------------------------------

    lifecycle_id = actor.get(
        "lifecycle_id"
    )


    if lifecycle_id is not None:

        for lifecycle in car_lifecycles:

            if (
                lifecycle[
                    "lifecycle_id"
                ]
                == lifecycle_id
            ):

                if (
                    lifecycle[
                        "end_frame"
                    ] == ""
                ):

                    lifecycle[
                        "end_frame"
                    ] = frame_number

                    lifecycle[
                        "end_time"
                    ] = frame_time

                break


    # --------------------------------------------------------
    # Release car slot
    # --------------------------------------------------------

    for slot in range(
        1,
        MAX_ACTIVE_CARS + 1
    ):

        if (
            slot_actor[slot]
            == actor_id
        ):

            physics = actor.get(
                "physics",
                empty_physics()
            )


            actor_position = position(
                physics
            )


            if actor_position is not None:

                slot_last_position[
                    slot
                ] = actor_position


            slot_actor[slot] = None


    # --------------------------------------------------------
    # Remove live actor
    # --------------------------------------------------------

    actors.pop(
        actor_id,
        None
    )


# ============================================================
# CURRENT CAR ACTORS
# ============================================================

def current_car_ids():

    result = []

    for actor_id, actor in actors.items():

        if not actor.get(
            "is_car",
            False
        ):
            continue

        result.append(
            actor_id
        )

    return result


# ============================================================
# ASSIGN FOUR CAR SLOTS
# ============================================================

def assign_car_slots():

    global overflow_frames


    active_ids = current_car_ids()


    assigned = {}

    used_actor_ids = set()

    used_slots = set()


    # --------------------------------------------------------
    # Keep already assigned cars in their current slots.
    # --------------------------------------------------------

    for slot in range(
        1,
        MAX_ACTIVE_CARS + 1
    ):

        actor_id = slot_actor[
            slot
        ]


        if (
            actor_id is not None
            and actor_id in active_ids
        ):

            assigned[
                slot
            ] = actor_id


            used_actor_ids.add(
                actor_id
            )


            used_slots.add(
                slot
            )


    # --------------------------------------------------------
    # Find newly available cars.
    # --------------------------------------------------------

    new_ids = [

        actor_id

        for actor_id in active_ids

        if actor_id not in used_actor_ids

    ]


    free_slots = [

        slot

        for slot in range(
            1,
            MAX_ACTIVE_CARS + 1
        )

        if slot not in used_slots

    ]


    # --------------------------------------------------------
    # More than four live Car_TA actors can briefly coexist.
    #
    # Existing assignments are protected.
    # Extra actors simply remain unassigned until a slot opens.
    # --------------------------------------------------------

    if len(active_ids) > MAX_ACTIVE_CARS:

        overflow_frames += 1


    # --------------------------------------------------------
    # Fill available slots.
    # --------------------------------------------------------

    for slot in free_slots:

        if not new_ids:
            break


        previous_position = (
            slot_last_position[
                slot
            ]
        )


        def candidate_key(
            actor_id
        ):

            actor = actors.get(
                actor_id
            )


            if actor is None:

                return (
                    999999999,
                    999999999,
                    actor_id
                )


            actor_position = position(
                actor.get(
                    "physics",
                    empty_physics()
                )
            )


            if (
                previous_position is not None
                and actor_position is not None
            ):

                return (
                    position_distance(
                        actor_position,
                        previous_position
                    ),

                    actor.get(
                        "spawn_frame",
                        999999999
                    ),

                    actor_id,
                )


            return (
                999999998,

                actor.get(
                    "spawn_frame",
                    999999999
                ),

                actor_id,
            )


        chosen_actor_id = min(
            new_ids,
            key=candidate_key
        )


        assigned[
            slot
        ] = chosen_actor_id


        new_ids.remove(
            chosen_actor_id
        )


    # --------------------------------------------------------
    # Update slot state.
    # --------------------------------------------------------

    for slot in range(
        1,
        MAX_ACTIVE_CARS + 1
    ):

        actor_id = assigned.get(
            slot
        )


        slot_actor[
            slot
        ] = actor_id


        if actor_id is None:
            continue


        actor = actors.get(
            actor_id
        )


        if actor is None:
            continue


        actor_position = position(
            actor.get(
                "physics",
                empty_physics()
            )
        )


        if actor_position is not None:

            slot_last_position[
                slot
            ] = actor_position


    # --------------------------------------------------------
    # Save which timeline slot this lifecycle used.
    # --------------------------------------------------------

    for slot, actor_id in assigned.items():

        if actor_id is None:
            continue


        actor = actors.get(
            actor_id
        )


        if actor is None:
            continue


        lifecycle_id = actor.get(
            "lifecycle_id"
        )


        if lifecycle_id is None:
            continue


        for lifecycle in car_lifecycles:

            if (
                lifecycle[
                    "lifecycle_id"
                ]
                == lifecycle_id
            ):

                if (
                    lifecycle[
                        "timeline_car"
                    ] == ""
                ):

                    lifecycle[
                        "timeline_car"
                    ] = (
                        f"car{slot}"
                    )

                break


    return assigned


# ============================================================
# TIMELINE COLUMNS
# ============================================================

fieldnames = [
    "frame",
    "time",
    "delta",

    "ball_actor",

    "ball_x",
    "ball_y",
    "ball_z",

    "ball_rw",
    "ball_rx",
    "ball_ry",
    "ball_rz",

    "ball_vx",
    "ball_vy",
    "ball_vz",
]


for slot in range(
    1,
    MAX_ACTIVE_CARS + 1
):

    prefix = f"car{slot}"


    fieldnames.extend([

        prefix + "_active",
        prefix + "_actor",

        prefix + "_x",
        prefix + "_y",
        prefix + "_z",

        prefix + "_rw",
        prefix + "_rx",
        prefix + "_ry",
        prefix + "_rz",

        prefix + "_vx",
        prefix + "_vy",
        prefix + "_vz",

        prefix + "_avx",
        prefix + "_avy",
        prefix + "_avz",
    ])


# ============================================================
# BUILD TIMELINE
# ============================================================

print()
print(
    "Building four-player timeline..."
)


timeline_rows = []


for frame_number, frame in enumerate(
    frames
):

    frame_time = safe_float(
        frame.get("time")
    )

    delta = safe_float(
        frame.get("delta")
    )


    # --------------------------------------------------------
    # New actors
    # --------------------------------------------------------

    for actor in frame.get(
        "new_actors",
        []
    ):

        register_new_actor(
            actor,
            frame_number,
            frame_time
        )


    # --------------------------------------------------------
    # Updates
    # --------------------------------------------------------

    for update in frame.get(
        "updated_actors",
        []
    ):

        update_actor(
            update
        )


    # --------------------------------------------------------
    # Deletes
    # --------------------------------------------------------

    for actor_id in frame.get(
        "deleted_actors",
        []
    ):

        delete_actor(
            actor_id,
            frame_number,
            frame_time
        )


    # --------------------------------------------------------
    # Car slots
    # --------------------------------------------------------

    assigned = assign_car_slots()


    # --------------------------------------------------------
    # Start row
    # --------------------------------------------------------

    row = {

        "frame":
            frame_number,

        "time":
            frame_time,

        "delta":
            delta,

        "ball_actor":
            "",
    }


    # ========================================================
    # BALL
    # ========================================================

    best_ball = None

    best_spawn_frame = -1


    for actor_id in active_ball_ids:

        actor = actors.get(
            actor_id
        )


        if actor is None:
            continue


        physics = actor.get(
            "physics",
            empty_physics()
        )


        if physics.get("x") is None:
            continue


        spawn_frame = actor.get(
            "spawn_frame",
            -1
        )


        if (
            spawn_frame
            > best_spawn_frame
        ):

            best_spawn_frame = (
                spawn_frame
            )

            best_ball = actor


    if best_ball is not None:

        physics = best_ball[
            "physics"
        ]


        row[
            "ball_actor"
        ] = best_ball[
            "actor_id"
        ]


        for suffix in [
            "x",
            "y",
            "z",

            "rw",
            "rx",
            "ry",
            "rz",

            "vx",
            "vy",
            "vz",
        ]:

            row[
                "ball_" + suffix
            ] = physics.get(
                suffix
            )


    else:

        for suffix in [
            "x",
            "y",
            "z",

            "rw",
            "rx",
            "ry",
            "rz",

            "vx",
            "vy",
            "vz",
        ]:

            row[
                "ball_" + suffix
            ] = ""


    # ========================================================
    # CARS
    # ========================================================

    for slot in range(
        1,
        MAX_ACTIVE_CARS + 1
    ):

        prefix = f"car{slot}"

        actor_id = assigned.get(
            slot
        )


        actor = None


        if actor_id is not None:

            actor = actors.get(
                actor_id
            )


        # ----------------------------------------------------
        # Empty slot
        # ----------------------------------------------------

        if actor is None:

            row[
                prefix + "_active"
            ] = 0


            row[
                prefix + "_actor"
            ] = ""


            for suffix in [
                "x",
                "y",
                "z",

                "rw",
                "rx",
                "ry",
                "rz",

                "vx",
                "vy",
                "vz",

                "avx",
                "avy",
                "avz",
            ]:

                row[
                    prefix
                    + "_"
                    + suffix
                ] = ""

            continue


        # ----------------------------------------------------
        # Active car
        # ----------------------------------------------------

        physics = actor.get(
            "physics",
            empty_physics()
        )


        row[
            prefix + "_active"
        ] = 1


        row[
            prefix + "_actor"
        ] = actor_id


        for suffix in [
            "x",
            "y",
            "z",

            "rw",
            "rx",
            "ry",
            "rz",

            "vx",
            "vy",
            "vz",

            "avx",
            "avy",
            "avz",
        ]:

            row[
                prefix
                + "_"
                + suffix
            ] = physics.get(
                suffix
            )


    timeline_rows.append(
        row
    )


# ============================================================
# CLOSE OPEN LIFECYCLES
# ============================================================

if frames:

    final_frame = (
        len(frames) - 1
    )

    final_time = safe_float(
        frames[-1].get("time")
    )


    for lifecycle in car_lifecycles:

        if (
            lifecycle[
                "end_frame"
            ] == ""
        ):

            lifecycle[
                "end_frame"
            ] = final_frame


            lifecycle[
                "end_time"
            ] = final_time


# ============================================================
# SAVE TIMELINE
# ============================================================

print()
print(
    "Saving timeline..."
)


with open(
    TIMELINE_FILE,
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
        timeline_rows
    )


# ============================================================
# SAVE CAR MAPPING
# ============================================================

mapping_fields = [
    "lifecycle_id",
    "actor_id",
    "name",

    "spawn_frame",
    "spawn_time",

    "end_frame",
    "end_time",

    "timeline_car",
]


with open(
    MAPPING_FILE,
    "w",
    encoding="utf-8",
    newline=""
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=mapping_fields
    )

    writer.writeheader()

    writer.writerows(
        car_lifecycles
    )


# ============================================================
# BALL LIFECYCLE COUNT
# ============================================================

ball_lifecycle_count = 0


seen_ball_actor_ids = set()


for frame in frames:

    for actor in frame.get(
        "new_actors",
        []
    ):

        actor_id = safe_int(
            actor.get("actor_id")
        )

        object_id = safe_int(
            actor.get("object_id")
        )


        if (
            object_id == BALL_OBJECT_ID
            and actor_id is not None
            and actor_id not in seen_ball_actor_ids
        ):

            seen_ball_actor_ids.add(
                actor_id
            )

            ball_lifecycle_count += 1


# ============================================================
# BALL COVERAGE
# ============================================================

valid_ball_rows = 0


for row in timeline_rows:

    if (
        row["ball_x"] not in ("", None)
        and
        row["ball_y"] not in ("", None)
        and
        row["ball_z"] not in ("", None)
    ):

        valid_ball_rows += 1


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 72)
print("TIMELINE BUILD COMPLETE")
print("=" * 72)

print(
    "Frames:",
    len(timeline_rows)
)

print(
    "Car lifecycles:",
    len(car_lifecycles)
)

print(
    "Unique ball actor IDs:",
    ball_lifecycle_count
)

print(
    "Rows with valid ball:",
    valid_ball_rows,
    "/",
    len(timeline_rows)
)

print(
    "Frames with >4 live Car_TA actors:",
    overflow_frames
)

print(
    "Duplicate new-actor refreshes ignored:",
    duplicate_new_actor_events
)


print()
print(
    "Timeline slots:"
)

print(
    "  car1"
)

print(
    "  car2"
)

print(
    "  car3"
)

print(
    "  car4"
)


# ============================================================
# FIRST LIFECYCLES
# ============================================================

print()
print(
    "First car lifecycles:"
)


for lifecycle in car_lifecycles[:40]:

    timeline_car = (
        lifecycle[
            "timeline_car"
        ]
        or "-"
    )


    print(
        f"  id={lifecycle['lifecycle_id']:3d} "
        f"actor={lifecycle['actor_id']:4d} "
        f"slot={timeline_car:5s} "
        f"spawn={lifecycle['spawn_frame']:5d} "
        f"end={lifecycle['end_frame']:5d} "
        f"{lifecycle['name']}"
    )


# ============================================================
# FILES
# ============================================================

print()
print(
    "Saved:"
)

print(
    " ",
    TIMELINE_FILE
)

print(
    " ",
    MAPPING_FILE
)

print()
print("=" * 72)
print("DONE")
print("=" * 72)