"""
Event scanner — checks for upcoming catalyst events before entering trades.

Catches things that can blow up an options position:
- FOMC meetings (rate decisions move everything)
- CPI releases (inflation data = volatility)
- Jobs reports (first Friday of each month)
- Earnings dates (already in pretrade.py, imported here)
- Company-specific: court cases, regulatory rulings, congressional hearings

Structured events (FOMC, CPI, earnings) are checked automatically.
Company-specific events require web search — this module generates the queries
and provides an assessment framework.

Usage:
    # CLI: check structured events + get search queries
    python event_scanner.py META 2026-04-24

    # Import: use in pretrade.py
    from event_scanner import scan_events, get_search_queries
"""
import sys
from datetime import datetime, date, timedelta

# ---------------------------------------------------------------------------
# MACRO EVENT CALENDARS (update these periodically)
# ---------------------------------------------------------------------------

# 2026 FOMC meeting dates (statement released day 2 at 2pm ET)
FOMC_DATES = [
    ("2026-01-28", "FOMC rate decision"),
    ("2026-03-18", "FOMC rate decision"),
    ("2026-04-29", "FOMC rate decision"),
    ("2026-06-17", "FOMC rate decision"),
    ("2026-07-29", "FOMC rate decision"),
    ("2026-09-16", "FOMC rate decision"),
    ("2026-10-28", "FOMC rate decision"),
    ("2026-12-09", "FOMC rate decision"),
]

# 2026 CPI release dates (8:30am ET)
CPI_DATES = [
    ("2026-01-13", "CPI release"),
    ("2026-02-11", "CPI release"),
    ("2026-03-11", "CPI release"),
    ("2026-04-10", "CPI release"),
    ("2026-05-12", "CPI release"),
    ("2026-06-10", "CPI release"),
    ("2026-07-14", "CPI release"),
    ("2026-08-12", "CPI release"),
    ("2026-09-11", "CPI release"),
    ("2026-10-14", "CPI release"),
    ("2026-11-10", "CPI release"),
    ("2026-12-10", "CPI release"),
]

# Jobs reports: typically first Friday of each month (approximate)
JOBS_DATES = [
    ("2026-01-09", "Jobs report (NFP)"),
    ("2026-02-06", "Jobs report (NFP)"),
    ("2026-03-06", "Jobs report (NFP)"),
    ("2026-04-03", "Jobs report (NFP)"),
    ("2026-05-08", "Jobs report (NFP)"),
    ("2026-06-05", "Jobs report (NFP)"),
    ("2026-07-02", "Jobs report (NFP)"),
    ("2026-08-07", "Jobs report (NFP)"),
    ("2026-09-04", "Jobs report (NFP)"),
    ("2026-10-02", "Jobs report (NFP)"),
    ("2026-11-06", "Jobs report (NFP)"),
    ("2026-12-04", "Jobs report (NFP)"),
]

# Earnings dates — INTENTIONALLY EMPTY. Earnings is NOT a gate (RULES.md §5).
# The screener forces the strike outside the option-implied expected move
# (screener_select.best_put_from_chain), so a name with a print in the window is
# pushed to a deeper cushion automatically — no calendar required. This dict used
# to hold hand-maintained dates that silently went stale; it now exists only as a
# plug-in point for context/display (days_from_earnings, post-earnings variant).
# Populate ONLY from a live feed, and ONLY for display — never wire it to a gate.
EARNINGS_CALENDAR = {}

# Sector-specific regulatory bodies that matter
REGULATORY_CONTEXT = {
    "META": "FTC antitrust, EU DMA/DSA, state AG lawsuits, Section 230",
    "GOOGL": "DOJ antitrust, EU DMA, ad-tech litigation",
    "AMZN": "FTC antitrust, labor/NLRB, EU Digital Markets Act",
    "AAPL": "DOJ antitrust, EU DMA (sideloading), App Store litigation",
    "MSFT": "EU/CMA regulatory (Activision aftermath), AI regulation",
    "NVDA": "Export controls (China), antitrust (AI chip dominance)",
    "AMD": "Export controls (China), patent litigation",
    "TSM": "Geopolitical (Taiwan/China), CHIPS Act compliance",
    "COIN": "SEC enforcement, crypto regulation bills",
    "SHOP": "E-commerce regulation, payment processing",
    "NET": "Content moderation liability, gov contracts",
    "NFLX": "Content regulation, international licensing",
    "ASML": "Export controls (China/Netherlands), geopolitical",
    "IBIT": "SEC crypto ETF rules, Bitcoin regulation",
    "HUBS": "M&A rumors, SaaS sector regulation",
}


def _parse_date(d):
    """Parse a date string or return a date object as-is."""
    if isinstance(d, date):
        return d
    return datetime.strptime(d, "%Y-%m-%d").date()


def check_macro_events(start_date, end_date):
    """Find all macro events (FOMC, CPI, jobs) in a date window."""
    start = _parse_date(start_date)
    end = _parse_date(end_date)
    events = []

    for date_str, label in FOMC_DATES + CPI_DATES + JOBS_DATES:
        event_date = _parse_date(date_str)
        if start <= event_date <= end:
            days_away = (event_date - start).days
            severity = "RED" if "FOMC" in label else "YELLOW"
            events.append({
                "date": date_str,
                "event": label,
                "days_away": days_away,
                "severity": severity,
                "source": "calendar",
            })

    return sorted(events, key=lambda e: e["date"])


def check_earnings(symbol, expiration_date):
    """Check if earnings fall within the trade window."""
    earnings_str = EARNINGS_CALENDAR.get(symbol)
    if not earnings_str:
        return None

    earnings = _parse_date(earnings_str)
    today = date.today()
    exp = _parse_date(expiration_date)

    if today < earnings <= exp:
        days_away = (earnings - today).days
        return {
            "date": earnings_str,
            "event": f"{symbol} earnings",
            "days_away": days_away,
            "severity": "RED",
            "source": "earnings_calendar",
        }
    return None


def get_search_queries(symbol):
    """
    Generate web search queries Claude should run for company-specific events.
    Returns a list of (query, description) tuples.
    """
    queries = []

    # Court cases and legal
    queries.append((
        f"{symbol} court case ruling lawsuit 2026",
        "Pending court cases or rulings"
    ))

    # Regulatory
    reg_context = REGULATORY_CONTEXT.get(symbol, "regulatory action")
    queries.append((
        f"{symbol} {reg_context.split(',')[0]} ruling decision 2026",
        f"Regulatory: {reg_context}"
    ))

    # Congressional hearings
    queries.append((
        f"{symbol} congressional hearing Senate House testimony 2026",
        "Congressional hearings or testimony"
    ))

    # Upcoming catalysts (general)
    queries.append((
        f"{symbol} stock upcoming catalyst event April May 2026",
        "General upcoming catalysts"
    ))

    return queries


def scan_events(symbol, expiration_date, web_events=None):
    """
    Main function: scan all event sources for a symbol.

    Args:
        symbol: Stock ticker
        expiration_date: Option expiration (date or "YYYY-MM-DD")
        web_events: Optional list of events found via web search.
                    Each should be a dict with: date, event, severity, source

    Returns:
        dict with: events, verdict (RED/YELLOW/GREEN), search_queries, summary
    """
    today = date.today()
    exp = _parse_date(expiration_date)
    all_events = []

    # 1. Macro events in the window
    macro = check_macro_events(today, exp)
    all_events.extend(macro)

    # 2. Earnings
    earnings = check_earnings(symbol, exp)
    if earnings:
        all_events.append(earnings)

    # 3. Web search results (if provided)
    if web_events:
        all_events.extend(web_events)

    # 4. Generate search queries for what we CAN'T check automatically
    queries = get_search_queries(symbol)

    # Determine overall verdict
    red_events = [e for e in all_events if e["severity"] == "RED"]
    yellow_events = [e for e in all_events if e["severity"] == "YELLOW"]

    if red_events:
        verdict = "RED"
    elif yellow_events:
        verdict = "YELLOW"
    else:
        verdict = "GREEN"

    # If no web search was done, flag it
    web_searched = web_events is not None
    if not web_searched:
        verdict = max(verdict, "YELLOW", key=["GREEN", "YELLOW", "RED"].index)

    # Build summary
    summary_lines = []
    if red_events:
        summary_lines.append(f"RED — {len(red_events)} high-impact event(s) in window:")
        for e in red_events:
            summary_lines.append(f"  {e['date']} — {e['event']} ({e['days_away']}d away)")
    if yellow_events:
        summary_lines.append(f"YELLOW — {len(yellow_events)} moderate event(s):")
        for e in yellow_events:
            summary_lines.append(f"  {e['date']} — {e['event']} ({e['days_away']}d away)")
    if not web_searched:
        summary_lines.append("YELLOW — Web search NOT yet run. Company-specific events unchecked.")
        summary_lines.append("Run these searches before trading:")
        for query, desc in queries:
            summary_lines.append(f"  Search: \"{query}\"")
            summary_lines.append(f"  Why: {desc}")
    if not all_events and web_searched:
        summary_lines.append("GREEN — No known events in window. Clear to trade.")

    return {
        "symbol": symbol,
        "expiration": str(exp),
        "events": all_events,
        "verdict": verdict,
        "web_searched": web_searched,
        "search_queries": queries,
        "summary": "\n".join(summary_lines),
    }


def format_report(result):
    """Pretty-print the event scan report."""
    lines = []
    v = result["verdict"]
    icon = {"RED": "[!!!]", "YELLOW": "[!!]", "GREEN": "[OK]"}[v]

    lines.append(f"EVENT SCAN: {result['symbol']} (exp {result['expiration']})")
    lines.append(f"Verdict: {icon} {v}")
    lines.append("")
    lines.append(result["summary"])
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python event_scanner.py SYMBOL EXPIRATION_DATE")
        print("Example: python event_scanner.py META 2026-04-24")
        sys.exit(1)

    symbol = sys.argv[1].upper()
    exp_date = sys.argv[2]

    result = scan_events(symbol, exp_date)
    print(format_report(result))
