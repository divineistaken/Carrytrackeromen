#!/usr/bin/env python3
"""Track territorial.io team-log wins for the OMEN clan and count carries.

A "carry" is the player at the front of the payout list (the one who earned
the most gold) in a match won by OMEN.

Usage: tracker.py [state.json] [slot_dir]
  state.json  full history, kept across workflow runs
  slot_dir    immutable 30s snapshot files served to the website
"""

import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LOG_URL = "https://territorial.io/log/team"
CLAN = "OMEN"
MAX_WINS = 2000
SLOT_MS = 30_000
RECENT_WINS = 25

FIELD_RE = re.compile(r"^([A-Za-z. ]+?):\s+(.*)$")
PAYOUT_RE = re.compile(r"([^\s,]+)\s+([0-9]+(?:\.[0-9]+)?)")


def fetch_log():
    req = urllib.request.Request(
        LOG_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "text/html,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", "replace")


def parse_entries(text):
    entries, current = [], None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("Time:"):
            if current:
                entries.append(current)
            current = {"Time": line.split(":", 1)[1].strip()}
            continue
        if current is None:
            continue
        m = FIELD_RE.match(line)
        if m:
            current[m.group(1).strip()] = m.group(2).strip()
    if current:
        entries.append(current)
    return entries


def parse_payout(value):
    payout = []
    for name, gold in PAYOUT_RE.findall(value or ""):
        try:
            payout.append([name, float(gold)])
        except ValueError:
            continue
    return payout


def parse_winners(value):
    return [w.strip() for w in (value or "").split(",") if w.strip()]


def to_record(entry):
    payout = parse_payout(entry.get("Payout", ""))
    if not payout:
        return None
    return {
        "time": entry.get("Time", ""),
        "map": entry.get("Map", ""),
        "players": int(entry["Player Count"]) if entry.get("Player Count", "").isdigit() else None,
        "gain": entry.get("Gain", ""),
        "carry": payout[0][0],
        "carry_gold": payout[0][1],
        "payout": payout,
        "clan_winners": parse_winners(entry.get("Clan Winners", "")),
    }


def load_json(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def build_summary(state, checked):
    wins = state.get("wins", [])
    carries = {}
    for win in wins:
        carries[win["carry"]] = carries.get(win["carry"], 0) + 1
    return {
        "clan": CLAN,
        "checked": checked,
        "updated": state.get("updated", checked),
        "total_wins": len(wins),
        "carries": dict(sorted(carries.items(), key=lambda kv: (-kv[1], kv[0].lower()))),
        "wins": wins[:RECENT_WINS],
    }


def write_if_changed(path, payload):
    text = json.dumps(payload, indent=2) + "\n"
    if path.exists() and path.read_text() == text:
        return False
    path.write_text(text)
    return True


def main():
    state_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("state.json")
    slot_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("d")

    state = load_json(state_path)
    wins = {f'{w["time"]}|{w["map"]}': w for w in state.get("wins", [])}

    added = 0
    try:
        text = fetch_log()
    except Exception as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return 1

    for entry in parse_entries(text):
        if entry.get("Winning Clan", "").strip().upper() != f"[{CLAN}]":
            continue
        record = to_record(entry)
        if not record:
            continue
        key = f'{record["time"]}|{record["map"]}'
        if key not in wins:
            wins[key] = record
            added += 1

    ordered = sorted(wins.values(), key=lambda w: w["time"], reverse=True)[:MAX_WINS]
    changed = False
    if added:
        state = {"clan": CLAN, "updated": utc_now(), "wins": ordered}
        changed = write_if_changed(state_path, state)
    elif not state:
        state = {"clan": CLAN, "updated": utc_now(), "wins": ordered}
        changed = write_if_changed(state_path, state)

    slot = int(time.time() * 1000 // SLOT_MS * SLOT_MS)
    slot_dir.mkdir(parents=True, exist_ok=True)
    slot_path = slot_dir / f"{slot}.json"
    if not slot_path.exists():
        summary = build_summary(state, utc_now())
        slot_path.write_text(json.dumps(summary, indent=2) + "\n")
        changed = True

    print(f"new={added} total={len(ordered)} slot={slot_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
