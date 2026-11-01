import csv
import json
from collections import Counter
from pathlib import Path


BASE = Path("data/replays")

INPUTS = {
    "Air Dribble": "air_dribble_sequence_candidates.csv",
    "Flick": "flick_candidates.csv",
    "Ground Dribble": "ground_dribble_candidates.csv",
    "Musty Flick": "musty_flick_candidates.csv",
    "Half Flip": "half_flip_candidates.csv",
    "Flip Reset": "flip_reset_candidates.csv",
    "Double Flip Reset": "double_flip_reset_candidates.csv",
    "Double Tap": "double_tap_candidates.csv",
}

ALL_FILE = BASE / "master_mechanic_all_results.csv"
REVIEW_FILE = BASE / "master_mechanic_candidates.csv"


def read_csv(path):
    if not path.exists():
        print(f"WARNING: Missing file: {path}")
        return []

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        return list(csv.DictReader(f))


def as_int(value):
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (ValueError, TypeError):
        return None


def as_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def first_present(row, keys):
    for key in keys:
        value = row.get(key, "")
        if value is not None and value != "":
            return value
    return ""


def detector_passed(mechanic, row):
    """Was this record selected by its heuristic detector?"""

    status = str(row.get("status", "")).lower()

    if mechanic == "Air Dribble":
        return as_int(row.get("sequence_pass")) == 1

    if mechanic == "Flick":
        return (
            "strong heuristic candidate" in status
            or "review candidate" in status
        )

    if mechanic == "Ground Dribble":
        return as_int(
            row.get("ground_dribble_proxy")
        ) == 1

    if mechanic == "Musty Flick":
        return "musty-like candidate" in status

    if mechanic == "Half Flip":
        return "half-flip-like candidate" in status

    if mechanic == "Flip Reset":
        return as_int(row.get("candidate")) == 1

    if mechanic == "Double Flip Reset":
        return bool(row)

    if mechanic == "Double Tap":
        return (
            "potential double tap sequence" in status
            or "possible sequence" in status
        )

    return False


def standardize(mechanic, filename, row):
    passed = detector_passed(mechanic, row)

    start_frame = first_present(row, [
        "first_frame",
        "first_contact_frame",
        "jump_frame",
        "contact_frame",
        "frame",
        "goal_frame",
        "second_contact_frame",
        "end_frame",
    ])

    end_frame = first_present(row, [
        "second_frame",
        "second_contact_frame",
        "end_frame",
        "frame",
        "contact_frame",
        "goal_frame",
        "jump_frame",
        "first_frame",
        "first_contact_frame",
    ])

    start_time = first_present(row, [
        "first_time",
        "first_contact_time",
        "jump_time",
        "contact_time",
        "time",
        "goal_time",
        "second_contact_time",
        "end_time",
    ])

    end_time = first_present(row, [
        "second_time",
        "second_contact_time",
        "end_time",
        "time",
        "goal_time",
        "contact_time",
        "jump_time",
        "first_time",
        "first_contact_time",
    ])

    car = first_present(row, [
        "car",
        "second_contact_car",
        "first_contact_car",
    ])

    score = first_present(row, [
        "heuristic_score",
    ])

    status = str(
        row.get("status", "")
    ).strip()

    manual_label = str(
        row.get("manual_label", "")
    ).strip()

    manual_note = str(
        row.get("manual_note", "")
    ).strip()

    # Only air-dribble examples have manual visual labels so far.
    if mechanic == "Air Dribble" and manual_label:
        if manual_label == "air_dribble":
            validation = "VISUALLY CONFIRMED"
        else:
            validation = "VISUALLY REJECTED"
    elif passed:
        validation = "UNVALIDATED CANDIDATE"
    else:
        validation = "NOT SHORTLISTED"

    # A detector pass is not always a final shortlist entry.
    # Specifically exclude visually rejected air-dribble examples.
    shortlist_flag = passed

    if (
        mechanic == "Air Dribble"
        and validation == "VISUALLY REJECTED"
    ):
        shortlist_flag = False

    return {
        "mechanic": mechanic,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "start_time": start_time,
        "end_time": end_time,
        "car": car,

        "detector_passed": int(passed),
        "shortlist_flag": int(shortlist_flag),

        "heuristic_score": score,
        "status": status,
        "validation_status": validation,

        "manual_label": manual_label,
        "manual_note": manual_note,

        "source_file": filename,
        "evidence_json": json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
        ),
    }


def numeric_time(row):
    return as_float(row.get("start_time"))


def main():
    all_results = []
    candidates = []

    print("Building final master report...")
    print()

    for mechanic, filename in INPUTS.items():
        source_rows = read_csv(BASE / filename)

        selected = 0
        visually_rejected = 0

        for source_row in source_rows:
            result = standardize(
                mechanic,
                filename,
                source_row,
            )

            all_results.append(result)

            if result["shortlist_flag"] == 1:
                candidates.append(result)
                selected += 1

            if result["detector_passed"] == 1 and result["validation_status"] == "VISUALLY REJECTED":
                visually_rejected += 1

        print(
            f"  {mechanic:20} "
            f"rows={len(source_rows):4} "
            f"shortlisted={selected:4} "
            f"visually_rejected={visually_rejected:3}"
        )

    fields = [
        "mechanic",
        "start_frame",
        "end_frame",
        "start_time",
        "end_time",
        "car",
        "detector_passed",
        "shortlist_flag",
        "heuristic_score",
        "status",
        "validation_status",
        "manual_label",
        "manual_note",
        "source_file",
        "evidence_json",
    ]

    def write_csv(path, rows):
        with path.open(
            "w",
            encoding="utf-8",
            newline=""
        ) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=fields,
            )
            writer.writeheader()
            writer.writerows(rows)

    # Full results are chronological.
    all_results.sort(
        key=lambda row: (
            numeric_time(row) is None,
            numeric_time(row)
            if numeric_time(row) is not None
            else 0.0,
            row["mechanic"],
        )
    )

    # Keep candidates grouped by mechanic. Scores from different
    # detectors aren't calibrated and shouldn't be compared.
    candidates.sort(
        key=lambda row: (
            row["mechanic"],
            numeric_time(row) is None,
            numeric_time(row)
            if numeric_time(row) is not None
            else 0.0,
        )
    )

    write_csv(ALL_FILE, all_results)
    write_csv(REVIEW_FILE, candidates)

    candidate_counts = Counter(
        row["mechanic"]
        for row in candidates
    )

    air_rows = [
        row for row in all_results
        if row["mechanic"] == "Air Dribble"
        and row["detector_passed"] == 1
    ]

    confirmed = sum(
        row["validation_status"] == "VISUALLY CONFIRMED"
        for row in air_rows
    )

    rejected = sum(
        row["validation_status"] == "VISUALLY REJECTED"
        for row in air_rows
    )

    unvalidated = sum(
        row["validation_status"] == "UNVALIDATED CANDIDATE"
        for row in air_rows
    )

    print()
    print("=" * 68)
    print("FINAL MASTER REPORT")
    print("=" * 68)

    print("All detector records:", len(all_results))
    print("Candidate shortlist records:", len(candidates))

    print()
    print("Shortlist by mechanic:")

    for mechanic in INPUTS:
        print(
            f"  {mechanic:20} "
            f"{candidate_counts[mechanic]}"
        )

    print()
    print("Air-dribble sequences that passed the detector:")
    print("  Visually confirmed:", confirmed)
    print("  Visually rejected:", rejected)
    print("  Still unvalidated:", unvalidated)

    print()
    print("Files created:")
    print(" ", ALL_FILE)
    print(" ", REVIEW_FILE)

    print()
    print(
        "All other mechanics remain unvalidated until "
        "they are checked against the replay."
    )
    print(
        "Heuristic scores are ranking aids, not probabilities."
    )


if __name__ == "__main__":
    main()
