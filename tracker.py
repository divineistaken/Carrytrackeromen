#!/usr/bin/env python3
"""Fetch the territorial.io team log, keep OMEN wins and count carries.

A "carry" is the player at the front of the payout list (most gold earned)
in a match won by the OMEN clan.
"""

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LOG_URL = "https://territorial.io/log/team"
CLAN = "OMEN"
MAX_WINS = 1000

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
    winners = parse_winners(entry.get("Clan Winners", ""))
    return {
        "time": entry.get("Time", ""),
        "map": entry.get("Map", ""),
        "players": int(entry["Player Count"]) if entry.get("Player Count", "").isdigit() else None,
        "gain": entry.get("Gain", ""),
        "carry": payout[0][0],
        "carry_gold": payout[0][1],
        "payout": payout,
        "clan_winners": winners,
    }


def load_existing(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data.json")
    data = load_existing(out)
    wins = {f'{w["time"]}|{w["map"]}': w for w in data.get("wins", [])}

    try:
        text = fetch_log()
    except Exception as exc:
        print(f"fetch failed: {exc}", file=sys.stderr)
        return 1

    added = 0
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

    if added == 0 and out.exists():
        print(f"no new {CLAN} wins ({len(wins)} tracked)")
        return 0

    ordered = sorted(wins.values(), key=lambda w: w["time"], reverse=True)[:MAX_WINS]
    carries = {}
    for win in ordered:
        carries[win["carry"]] = carries.get(win["carry"], 0) + 1

    result = {
        "clan": CLAN,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "total_wins": len(ordered),
        "carries": dict(sorted(carries.items(), key=lambda kv: (-kv[1], kv[0].lower()))),
        "wins": ordered,
    }
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(f"parsed {len(ordered)} {CLAN} wins, {added} new")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
