import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


BASE = Path("data/replays")

REPLAY_FILE = BASE / "new_test_network.json"
TIMELINE_FILE = BASE / "timeline.csv"

EVENTS_FILE = BASE / "mechanic_events.csv"
BOOST_FILE = BASE / "boost_amount_changes.csv"


# Object IDs confirmed from this replay.
OWNERSHIP_OBJECT_ID = 23
ACTIVE_OBJECT_ID = 24
BOOST_AMOUNT_OBJECT_ID = 263

COMPONENT_OBJECTS = {
    29: "FlipCar",
    191: "DoubleJump",
    240: "Jump",
    276: "Boost",
    279: "Dodge",
}


def safe_int(value):
    if value is None or value == "":
        return None

    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def safe_float(value):
    if value is None or value == "":
        return None

    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def read_slot_maps():
    """
    Map each vehicle actor ID to car1-car4 at each frame,
    using the timeline produced by extract_states.py.
    """

    slot_maps = {}

    with TIMELINE_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:
            frame = safe_int(row.get("frame"))

            if frame is None:
                continue

            actor_to_slot = {}

            for slot in range(1, 5):
                actor_id = safe_int(
                    row.get(f"car{slot}_actor")
                )

                active = safe_int(
                    row.get(f"car{slot}_active")
                )

                if actor_id is not None and active == 1:
                    actor_to_slot[actor_id] = f"car{slot}"

            slot_maps[frame] = actor_to_slot

    return slot_maps


def main():
    if not REPLAY_FILE.exists():
        raise FileNotFoundError(
            f"Replay JSON not found: {REPLAY_FILE}"
        )

    if not TIMELINE_FILE.exists():
        raise FileNotFoundError(
            f"Timeline not found: {TIMELINE_FILE}. "
            "Run python extract_states.py first."
        )

    print("Loading replay...")
    with REPLAY_FILE.open(
        "r",
        encoding="utf-8"
    ) as f:
        replay = json.load(f)

    frames = (
        replay.get("network_frames", {})
        .get("frames", [])
    )

    if not frames:
        raise RuntimeError("No network frames found.")

    print("Frames:", len(frames))
    print("Loading timeline slot assignments...")

    slot_maps = read_slot_maps()

    # Currently live actors, keyed by actor ID.
    live_actors = {}

    # Generation increments only after an actor ID disappears
    # and is subsequently reused.
    generation_counts = defaultdict(int)

    # Actor/component IDs whose initial values have been seen.
    # We use the first observed byte as a baseline, not an event.
    active_baselines = 0
    boost_baselines = 0
    duplicate_spawn_refreshes = 0

    mechanic_events = []
    boost_events = []

    component_counts = Counter()
    boost_change_counts = Counter()

    # --------------------------------------------------------
    # Iterate through the replay in chronological order.
    # --------------------------------------------------------

    for frame_number, frame in enumerate(frames):

        frame_time = safe_float(frame.get("time"))

        # ----------------------------------------------------
        # 1. Register genuinely new actors.
        # ----------------------------------------------------

        for actor in frame.get("new_actors", []):
            actor_id = safe_int(actor.get("actor_id"))
            object_id = safe_int(actor.get("object_id"))

            if actor_id is None:
                continue

            # Repeated snapshots can list an actor which is
            # already alive. Do not reset its state.
            if actor_id in live_actors:
                duplicate_spawn_refreshes += 1
                continue

            generation_counts[actor_id] += 1

            live_actors[actor_id] = {
                "actor_id": actor_id,
                "object_id": object_id,
                "component_type": COMPONENT_OBJECTS.get(
                    object_id,
                    ""
                ),
                "generation": generation_counts[actor_id],
                "owner_vehicle": None,
                "active_byte": None,
                "boost_byte": None,
            }

        # ----------------------------------------------------
        # 2. Process updates.
        # ----------------------------------------------------

        for update in frame.get("updated_actors", []):
            actor_id = safe_int(update.get("actor_id"))
            object_id = safe_int(update.get("object_id"))
            attribute = update.get("attribute")

            if actor_id is None:
                continue

            # Actor IDs not currently tracked may be stale
            # updates. Ignore them rather than guessing identity.
            actor = live_actors.get(actor_id)

            if actor is None:
                continue

            component_type = actor["component_type"]

            # ................................................
            # Ownership: mechanic component -> vehicle actor.
            # ................................................

            if object_id == OWNERSHIP_OBJECT_ID:
                if isinstance(attribute, dict):
                    active_actor = attribute.get("ActiveActor")

                    if isinstance(active_actor, dict):
                        owner_id = safe_int(
                            active_actor.get("actor")
                        )

                        is_active = active_actor.get("active")

                        if is_active is False:
                            actor["owner_vehicle"] = None
                        elif owner_id is not None:
                            actor["owner_vehicle"] = owner_id

                continue

            # Only inspect properties on known mechanic actors.
            if not component_type:
                continue

            owner_id = actor["owner_vehicle"]

            timeline_car = slot_maps.get(
                frame_number,
                {}
            ).get(owner_id)

            # ................................................
            # ReplicatedActive byte changes.
            # ................................................

            if object_id == ACTIVE_OBJECT_ID:
                if not isinstance(attribute, dict):
                    continue

                current_value = safe_int(
                    attribute.get("Byte")
                )

                if current_value is None:
                    continue

                previous_value = actor["active_byte"]

                if previous_value is None:
                    actor["active_byte"] = current_value
                    active_baselines += 1
                    continue

                if current_value == previous_value:
                    continue

                event = {
                    "frame": frame_number,
                    "time": frame_time,
                    "event_type": "ReplicatedActive_change",
                    "component_type": component_type,
                    "component_actor": actor_id,
                    "actor_generation": actor["generation"],
                    "owner_vehicle_actor": owner_id,
                    "timeline_car": timeline_car,
                    "previous_byte": previous_value,
                    "current_byte": current_value,
                    "byte_difference": (
                        current_value - previous_value
                    ),
                    "raw_attribute": json.dumps(
                        attribute,
                        sort_keys=True
                    ),
                }

                mechanic_events.append(event)
                component_counts[component_type] += 1

                actor["active_byte"] = current_value
                continue

            # ................................................
            # Boost resource updates.
            #
            # These show boost amount changes, not necessarily
            # an individual button press.
            # ................................................

            if object_id == BOOST_AMOUNT_OBJECT_ID:
                if not isinstance(attribute, dict):
                    continue

                current_value = safe_int(
                    attribute.get("Byte")
                )

                if current_value is None:
                    continue

                previous_value = actor["boost_byte"]

                if previous_value is None:
                    actor["boost_byte"] = current_value
                    boost_baselines += 1
                    continue

                if current_value == previous_value:
                    continue

                event = {
                    "frame": frame_number,
                    "time": frame_time,
                    "event_type": "boost_amount_change",
                    "component_type": component_type,
                    "component_actor": actor_id,
                    "actor_generation": actor["generation"],
                    "owner_vehicle_actor": owner_id,
                    "timeline_car": timeline_car,
                    "previous_byte": previous_value,
                    "current_byte": current_value,
                    "byte_difference": (
                        current_value - previous_value
                    ),
                    "raw_attribute": json.dumps(
                        attribute,
                        sort_keys=True
                    ),
                }

                boost_events.append(event)
                boost_change_counts[component_type] += 1

                actor["boost_byte"] = current_value

        # ----------------------------------------------------
        # 3. Process deletions after the frame's updates.
        # ----------------------------------------------------

        for deleted in frame.get("deleted_actors", []):
            actor_id = safe_int(deleted)

            if actor_id is not None:
                live_actors.pop(actor_id, None)

    # --------------------------------------------------------
    # Write mechanic state-change candidates.
    # --------------------------------------------------------

    event_fields = [
        "frame",
        "time",
        "event_type",
        "component_type",
        "component_actor",
        "actor_generation",
        "owner_vehicle_actor",
        "timeline_car",
        "previous_byte",
        "current_byte",
        "byte_difference",
        "raw_attribute",
    ]

    with EVENTS_FILE.open(
        "w",
        encoding="utf-8",
        newline=""
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=event_fields
        )

        writer.writeheader()
        writer.writerows(mechanic_events)

    # --------------------------------------------------------
    # Write boost amount changes separately.
    # --------------------------------------------------------

    with BOOST_FILE.open(
        "w",
        encoding="utf-8",
        newline=""
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=event_fields
        )

        writer.writeheader()
        writer.writerows(boost_events)

    # --------------------------------------------------------
    # Summary.
    # --------------------------------------------------------

    print()
    print("=" * 65)
    print("MECHANIC EVENT EXTRACTION COMPLETE")
    print("=" * 65)

    print("Frames scanned:", len(frames))
    print("ReplicatedActive baselines:", active_baselines)
    print("Boost amount baselines:", boost_baselines)
    print("Repeated actor refreshes ignored:",
          duplicate_spawn_refreshes)

    print()
    print("ReplicatedActive byte changes:")

    for component_type in sorted(component_counts):
        print(
            f"  {component_type}: "
            f"{component_counts[component_type]}"
        )

    print("Total state-change candidates:", len(mechanic_events))

    print()
    print("Boost amount changes:")

    for component_type in sorted(boost_change_counts):
        print(
            f"  {component_type}: "
            f"{boost_change_counts[component_type]}"
        )

    print("Total boost amount changes:", len(boost_events))

    print()
    print("Saved files:")
    print(" ", EVENTS_FILE)
    print(" ", BOOST_FILE)

    print()
    print("First 15 mechanic state-change candidates:")

    for event in mechanic_events[:15]:
        print(
            f"  frame={event['frame']:5} "
            f"time={event['time']} "
            f"type={event['component_type']:10} "
            f"car={event['timeline_car']} "
            f"byte={event['previous_byte']} "
            f"->{event['current_byte']}"
        )

    print()
    print("Done.")


if __name__ == "__main__":
    main()