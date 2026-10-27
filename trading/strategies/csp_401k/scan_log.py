"""
Logging for all trading scans. Every check gets logged with full context
so the account owner can audit exactly what happened and why.
"""
import json
import os
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def get_log_path():
    """One log file per day."""
    return os.path.join(LOG_DIR, f"{datetime.now().strftime('%Y-%m-%d')}.jsonl")


def log_scan(scan_type, data):
    """
    Append a scan entry to today's log.

    scan_type: "open", "primary_window", "midday", "close"
    data: dict with full scan results
    """
    entry = {
        "timestamp": datetime.now().isoformat(),
        "scan_type": scan_type,
        **data,
    }
    with open(get_log_path(), "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def log_alert(message, sent_slack=False):
    """Log when an alert was generated and whether Slack was sent."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "type": "ALERT",
        "message": message,
        "sent_slack": sent_slack,
    }
    with open(get_log_path(), "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def log_no_action(reason, source="system"):
    """Log when we checked and decided no action needed.

    source: "system" for the terse machine reasons daily_scan/monitor emit,
    "agent" for the morning agent's rich human reason. The recap
    (daily_summary.py) prefers the agent's over any system reason logged later
    by an intraday scan, so the morning message always shows the real hunt."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "type": "NO_ACTION",
        "reason": reason,
        "source": source,
    }
    with open(get_log_path(), "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def print_todays_log():
    """Print all of today's log entries."""
    path = get_log_path()
    if not os.path.exists(path):
        print("No log entries for today.")
        return

    with open(path) as f:
        entries = [json.loads(line) for line in f if line.strip()]

    print(f"=== SCAN LOG {datetime.now().strftime('%Y-%m-%d')} ({len(entries)} entries) ===\n")
    for e in entries:
        ts = e["timestamp"][11:19]
        etype = e.get("type", e.get("scan_type", "?"))

        if etype == "ALERT":
            print(f"  [{ts}] *** ALERT: {e['message']} (Slack: {e['sent_slack']})")
        elif etype == "NO_ACTION":
            print(f"  [{ts}]     NO ACTION: {e['reason']}")
        else:
            # Scan entry — show key details
            spy = e.get("spy_change", "?")
            qqq = e.get("qqq_change", "?")
            cash = e.get("cash_available", "?")
            position_pnl = e.get("position_pnl", "?")
            dca_candidates = e.get("dca_candidates", [])
            premium_signal = e.get("premium_signal", False)

            details = f"SPY:{spy:+.1f}% QQQ:{qqq:+.1f}%" if isinstance(spy, (int, float)) else ""
            if position_pnl and isinstance(position_pnl, (int, float)):
                details += f" | Put P&L:${position_pnl:+.0f}"
            if dca_candidates:
                details += f" | red: {','.join(dca_candidates)}"
            if premium_signal:
                details += " | PREMIUM OPPORTUNITY"

            print(f"  [{ts}] {etype:>16}: {details}")


if __name__ == "__main__":
    print_todays_log()
