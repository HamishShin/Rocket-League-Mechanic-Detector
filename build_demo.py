import csv
import json
import webbrowser
from collections import Counter
from pathlib import Path
from html import escape


BASE = Path("data/replays")

ALL_FILE = BASE / "master_mechanic_all_results.csv"
CANDIDATE_FILE = BASE / "master_mechanic_candidates.csv"
METADATA_FILE = BASE / "new_test.json"

OUTPUT_FILE = Path("rocket_league_ai_demo.html")


# ============================================================
# LOAD CSV FILES
# ============================================================

def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(
            f"Required file is missing: {path}\n"
            "Run python .\\build_master_report.py first."
        )

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        return list(csv.DictReader(f))


# ============================================================
# LOAD REPLAY METADATA
# ============================================================

def find_key(data, wanted):
    if isinstance(data, dict):
        # Prefer the direct key at this level.
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


def extract_players(data):
    raw = find_key(data, "PlayerStats")

    if not isinstance(raw, list):
        return []

    players = []

    for item in raw:
        if not isinstance(item, dict):
            continue

        lowered = {
            str(key).lower(): value
            for key, value in item.items()
        }

        name = next(
            (
                lowered[key]
                for key in [
                    "name",
                    "playername",
                    "player",
                ]
                if lowered.get(key) not in (None, "")
                and isinstance(lowered.get(key), str)
            ),
            None,
        )

        team = next(
            (
                lowered[key]
                for key in [
                    "team",
                    "teamnumber",
                    "teamindex",
                ]
                if lowered.get(key) is not None
            ),
            None,
        )

        if name:
            players.append({
                "name": str(name),
                "team": str(team) if team is not None else "",
            })

    return players


def load_metadata():
    if not METADATA_FILE.exists():
        return {}

    with METADATA_FILE.open(
        "r",
        encoding="utf-8"
    ) as f:
        data = json.load(f)

    return {
        "replay_id": find_key(data, "Id") or "",
        "map_name": find_key(data, "MapName") or "",
        "date": find_key(data, "Date") or "",
        "match_type": find_key(data, "MatchType") or "",
        "team_size": find_key(data, "TeamSize"),
        "team0_score": find_key(data, "Team0Score"),
        "team1_score": find_key(data, "Team1Score"),
        "frames": find_key(data, "NumFrames"),
        "players": extract_players(data),
    }


# ============================================================
# SAFE DATA EMBEDDING
# ============================================================

def js_json(data):
    return (
        json.dumps(data, ensure_ascii=False)
        .replace("</", "<\\/")
    )


# ============================================================
# BUILD HTML
# ============================================================

def main():
    all_rows = read_csv(ALL_FILE)
    candidates = read_csv(CANDIDATE_FILE)
    metadata = load_metadata()

    mechanics = sorted({
        row.get("mechanic", "")
        for row in all_rows
        if row.get("mechanic")
    })

    validation_counts = Counter(
        row.get("validation_status", "Unknown")
        for row in candidates
    )

    confirmed_air_dribbles = sum(
        row.get("mechanic") == "Air Dribble"
        and row.get("validation_status") == "VISUALLY CONFIRMED"
        for row in candidates
    )

    metadata_for_page = {
        "replay": metadata,
        "all_count": len(all_rows),
        "candidate_count": len(candidates),
        "mechanics": mechanics,
        "validation_counts": dict(validation_counts),
        "confirmed_air_dribbles": confirmed_air_dribbles,
    }

    html = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rocket League Mechanics Lab</title>
<style>
:root {
    color-scheme: dark;
    --bg: #0b1020;
    --panel: #141c30;
    --panel2: #1b2740;
    --line: #2b3854;
    --text: #edf3ff;
    --muted: #9cacca;
    --accent: #67d5ff;
    --green: #72e0ae;
    --amber: #ffd27a;
    --red: #ff9d9d;
}
* { box-sizing: border-box; }
body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: Segoe UI, Arial, sans-serif;
    line-height: 1.45;
}
header {
    padding: 32px clamp(16px, 4vw, 56px);
    border-bottom: 1px solid var(--line);
    background: linear-gradient(120deg, #152848, #0b1020 75%);
}
.eyebrow {
    color: var(--accent);
    text-transform: uppercase;
    letter-spacing: .13em;
    font-size: 12px;
    font-weight: 700;
}
h1 {
    margin: 8px 0;
    font-size: clamp(28px, 4vw, 44px);
}
.subtitle { color: var(--muted); max-width: 850px; }
main {
    max-width: 1500px;
    margin: auto;
    padding: 24px clamp(12px, 3vw, 36px) 48px;
}
.panel {
    border: 1px solid var(--line);
    border-radius: 14px;
    background: var(--panel);
    padding: 18px;
    margin-bottom: 18px;
}
h2 { margin: 0 0 12px; font-size: 19px; }
.metrics {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
    margin-bottom: 18px;
}
.metric {
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 17px;
    background: var(--panel);
}
.metric .label { color: var(--muted); font-size: 13px; }
.metric .number { font-size: 30px; font-weight: 750; margin-top: 5px; }
.metric .hint { font-size: 12px; color: var(--muted); margin-top: 4px; }
.meta-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
}
.meta-item {
    padding: 10px;
    background: var(--panel2);
    border-radius: 8px;
    overflow-wrap: anywhere;
}
.meta-label { color: var(--muted); font-size: 12px; }
.meta-value { font-weight: 600; margin-top: 3px; }
.warning {
    border-left: 4px solid var(--amber);
    background: #30281a;
    padding: 14px 16px;
    border-radius: 8px;
    margin: 18px 0;
}
.controls {
    display: grid;
    grid-template-columns: 1.2fr 1fr 1.5fr 1fr;
    gap: 10px;
}
label { display: block; color: var(--muted); font-size: 12px; margin-bottom: 5px; }
select, input, button {
    width: 100%;
    padding: 11px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: var(--panel2);
    color: var(--text);
    font: inherit;
}
button { cursor: pointer; }
button:hover { border-color: var(--accent); }
.table-wrap {
    overflow: auto;
    max-height: 650px;
    border: 1px solid var(--line);
    border-radius: 10px;
}
table {
    width: 100%;
    border-collapse: collapse;
    min-width: 900px;
}
th, td {
    text-align: left;
    padding: 11px 12px;
    border-bottom: 1px solid var(--line);
    vertical-align: top;
}
th {
    background: #1a2741;
    position: sticky;
    top: 0;
    z-index: 1;
    font-size: 12px;
    color: var(--muted);
}
td { font-size: 13px; }
tr:hover td { background: #18233a; }
.pill {
    display: inline-block;
    border: 1px solid var(--line);
    border-radius: 999px;
    padding: 3px 8px;
    font-size: 11px;
    white-space: nowrap;
}
.confirmed { color: var(--green); border-color: #367c60; }
.rejected { color: var(--red); border-color: #854848; }
.unvalidated { color: var(--amber); border-color: #8f7138; }
.muted { color: var(--muted); }
details summary { cursor: pointer; color: var(--accent); }
pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
    max-width: 650px;
    max-height: 340px;
    overflow: auto;
    color: var(--muted);
}
#result-count { color: var(--muted); font-size: 13px; margin: 12px 0; }
footer { color: var(--muted); font-size: 12px; padding: 0 4px; }
@media (max-width: 850px) {
    .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .controls { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .meta-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 480px) {
    .metrics, .controls, .meta-grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<header>
    <div class="eyebrow">Replay analysis prototype</div>
    <h1>Rocket League Mechanics Lab</h1>
    <div class="subtitle">
        Browse mechanic candidates, jump to their replay timestamps,
        and inspect the evidence used by each heuristic detector.
    </div>
</header>

<main>
    <section class="metrics" id="metrics"></section>

    <section class="panel">
        <h2>Replay information</h2>
        <div class="meta-grid" id="metadata"></div>
        <div id="players" style="margin-top:12px"></div>
    </section>

    <div class="warning">
        <strong>Validation matters.</strong>
        Detector scores are heuristic rankings, not probabilities.
        Only examples explicitly marked as visually confirmed have been
        checked against the replay. The other mechanic detectors remain
        experimental and their candidates are not confirmed detections.
    </div>

    <section class="panel">
        <h2>Candidate explorer</h2>
        <div class="controls">
            <div>
                <label for="dataset">Dataset</label>
                <select id="dataset">
                    <option value="candidates">Shortlisted candidates</option>
                    <option value="all">All detector results</option>
                </select>
            </div>
            <div>
                <label for="mechanic">Mechanic</label>
                <select id="mechanic"><option value="">All mechanics</option></select>
            </div>
            <div>
                <label for="validation">Validation status</label>
                <select id="validation">
                    <option value="">All statuses</option>
                </select>
            </div>
            <div>
                <label for="search">Search</label>
                <input id="search" placeholder="Car, status, time...">
            </div>
        </div>

        <div id="result-count"></div>
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th>Mechanic</th>
                        <th>Time window</th>
                        <th>Car</th>
                        <th>Score</th>
                        <th>Status</th>
                        <th>Validation</th>
                        <th>Evidence</th>
                    </tr>
                </thead>
                <tbody id="results"></tbody>
            </table>
        </div>
    </section>

    <footer>
        Generated locally from this project's CSV outputs.
        Review status is kept separate from heuristic detection status.
    </footer>
</main>

<script>
const ALL_ROWS = __ALL_ROWS__;
const CANDIDATE_ROWS = __CANDIDATE_ROWS__;
const META = __META__;

const $ = (id) => document.getElementById(id);

function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;"
    })[char]);
}

function pretty(value) {
    if (value === null || value === undefined || value === "") {
        return "—";
    }
    return String(value);
}

function badgeClass(status) {
    const s = String(status || "").toLowerCase();

    if (s.includes("visually confirmed")) return "confirmed";
    if (s.includes("visually rejected")) return "rejected";

    return "unvalidated";
}

function renderMetrics() {
    const count = META.candidate_count;
    const confirmed = META.confirmed_air_dribbles;

    $("metrics").innerHTML = [
        {
            label: "Replay frames",
            value: pretty(META.replay.frames),
            hint: "Parsed network timeline"
        },
        {
            label: "Detector records",
            value: META.all_count,
            hint: "Across the eight mechanic pipelines"
        },
        {
            label: "Shortlisted records",
            value: count,
            hint: "Candidates, not confirmed tricks"
        },
        {
            label: "Visually confirmed air dribbles",
            value: confirmed,
            hint: "From the examples manually reviewed so far"
        }
    ].map(item => `
        <div class="metric">
            <div class="label">${esc(item.label)}</div>
            <div class="number">${esc(item.value)}</div>
            <div class="hint">${esc(item.hint)}</div>
        </div>
    `).join("");
}

function renderMetadata() {
    const r = META.replay || {};

    const items = [
        ["Map internal name", r.map_name],
        ["Match type", r.match_type],
        ["Team size", r.team_size],
        ["Team 0 score", r.team0_score],
        ["Team 1 score", r.team1_score],
        ["Replay date", r.date],
        ["Replay ID", r.replay_id]
    ];

    $("metadata").innerHTML = items.map(([label, value]) => `
        <div class="meta-item">
            <div class="meta-label">${esc(label)}</div>
            <div class="meta-value">${esc(pretty(value))}</div>
        </div>
    `).join("");

    const players = r.players || [];

    if (players.length) {
        $("players").innerHTML = `
            <div class="meta-label">Player names extracted from metadata</div>
            <div>${players.map(p =>
                `<span class="pill">${esc(p.name)}${p.team ? " · team " + esc(p.team) : ""}</span>`
            ).join(" ")}</div>
        `;
    } else {
        $("players").innerHTML = `
            <div class="muted">
                Player names were not extracted automatically from this metadata.
                Confirm the names in the replay before presenting them.
            </div>
        `;
    }
}

function currentRows() {
    return $("dataset").value === "all" ? ALL_ROWS : CANDIDATE_ROWS;
}

function populateFilters() {
    const mechanics = [...new Set(ALL_ROWS.map(r => r.mechanic).filter(Boolean))].sort();
    const statuses = [...new Set(ALL_ROWS.map(r => r.validation_status).filter(Boolean))].sort();

    $("mechanic").innerHTML =
        `<option value="">All mechanics</option>` +
        mechanics.map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join("");

    $("validation").innerHTML =
        `<option value="">All statuses</option>` +
        statuses.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
}

function renderRows() {
    const chosenMechanic = $("mechanic").value;
    const chosenValidation = $("validation").value;
    const search = $("search").value.trim().toLowerCase();

    let rows = currentRows().filter(row => {
        if (chosenMechanic && row.mechanic !== chosenMechanic) return false;
        if (chosenValidation && row.validation_status !== chosenValidation) return false;

        const searchable = [
            row.mechanic,
            row.start_time,
            row.end_time,
            row.car,
            row.status,
            row.validation_status,
            row.manual_note,
            row.source_file
        ].join(" ").toLowerCase();

        return !search || searchable.includes(search);
    });

    // Keep the list chronological for easy replay navigation.
    rows.sort((a, b) => {
        const at = Number(a.start_time);
        const bt = Number(b.start_time);

        const aValid = Number.isFinite(at);
        const bValid = Number.isFinite(bt);

        if (aValid && bValid) return at - bt;
        if (aValid) return -1;
        if (bValid) return 1;

        return String(a.mechanic).localeCompare(String(b.mechanic));
    });

    $("result-count").textContent =
        `Showing ${rows.length} of ${currentRows().length} records`;

    $("results").innerHTML = rows.map(row => {
        let evidence = row.evidence_json || "{}";

        try {
            evidence = JSON.stringify(JSON.parse(evidence), null, 2);
        } catch (_) {}

        const windowText =
            row.start_time || row.end_time
                ? `${pretty(row.start_time)}${row.end_time && row.end_time !== row.start_time ? " – " + pretty(row.end_time) : ""} s`
                : "—";

        return `
            <tr>
                <td><strong>${esc(row.mechanic)}</strong></td>
                <td>
                    ${esc(windowText)}
                    <div class="muted">Frames ${esc(pretty(row.start_frame))}${row.end_frame && row.end_frame !== row.start_frame ? " – " + esc(row.end_frame) : ""}</div>
                </td>
                <td>${esc(pretty(row.car))}</td>
                <td>${esc(pretty(row.heuristic_score))}</td>
                <td>${esc(pretty(row.status))}</td>
                <td>
                    <span class="pill ${badgeClass(row.validation_status)}">
                        ${esc(pretty(row.validation_status))}
                    </span>
                </td>
                <td>
                    <details>
                        <summary>Inspect</summary>
                        <div class="muted">${esc(pretty(row.manual_note))}</div>
                        <pre>${esc(evidence)}</pre>
                    </details>
                </td>
            </tr>
        `;
    }).join("");

    if (!rows.length) {
        $("results").innerHTML = `
            <tr><td colspan="7" class="muted">No records match these filters.</td></tr>
        `;
    }
}

renderMetrics();
renderMetadata();
populateFilters();
renderRows();

["dataset", "mechanic", "validation", "search"].forEach(id => {
    $(id).addEventListener("input", renderRows);
    $(id).addEventListener("change", renderRows);
});
</script>
</body>
</html>
"""

    html = (
        html
        .replace("__ALL_ROWS__", js_json(all_rows))
        .replace("__CANDIDATE_ROWS__", js_json(candidates))
        .replace("__META__", js_json(metadata_for_page))
    )

    OUTPUT_FILE.write_text(
        html,
        encoding="utf-8"
    )

    print()
    print("=" * 60)
    print("ROCKET LEAGUE AI DEMO BUILT")
    print("=" * 60)
    print("Replay:", metadata.get("replay_id", "Unknown"))
    print("Map:", metadata.get("map_name", "Unknown"))
    print("All detector records:", len(all_rows))
    print("Shortlisted records:", len(candidates))
    print("Visually confirmed air dribbles:", confirmed_air_dribbles)
    print()
    print("Created:", OUTPUT_FILE.resolve())

    webbrowser.open(
        OUTPUT_FILE.resolve().as_uri()
    )


if __name__ == "__main__":
    main()