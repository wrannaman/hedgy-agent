"""Reject empty/partial agent turns and outputs left by earlier attempts."""

import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


def verify_run(started, here=HERE):
    day = datetime.fromtimestamp(started).date().isoformat()
    paths = [
        (here / "state/last_scan.json", "timestamp"),
        (here / "state/last_screen.json", "timestamp"),
        (here.parents[1] / "state/agent_decision.json", "date"),
    ]
    for path, field in paths:
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                raise ValueError("expected a JSON object")
            if path.stat().st_mtime < started:
                raise ValueError("not written during this attempt")
            if field == "timestamp":
                if datetime.fromisoformat(data[field]).timestamp() < started:
                    raise ValueError("stale data timestamp")
            elif data[field] != day:
                raise ValueError("decision is not dated today")
            if field == "date" and (
                not isinstance(data.get("new_trades"), list)
                or not isinstance(data.get("hunt_reason"), str)
                or not data["hunt_reason"].strip()
            ):
                raise ValueError("decision requires new_trades and hunt_reason")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"{path.name}: {exc}") from exc

    log = here / "logs" / f"{day}.jsonl"
    try:
        for line in log.read_text().splitlines():
            entry = json.loads(line)
            if not isinstance(entry, dict):
                raise ValueError("expected a JSON log object")
            if entry.get("scan_type") == "daily_scan" and (
                datetime.fromisoformat(entry["timestamp"]).timestamp() >= started
            ):
                return
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{log.name}: {exc}") from exc
    raise ValueError(f"{log.name}: no daily_scan from this attempt")


if __name__ == "__main__":
    try:
        verify_run(float(sys.argv[1]))
    except ValueError as exc:
        print(f"INCOMPLETE RUN: {exc}", file=sys.stderr)
        sys.exit(1)
    print("agent outputs: fresh scan, screen, and decision verified")
