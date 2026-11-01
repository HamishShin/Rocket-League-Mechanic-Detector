import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPLAYS_DIR = ROOT / "data" / "replays"
PROCESSED_DIR = ROOT / "data" / "processed"

RRROCKET = ROOT / "rrrocket.exe"

METADATA_JSON = REPLAYS_DIR / "new_test.json"
NETWORK_JSON = REPLAYS_DIR / "new_test_network.json"

REVIEWED_REPLAY_ID = "758D309B481126DD941A8A913799FE60"

# The downstream scripts expect these normalized object IDs.
# The actual indices in an individual replay are discovered
# from that replay's objects table.
CANONICAL_OBJECTS = {
    23: "TAGame.CarComponent_TA:Vehicle",
    24: "TAGame.CarComponent_TA:ReplicatedActive",
    26: "TAGame.CarComponent_FlipCar_TA:bFlipRight",
    27: "TAGame.CarComponent_FlipCar_TA:FlipCarTime",
    29: "Archetypes.CarComponents.CarComponent_FlipCar",

    48: "TAGame.GameEvent_Soccar_TA:ReplicatedStatEvent",

    189: "TAGame.CarComponent_DoubleJump_TA:DoubleJumpImpulse",
    191: "Archetypes.CarComponents.CarComponent_DoubleJump",

    238: "TAGame.Ball_TA",
    239: "TAGame.CarComponent_Jump_TA",
    240: "Archetypes.CarComponents.CarComponent_Jump",

    263: "TAGame.CarComponent_Boost_TA:ReplicatedBoostAmount",
    276: "Archetypes.CarComponents.CarComponent_Boost",

    277: "TAGame.CarComponent_Dodge_TA:DodgeTorque",
    279: "Archetypes.CarComponents.CarComponent_Dodge",

    304: "TAGame.Car_TA",
    374: "StatEvents.Events.Goal",
}

REQUIRED_OBJECT_IDS = {
    23, 24, 29, 48, 191, 238, 240, 263, 276, 279, 304, 374
}

ARCHIVE_FILES = [
    "timeline.csv",
    "car_actor_mapping.csv",
    "mechanic_events.csv",
    "boost_amount_changes.csv",
    "ball_contact_candidates.csv",
    "ball_contacts.csv",
    "flick_candidates.csv",
    "double_tap_candidates.csv",
    "wall_bounce_candidates.csv",
    "ground_dribble_candidates.csv",
    "musty_flick_candidates.csv",
    "half_flip_candidates.csv",
    "flip_reset_candidates.csv",
    "double_flip_reset_candidates.csv",
    "air_dribble_sequence_candidates.csv",
    "manual_air_dribble_labels.csv",
    "master_mechanic_all_results.csv",
    "master_mechanic_candidates.csv",
]


def safe_int(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (ValueError, TypeError):
        return None


def find_key(data, wanted):
    if isinstance(data, dict):
        for key, value in data.items():
            if str(key).lower() == wanted.lower():
                return value

        for value in data.values():
            result = find_key(value, wanted)
            if result is not None:
                return result

    elif isinstance(data, list):
        for item in data:
            result = find_key(item, wanted)
            if result is not None:
                return result

    return None


def choose_replay(argument):
    if argument:
        path = Path(argument).expanduser()

        if not path.is_absolute():
            path = ROOT / path

        path = path.resolve()

        if not path.is_file():
            raise FileNotFoundError(
                f"Replay not found: {path}"
            )

        if path.suffix.lower() != ".replay":
            raise ValueError(
                "Please provide a .replay file."
            )

        return path

    choices = sorted(REPLAYS_DIR.glob("*.replay"))

    if not choices:
        raise FileNotFoundError(
            f"No replay files found in {REPLAYS_DIR}"
        )

    print()
    print("Available replays:")

    for number, path in enumerate(choices, start=1):
        print(f"  {number}. {path.name}")

    while True:
        selection = input(
            "\nEnter the replay number: "
        ).strip()

        try:
            index = int(selection) - 1

            if 0 <= index < len(choices):
                return choices[index].resolve()

        except ValueError:
            pass

        print("Enter one of the listed numbers.")


def run_parser(arguments, output_path):
    print(
        "Running:",
        " ".join(str(part) for part in arguments)
    )

    with output_path.open(
        "w",
        encoding="utf-8"
    ) as output:
        result = subprocess.run(
            arguments,
            cwd=ROOT,
            stdout=output,
            check=False,
        )

    if result.returncode != 0:
        raise RuntimeError(
            f"Replay parser failed with exit code "
            f"{result.returncode}"
        )

    with output_path.open(
        "r",
        encoding="utf-8"
    ) as f:
        json.load(f)


def find_table_index(objects, wanted):
    """
    Find an exact object-table entry.

    Only the car and ball class names allow a root-name fallback;
    property entries such as ReplicatedActive must match exactly.
    """

    wanted = wanted.strip()

    for index, entry in enumerate(objects):
        if str(entry).strip() == wanted:
            return index

    if wanted in {"TAGame.Car_TA", "TAGame.Ball_TA"}:
        matches = []

        for index, entry in enumerate(objects):
            text = str(entry).strip()

            if text.split(":", 1)[0] == wanted:
                matches.append(index)

        if len(matches) == 1:
            return matches[0]

    return None


def normalize_network_json(path):
    """
    Remap object references into the canonical IDs used by the
    existing pipeline.

    This transforms the network JSON itself, including actor class
    IDs, update property IDs, the object table, and the nested
    StatEvent goal ID. Actor IDs and name IDs are left unchanged.
    """

    print()
    print("Discovering replay-specific object IDs...")

    with path.open(
        "r",
        encoding="utf-8"
    ) as f:
        data = json.load(f)

    objects = data.get("objects", [])

    if not isinstance(objects, list) or not objects:
        raise RuntimeError(
            "Network JSON has no usable objects table."
        )

    raw_to_canonical = {}
    canonical_to_raw = {}
    missing = []

    for canonical_id, object_name in CANONICAL_OBJECTS.items():
        raw_id = find_table_index(
            objects,
            object_name
        )

        if raw_id is None:
            if canonical_id in REQUIRED_OBJECT_IDS:
                missing.append(
                    (canonical_id, object_name)
                )
            continue

        if raw_id in raw_to_canonical:
            previous = raw_to_canonical[raw_id]
            raise RuntimeError(
                f"Object table collision: raw ID {raw_id} "
                f"matched canonical IDs {previous} and "
                f"{canonical_id}."
            )

        raw_to_canonical[raw_id] = canonical_id
        canonical_to_raw[canonical_id] = raw_id

    if missing:
        print()
        print("Required object names missing from this replay:")

        for canonical_id, name in missing:
            print(f"  expected {canonical_id}: {name}")

        print()
        print("Some similarly named entries, if present:")

        keywords = (
            "Car_TA",
            "Ball_TA",
            "CarComponent",
            "ReplicatedStatEvent",
            "StatEvents.Events.Goal",
        )

        shown = 0

        for raw_id, entry in enumerate(objects):
            text = str(entry)

            if any(word in text for word in keywords):
                print(f"  raw {raw_id}: {text}")
                shown += 1

                if shown >= 60:
                    break

        raise RuntimeError(
            "This replay's object table is missing required "
            "entries. Stopping rather than producing unreliable "
            "mechanic detections."
        )

    # Reserve every canonical slot. Any other raw object table
    # entry is moved to a free ID, avoiding collisions.
    reserved_ids = set(
        CANONICAL_OBJECTS.keys()
    )

    table_size = max(
        len(objects) + len(CANONICAL_OBJECTS),
        max(reserved_ids) + 1
    )

    normalized_objects = [""] * table_size

    # Put known objects at their canonical indices.
    for raw_id, canonical_id in raw_to_canonical.items():
        normalized_objects[canonical_id] = str(
            objects[raw_id]
        )

    free_ids = (
        index
        for index in range(table_size)
        if index not in reserved_ids
    )

    raw_to_normalized = dict(
        raw_to_canonical
    )

    # Remap all remaining table entries into the free positions.
    for raw_id, entry in enumerate(objects):
        if raw_id in raw_to_normalized:
            continue

        new_id = next(free_ids)

        raw_to_normalized[raw_id] = new_id
        normalized_objects[new_id] = str(entry)

    # Confirm that the primary actor classes landed in the
    # expected canonical positions.
    if normalized_objects[304] != "TAGame.Car_TA":
        raise RuntimeError(
            "Could not normalize the Car_TA object."
        )

    if normalized_objects[238] != "TAGame.Ball_TA":
        raise RuntimeError(
            "Could not normalize the Ball_TA object."
        )

    # --------------------------------------------------------
    # Remap new-actor class IDs and update property IDs.
    # --------------------------------------------------------

    frames = (
        data.get("network_frames", {})
        .get("frames", [])
    )

    if not frames:
        raise RuntimeError(
            "No network frames found."
        )

    for frame in frames:
        for actor in frame.get("new_actors", []):
            old_id = safe_int(
                actor.get("object_id")
            )

            if old_id in raw_to_normalized:
                actor["object_id"] = (
                    raw_to_normalized[old_id]
                )

        for update in frame.get("updated_actors", []):
            old_id = safe_int(
                update.get("object_id")
            )

            if old_id in raw_to_normalized:
                update["object_id"] = (
                    raw_to_normalized[old_id]
                )

            # A goal StatEvent includes an object-table reference
            # inside the attribute. Other actor IDs inside
            # attributes must not be changed.
            attribute = update.get("attribute")

            if not isinstance(attribute, dict):
                continue

            stat_event = attribute.get("StatEvent")

            if not isinstance(stat_event, dict):
                continue

            stat_id = safe_int(
                stat_event.get("object_id")
            )

            if stat_id in raw_to_normalized:
                stat_event["object_id"] = (
                    raw_to_normalized[stat_id]
                )

    data["objects"] = normalized_objects

    # Write a normalized network file for all the existing scripts.
    with path.open(
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            separators=(",", ":")
        )

    print("Raw object table size:", len(objects))
    print("Normalized object table size:", len(normalized_objects))
    print("Car class:", normalized_objects[304], "(304)")
    print("Ball class:", normalized_objects[238], "(238)")
    print("Ownership link:", normalized_objects[23], "(23)")
    print("ReplicatedActive:", normalized_objects[24], "(24)")
    print("Boost amount:", normalized_objects[263], "(263)")
    print("Goal stat event:", normalized_objects[374], "(374)")
    print("Normalization complete.")


def run_script(filename):
    path = ROOT / filename

    if not path.exists():
        raise FileNotFoundError(
            f"Required script not found: {path}"
        )

    print()
    print("=" * 68)
    print(f"RUNNING {filename}")
    print("=" * 68)

    subprocess.run(
        [sys.executable, str(path)],
        cwd=ROOT,
        check=True,
    )


def run_air_dribble_detector(replay_id):
    """
    Keep manual labels for their original replay only.
    Timestamps from one match must not be reused as labels
    for a different match.
    """

    filename = "detect_air_dribble_sequences.py"
    source_path = ROOT / filename

    if replay_id == REVIEWED_REPLAY_ID:
        run_script(filename)
        return

    original = source_path.read_text(
        encoding="utf-8"
    )

    pattern = re.compile(
        r"(?ms)^MANUAL_REVIEWS\s*=\s*\[.*?^\]"
    )

    modified, count = pattern.subn(
        "MANUAL_REVIEWS = []",
        original,
        count=1,
    )

    if count != 1:
        raise RuntimeError(
            "Could not safely disable the old replay's manual "
            "labels. This replay was parsed, but analysis stopped."
        )

    temporary = (
        ROOT / "_temporary_air_dribble_detector.py"
    )

    try:
        temporary.write_text(
            modified,
            encoding="utf-8"
        )

        run_script(
            temporary.name
        )

    finally:
        if temporary.exists():
            temporary.unlink()


def archive_results(replay_id, source_replay):
    safe_id = re.sub(
        r"[^A-Za-z0-9_-]",
        "_",
        str(replay_id)
    )

    destination = PROCESSED_DIR / safe_id

    destination.mkdir(
        parents=True,
        exist_ok=True
    )

    copied = 0

    for filename in ARCHIVE_FILES:
        source = REPLAYS_DIR / filename

        if source.exists():
            shutil.copy2(
                source,
                destination / filename
            )
            copied += 1

    if METADATA_JSON.exists():
        shutil.copy2(
            METADATA_JSON,
            destination / "replay_metadata.json"
        )

    if NETWORK_JSON.exists():
        shutil.copy2(
            NETWORK_JSON,
            destination / "normalized_network.json"
        )

    demo = ROOT / "rocket_league_ai_demo.html"

    if demo.exists():
        shutil.copy2(
            demo,
            destination / "rocket_league_ai_demo.html"
        )

    (destination / "source_replay_path.txt").write_text(
        str(source_replay),
        encoding="utf-8"
    )

    print()
    print("=" * 68)
    print("REPLAY RESULTS ARCHIVED")
    print("=" * 68)
    print("Replay ID:", replay_id)
    print("Source replay:", source_replay)
    print("Archived CSV files:", copied)
    print("Results folder:", destination)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Parse a Rocket League replay and run the current "
            "mechanic candidate pipeline."
        )
    )

    parser.add_argument(
        "replay",
        nargs="?",
        help="Path to a .replay file"
    )

    args = parser.parse_args()

    if not RRROCKET.exists():
        raise FileNotFoundError(
            f"Replay parser not found: {RRROCKET}"
        )

    REPLAYS_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    source_replay = choose_replay(
        args.replay
    )

    print()
    print("=" * 68)
    print("PROCESSING REPLAY")
    print("=" * 68)
    print("Input:", source_replay)

    # Parse metadata and network data afresh, so previously
    # normalized files are never normalized a second time.
    run_parser(
        [
            str(RRROCKET),
            "-p",
            str(source_replay),
        ],
        METADATA_JSON,
    )

    run_parser(
        [
            str(RRROCKET),
            "-p",
            "-n",
            str(source_replay),
        ],
        NETWORK_JSON,
    )

    with METADATA_JSON.open(
        "r",
        encoding="utf-8"
    ) as f:
        metadata = json.load(f)

    replay_id = find_key(
        metadata,
        "Id"
    ) or source_replay.stem

    print()
    print("Replay ID:", replay_id)
    print("Map:", find_key(metadata, "MapName"))
    print("Date:", find_key(metadata, "Date"))
    print("Team 0 score:", find_key(metadata, "Team0Score"))
    print("Team 1 score:", find_key(metadata, "Team1Score"))

    # This is the fix: resolve every object by name and normalize
    # IDs before any detector reads the network JSON.
    normalize_network_json(
        NETWORK_JSON
    )

    # --------------------------------------------------------
    # Run pipeline in dependency order.
    # --------------------------------------------------------

    run_script("extract_states.py")
    run_script("extract_mechanic_events.py")
    run_script("detect_ball_contacts.py")
    run_script("cluster_ball_contacts.py")
    run_script("detect_flicks.py")
    run_script("detect_double_taps.py")
    run_script("detect_remaining_mechanics.py")

    run_air_dribble_detector(
        str(replay_id)
    )

    run_script("build_master_report.py")
    run_script("build_demo.py")

    archive_results(
        str(replay_id),
        source_replay
    )

    print()
    print("=" * 68)
    print("PIPELINE COMPLETE")
    print("=" * 68)
    print("Dashboard:", ROOT / "rocket_league_ai_demo.html")
    print("Archived results:", PROCESSED_DIR / str(replay_id))


if __name__ == "__main__":
    try:
        main()

    except (
        FileNotFoundError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
        json.JSONDecodeError,
        StopIteration,
    ) as error:
        print()
        print("PROCESSING FAILED:")
        print(error)
        sys.exit(1)