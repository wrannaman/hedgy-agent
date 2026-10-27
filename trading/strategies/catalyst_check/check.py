#!/usr/bin/env python3
"""Check recent public headlines for candidate-specific bad news."""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
MORNING_DECISION = REPO_ROOT / "strategies" / "morning_decision" / "state" / "morning_decision.json"
STATE_DIR = HERE / "state"
DEFAULT_LOOKBACK_DAYS = 7

BLOCK_TERMS = [
    "accounting probe",
    "accounting issue",
    "accounting irregular",
    "bankruptcy",
    "criminal",
    "fraud",
    "guidance cut",
    "guidance slashed",
    "investigation",
    "lawsuit ruling",
    "sec charges",
    "sec investigation",
    "subpoena",
]

CAUTION_TERMS = [
    "analyst downgrade",
    "downgrade",
    "debt",
    "dilution",
    "offering",
    "plunge",
    "regulatory",
    "selloff",
    "short seller",
    "volatility",
]


@dataclass
class Article:
    title: str
    link: str
    published: str | None
    summary: str


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def symbol_state_path(symbol: str, state_dir: Path = STATE_DIR) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", symbol.upper())
    return state_dir / f"{safe}.json"


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def candidate_from_decision(decision: dict[str, Any]) -> tuple[str | None, str | None]:
    candidate = decision.get("best_candidate") or {}
    symbol = candidate.get("symbol")
    expiration = candidate.get("expiration")
    if symbol:
        return str(symbol), str(expiration) if expiration else None
    if decision.get("action") != "CHECK_CANDIDATE":
        return None, None
    for candidate in decision.get("candidates") or []:
        if candidate.get("symbol"):
            return str(candidate["symbol"]), str(candidate.get("expiration")) if candidate.get("expiration") else None
    return None, None


def fetch_yahoo_headlines(symbol: str, timeout: int = 15) -> list[Article]:
    params = urllib.parse.urlencode({"s": symbol, "region": "US", "lang": "en-US"})
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "trading-catalyst-check/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        xml = resp.read()

    root = ET.fromstring(xml)
    articles: list[Article] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        summary = re.sub(r"\s+", " ", (item.findtext("description") or "").strip())
        published = item.findtext("pubDate")
        if published:
            try:
                published = parsedate_to_datetime(published).isoformat()
            except Exception:
                published = published.strip()
        if title:
            articles.append(Article(title=title, link=link, published=published, summary=summary))
    return articles


def matching_terms(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term in lowered]


def classify_articles(symbol: str, articles: list[Article], fetch_error: str | None = None) -> dict[str, Any]:
    hits: list[dict[str, Any]] = []
    verdict = "clean"

    if fetch_error:
        verdict = "caution"
        hits.append({
            "severity": "caution",
            "terms": ["news fetch failed"],
            "title": fetch_error,
            "link": "",
            "published": None,
        })
    elif not articles:
        verdict = "caution"
        hits.append({
            "severity": "caution",
            "terms": ["no recent headlines"],
            "title": "No recent headlines found; manual check still required",
            "link": "",
            "published": None,
        })

    for article in articles:
        text = f"{article.title} {article.summary}"
        block = matching_terms(text, BLOCK_TERMS)
        caution = matching_terms(text, CAUTION_TERMS)
        if block:
            verdict = "block"
            hits.append({
                "severity": "block",
                "terms": block,
                "title": article.title,
                "link": article.link,
                "published": article.published,
            })
        elif caution and verdict != "block":
            verdict = "caution"
            hits.append({
                "severity": "caution",
                "terms": caution,
                "title": article.title,
                "link": article.link,
                "published": article.published,
            })

    summary = {
        "clean": f"Catalyst check: {symbol} clean in recent public headlines",
        "caution": f"Catalyst check: {symbol} caution; review flagged headlines before trading",
        "block": f"Catalyst check: {symbol} blocked by company-specific bad-news terms",
    }[verdict]

    return {
        "verdict": verdict,
        "summary": summary,
        "hits": hits[:8],
    }


def write_payload(payload: dict[str, Any], state_dir: Path = STATE_DIR) -> dict[str, Any]:
    state_dir.mkdir(exist_ok=True)
    json_path = state_dir / "latest.json"
    text_path = state_dir / "latest_summary.txt"
    symbol_path = symbol_state_path(payload["symbol"], state_dir) if payload.get("symbol") else None
    payload["output_files"] = {
        "json": display_path(json_path),
        "text": display_path(text_path),
    }
    if symbol_path:
        payload["output_files"]["symbol_json"] = display_path(symbol_path)
    json_path.write_text(json.dumps(payload, indent=2, default=str))
    if symbol_path:
        symbol_path.write_text(json.dumps(payload, indent=2, default=str))
    text_path.write_text(payload["summary"] + "\n")
    return payload


def run(
    symbol: str | None = None,
    expiration: str | None = None,
    decision_path: Path = MORNING_DECISION,
    state_dir: Path = STATE_DIR,
    fetch: bool = True,
) -> dict[str, Any]:
    decision = load_json(decision_path, {})
    if symbol is None:
        symbol, expiration = candidate_from_decision(decision)

    if not symbol:
        return write_payload({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "symbol": None,
            "expiration": expiration,
            "verdict": "caution",
            "summary": "Catalyst check: no candidate symbol available",
            "articles": [],
            "hits": [],
        }, state_dir=state_dir)

    fetch_error = None
    articles: list[Article] = []
    if fetch:
        try:
            articles = fetch_yahoo_headlines(symbol)
        except Exception as exc:
            fetch_error = f"{type(exc).__name__}: {exc}"

    classified = classify_articles(symbol, articles, fetch_error=fetch_error)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "screen_timestamp": decision.get("screen_timestamp"),
        "symbol": symbol,
        "expiration": expiration,
        "source": "yahoo_finance_rss" if fetch else "offline",
        "verdict": classified["verdict"],
        "summary": classified["summary"],
        "articles": [asdict(article) for article in articles[:12]],
        "hits": classified["hits"],
        "fetch_error": fetch_error,
    }
    return write_payload(payload, state_dir=state_dir)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", nargs="?")
    parser.add_argument("--expiration")
    parser.add_argument("--offline", action="store_true", help="Do not fetch news; useful for tests.")
    args = parser.parse_args()

    payload = run(symbol=args.symbol, expiration=args.expiration, fetch=not args.offline)
    print(payload["summary"])
    print(f"Wrote {payload['output_files']['json']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
