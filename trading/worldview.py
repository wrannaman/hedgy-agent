"""
worldview.py — parser + staleness reviewer for WORLDVIEW.md.

WORLDVIEW.md is human-owned prose (the judgment half of the mandate). This module
does NOT write to it. It reads it, extracts each thesis with its Review-by date, and
answers the one question a review-by date is worthless without something asking it:
"is any belief past its review date and quietly still tilting our trades?"

A thesis is a `### T<n>. <name>` block carrying labeled fields (Claim / Source /
Conviction / Falsifier / Review by / Hook). This surfaces:
  - active theses (and enforces the max-6 cap — a 7th is a bug to flag)
  - STALE theses: Review-by date is in the past → must be re-affirmed (bump the date)
    or archived. Until a human does one of those, the morning recap nags about it.

The nag is the whole point: a stale thesis is worse than no thesis, because it keeps
tilting the hunt on a belief nobody has re-checked. Read-only; writes a review summary
to state/worldview_review.json for the morning engine to surface.
"""
import re, sys, json
from collections import Counter
from datetime import date, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
DOC = _ROOT / "WORLDVIEW.md"
STATE = _ROOT / "state"

MAX_ACTIVE = 6      # mirrors WORLDVIEW.md "Max 6 active theses" — kept in sync by hand.
PER_SOURCE_CAP = 2  # no single thinker (Damodaran, Prof G, ...) may own more than this
                    # many active theses — the "don't over-index on one voice" rule.

_THESIS_RE = re.compile(r"^###\s+(T\d+)\.\s+(.+)$", re.M)
_FIELD_RE = re.compile(r"^\s*-\s*\*\*(?P<key>[^:*]+):\*\*\s*(?P<val>.+?)\s*$", re.M)
_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _active_section(text):
    """Only theses under '## Active theses' count — the Archive is history, not live.
    HTML comments are stripped first so the `<!-- Template -->` block never parses as a
    real thesis."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    start = text.find("## Active theses")
    if start == -1:
        return ""
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else len(text)]


def parse(text=None):
    """Return the list of active theses as dicts (id, name, fields, review_by)."""
    if text is None:
        text = DOC.read_text() if DOC.exists() else ""
    section = _active_section(text)
    theses = []
    matches = list(_THESIS_RE.finditer(section))
    for i, m in enumerate(matches):
        body = section[m.end():(matches[i + 1].start() if i + 1 < len(matches) else len(section))]
        fields = {k.strip().lower(): v.strip() for k, v in _FIELD_RE.findall(body)}
        review_raw = fields.get("review by") or fields.get("review-by") or ""
        dm = _DATE_RE.search(review_raw)
        source = fields.get("source") or ""
        theses.append({
            "id": m.group(1),
            "name": m.group(2).strip(),
            "conviction": fields.get("conviction"),
            "hook": fields.get("hook"),
            "review_by": dm.group(1) if dm else None,
            "source": source,
            "source_key": _source_key(source),
        })
    return theses


def _source_key(source):
    """Normalize a Source line to the attributable person/outlet: the text before the
    first comma, lowercased. 'Aswath Damodaran, Musings on Markets, 2026-03' -> 'aswath
    damodaran'. Used to enforce the per-source cap so one voice can't dominate."""
    return source.split(",")[0].strip().lower() if source else ""


def review(today=None, text=None):
    today = today or date.today()
    theses = parse(text)
    stale, undated = [], []
    for t in theses:
        if not t["review_by"]:
            undated.append(t)
            continue
        try:
            rb = datetime.strptime(t["review_by"], "%Y-%m-%d").date()
        except ValueError:
            undated.append(t)
            continue
        if rb < today:
            t["days_overdue"] = (today - rb).days
            stale.append(t)
    # Per-source cap: no single thinker may own more than PER_SOURCE_CAP active theses.
    src_counts = Counter(t["source_key"] for t in theses if t["source_key"])
    over_source = [{"source": k, "count": n} for k, n in src_counts.items()
                   if n > PER_SOURCE_CAP]
    return {
        "date": str(today),
        "active_count": len(theses),
        "max_active": MAX_ACTIVE,
        "over_cap": len(theses) > MAX_ACTIVE,
        "per_source_cap": PER_SOURCE_CAP,
        "over_source": over_source,
        "stale": stale,
        "undated": undated,
        "active": theses,
    }


def render(r):
    """One-line-per-issue review, or a single clean line when nothing needs attention."""
    if r["active_count"] == 0:
        return "WORLDVIEW: no active theses."
    lines = [f"WORLDVIEW: {r['active_count']}/{r['max_active']} active theses."]
    if r["over_cap"]:
        lines.append(f"  ⚠ OVER CAP — {r['active_count']} > {r['max_active']}; kill one.")
    for o in r["over_source"]:
        lines.append(f"  ⚠ OVER-INDEXED on {o['source']} — {o['count']} active theses "
                     f"(cap {r['per_source_cap']}); one voice is dominating, prune it.")
    for t in r["stale"]:
        lines.append(f"  ⚠ STALE: {t['id']} \"{t['name']}\" — review-by {t['review_by']} "
                     f"({t['days_overdue']}d overdue). Re-affirm (bump the date) or archive it.")
    for t in r["undated"]:
        lines.append(f"  ⚠ NO REVIEW DATE: {t['id']} \"{t['name']}\" — every thesis needs one.")
    if not r["stale"] and not r["undated"] and not r["over_cap"] and not r["over_source"]:
        lines.append("  all current — none past its review-by date, no voice over-indexed.")
    return "\n".join(lines)


def run():
    STATE.mkdir(exist_ok=True)
    r = review()
    (STATE / "worldview_review.json").write_text(json.dumps(r, indent=2))
    print(render(r))
    return r


if __name__ == "__main__":
    run()
