import csv
import math


INPUT_FILE = "data/replays/ball_contact_candidates.csv"
OUTPUT_FILE = "data/replays/ball_contacts.csv"


# ============================================================
# SETTINGS
# ============================================================

# Two candidates from the same car closer than this in time
# are treated as part of the same contact.
CLUSTER_GAP = 0.15


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


# ============================================================
# LOAD
# ============================================================

print("Loading contact candidates...")

with open(
    INPUT_FILE,
    "r",
    encoding="utf-8",
    newline=""
) as f:

    reader = csv.DictReader(f)

    fields = reader.fieldnames

    if not fields:
        raise RuntimeError(
            "ball_contact_candidates.csv has no header."
        )

    rows = list(reader)


print(
    "Candidates loaded:",
    len(rows)
)


# ============================================================
# SORT BY CAR + TIME
# ============================================================

rows.sort(
    key=lambda row: (
        row.get("car", ""),
        to_float(row.get("time_before"))
        or 0.0
    )
)


# ============================================================
# BUILD CLUSTERS
# ============================================================

clusters = []

current = []

for row in rows:

    car = row.get("car", "")

    time = to_float(
        row.get("time_before")
    )

    if time is None:
        continue

    if not current:

        current = [row]
        continue

    previous = current[-1]

    previous_time = to_float(
        previous.get("time_before")
    )

    previous_car = previous.get(
        "car",
        ""
    )

    gap = (
        time - previous_time
        if previous_time is not None
        else 999.0
    )

    same_cluster = (
        car == previous_car
        and gap <= CLUSTER_GAP
    )

    if same_cluster:

        current.append(row)

    else:

        clusters.append(
            current
        )

        current = [row]


if current:

    clusters.append(
        current
    )


# ============================================================
# PICK BEST CANDIDATE PER CLUSTER
# ============================================================

contacts = []


for cluster_id, cluster in enumerate(
    clusters,
    start=1
):

    # Stronger score:
    # large ball velocity change
    # + small car-ball distance
    #
    # This does NOT prove contact. It simply picks the strongest
    # candidate inside a cluster.

    def score(row):

        ball_dv = (
            to_float(
                row.get("ball_dv")
            )
            or 0.0
        )

        distance = (
            to_float(
                row.get("min_distance")
            )
            or 999999.0
        )

        return (
            ball_dv
            /
            max(distance, 1.0)
        )

    best = max(
        cluster,
        key=score
    )

    output = dict(best)

    output[
        "contact_id"
    ] = cluster_id

    output[
        "cluster_size"
    ] = len(cluster)

    output[
        "cluster_start_time"
    ] = cluster[0][
        "time_before"
    ]

    output[
        "cluster_end_time"
    ] = cluster[-1][
        "time_before"
    ]

    contacts.append(
        output
    )


# ============================================================
# SORT CHRONOLOGICALLY
# ============================================================

contacts.sort(
    key=lambda row:
        to_float(
            row.get("time_before")
        )
        or 0.0
)


# ============================================================
# SAVE
# ============================================================

base_fields = [
    "contact_id",
    "cluster_size",
    "cluster_start_time",
    "cluster_end_time",
]


original_fields = [
    field
    for field in fields
    if field not in base_fields
]


output_fields = (
    base_fields
    + original_fields
)


with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8",
    newline=""
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=output_fields
    )

    writer.writeheader()

    writer.writerows(
        contacts
    )


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 70)
print("CLUSTERED BALL CONTACTS")
print("=" * 70)

print(
    "Raw candidates :",
    len(rows)
)

print(
    "Contact clusters:",
    len(contacts)
)

print(
    "Removed duplicate candidates:",
    len(rows) - len(contacts)
)


# ============================================================
# CLUSTER SIZE DISTRIBUTION
# ============================================================

sizes = {}

for contact in contacts:

    size = int(
        contact["cluster_size"]
    )

    sizes[size] = (
        sizes.get(size, 0)
        + 1
    )


print()
print("Cluster sizes:")

for size in sorted(sizes):

    print(
        f"  {size} candidate(s):"
        f" {sizes[size]}"
    )


# ============================================================
# STRONGEST CONTACTS
# ============================================================

print()
print("Strongest clustered contacts:")

scored = []

for contact in contacts:

    ball_dv = (
        to_float(
            contact.get("ball_dv")
        )
        or 0.0
    )

    distance = (
        to_float(
            contact.get("min_distance")
        )
        or 999999.0
    )

    score = (
        ball_dv
        /
        max(distance, 1.0)
    )

    scored.append(
        (
            score,
            contact
        )
    )


scored.sort(
    reverse=True,
    key=lambda item: item[0]
)


for score, contact in scored[:30]:

    print(
        f"time={float(contact['time_before']):8.3f} "
        f"frame={contact['frame_before']:>5s} "
        f"car={contact['car']:6s} "
        f"dist={float(contact['min_distance']):7.2f} "
        f"ball_dv={float(contact['ball_dv']):8.2f} "
        f"cluster={contact['cluster_size']}"
    )


print()
print("Saved:")
print(OUTPUT_FILE)