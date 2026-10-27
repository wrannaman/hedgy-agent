"""
THE canonical screening universe — one list, defined once, imported everywhere (FUND.md §6).

Lives in shared/ because multiple sleeves consume it (csp_401k put screener, pead
earnings screener) and sleeves may never import each other's code. shared/ is
plumbing, and a watchlist is plumbing.

The old bot watched 16 mega-cap names — all moderate volatility, so a 10%-cushion
put on them rarely paid the premium floor, and it only ever looked on red days.
That is why it almost never traded.

This list is wide and *deliberately spans the volatility spectrum* — the fat
premium lives in the high-IV names (semis, crypto proxies, biotech, volatile
single names, leveraged ETFs), not the mega-cap index sleeve. The screener sweeps
all of these every run, no red-day requirement.

Not a buy list — a *look* list. Every name still has to clear the judgment-layer
gates (cushion, premium, earnings, willing-owner, concentration) before anything
is recommended.
"""

UNIVERSE = [
    # --- mega-cap / large tech (lower IV, the index sleeve) ---
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "TSLA",
    "NFLX", "ORCL", "CRM", "ADBE", "CSCO", "INTC", "QCOM", "TXN",

    # --- semiconductors (high IV — where far-OTM puts pay) ---
    "AMD", "MU", "TSM", "ASML", "MRVL", "ARM", "SMCI", "ON", "LRCX",
    "AMAT", "KLAC", "ADI", "NXPI", "MCHP", "WDC", "STX",

    # --- software / high-beta growth (high IV) ---
    "SHOP", "NET", "CRWD", "DDOG", "SNOW", "PLTR", "NOW", "PANW", "ZS",
    "MDB", "ABNB", "UBER", "DASH", "RBLX", "U", "TWLO", "TEAM", "HUBS",
    "WDAY", "OKTA",

    # --- crypto proxies (very high IV) ---
    "COIN", "MSTR", "MARA", "RIOT", "CLSK", "HOOD", "IBIT", "BITO",

    # --- fintech / volatile consumer ---
    "SOFI", "AFRM", "UPST", "PYPL", "NU",

    # --- volatile single names / meme ---
    "GME", "AMC", "LCID", "RIVN", "CVNA", "DKNG", "PINS", "SNAP",
    "ROKU", "CHWY", "CART",

    # --- space / new-space (high IV, halo-trade sleeve, narrative-driven) ---
    # The account label (401k) doesn't dictate the risk profile of the
    # strategy — this is a mini hedge fund that happens to be funded by 401k
    # cash. Include speculative names; the screener's liquidity + cushion +
    # premium gates decide what makes the cut, and the willing-owner gate is
    # about the trade thesis, not "is this appropriate for a retirement account."
    "SPCX", "RKLB", "LUNR", "ASTS", "RDW", "PL", "BKSY", "JOBY", "ACHR",

    # --- biotech / pharma (event-driven, high IV) ---
    "LLY", "UNH", "PFE", "JNJ", "MRK", "ABBV", "MRNA", "BNTX", "VRTX",
    "REGN", "GILD", "AMGN", "BIIB",

    # --- China ADRs (high IV) ---
    "BABA", "PDD", "JD", "NIO", "LI", "BIDU",

    # --- industrials / airlines / travel ---
    "BA", "DAL", "AAL", "UAL", "CCL", "NCLH", "RCL", "WYNN", "LVS", "MGM",

    # --- data-center buildout / skilled-labor infrastructure (WORLDVIEW T2) ---
    # Electrical-mechanical contractors, equipment, and distribution tied to the
    # labor-constrained AI/grid capex wave. Baseline VRP was thin-to-negative when
    # added (2026-07-08) — these are here to catch the scare-day IV blowouts, not
    # because they pay today. EME/TT/WSO/CARR/HUBB chains are thin; the spread
    # gate decides, not us.
    "ETN", "PWR", "EME", "FIX", "TT", "WSO", "CARR", "VRT", "HUBB",

    # --- autos ---
    "F", "GM",

    # --- energy (commodity vol) ---
    "XOM", "CVX", "OXY", "DVN", "FANG", "SLB", "HAL",

    # --- financials ---
    "JPM", "BAC", "GS", "MS", "C", "WFC", "SCHW", "BLK", "V", "MA", "AXP",

    # --- retail / consumer ---
    "WMT", "TGT", "COST", "HD", "LOW", "MCD", "SBUX", "NKE", "DIS", "LULU",

    # --- ETFs (index + sector). No leveraged ETFs on purpose: getting
    # assigned one leaves you holding a 3x product that decays over the
    # multi-week hold — it fails the willing-owner gate every time. ---
    "SPY", "QQQ", "IWM", "SMH", "ARKK", "XLE", "GDX", "SLV", "GLD",

    # --- hardware / networking ---
    "DELL", "HPE", "ANET",

    # --- large-cap defensives (low IV, completeness) ---
    "T", "VZ", "KO", "PEP",
]

# De-dupe defensively while preserving order.
UNIVERSE = list(dict.fromkeys(UNIVERSE))


# Ticker -> plain English company name. Lives here, next to UNIVERSE, because the
# Slack recap (daily_summary.py) and the morning agent must render the SAME
# "Micron (MU)" string — a bare renamed ticker reads as gibberish (CRON_PROMPT
# rule). Reference data, not a drifting number, so it's safe to keep in code.
# Unknown tickers fall back to the bare symbol via display_name().
COMPANY_NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon",
    "META": "Meta", "NVDA": "Nvidia", "AVGO": "Broadcom", "TSLA": "Tesla",
    "NFLX": "Netflix", "ORCL": "Oracle", "CRM": "Salesforce", "ADBE": "Adobe",
    "CSCO": "Cisco", "INTC": "Intel", "QCOM": "Qualcomm", "TXN": "Texas Instruments",
    "AMD": "AMD", "MU": "Micron", "TSM": "TSMC", "ASML": "ASML", "MRVL": "Marvell",
    "ARM": "Arm", "SMCI": "Super Micro", "ON": "ON Semiconductor", "LRCX": "Lam Research",
    "AMAT": "Applied Materials", "KLAC": "KLA", "ADI": "Analog Devices",
    "NXPI": "NXP", "MCHP": "Microchip", "WDC": "Western Digital", "STX": "Seagate",
    "SHOP": "Shopify", "NET": "Cloudflare", "CRWD": "CrowdStrike", "DDOG": "Datadog",
    "SNOW": "Snowflake", "PLTR": "Palantir", "NOW": "ServiceNow", "PANW": "Palo Alto Networks",
    "ZS": "Zscaler", "MDB": "MongoDB", "ABNB": "Airbnb", "UBER": "Uber", "DASH": "DoorDash",
    "RBLX": "Roblox", "U": "Unity", "TWLO": "Twilio", "TEAM": "Atlassian", "HUBS": "HubSpot",
    "WDAY": "Workday", "OKTA": "Okta",
    "COIN": "Coinbase", "MSTR": "Strategy", "MARA": "Marathon Digital", "RIOT": "Riot Platforms",
    "CLSK": "CleanSpark", "HOOD": "Robinhood", "IBIT": "iShares Bitcoin", "BITO": "Bitcoin Strategy ETF",
    "SOFI": "SoFi", "AFRM": "Affirm", "UPST": "Upstart", "PYPL": "PayPal", "NU": "Nu Holdings",
    "GME": "GameStop", "AMC": "AMC", "LCID": "Lucid", "RIVN": "Rivian", "CVNA": "Carvana",
    "DKNG": "DraftKings", "PINS": "Pinterest", "SNAP": "Snap", "ROKU": "Roku", "CHWY": "Chewy",
    "CART": "Instacart",
    "SPCX": "SpaceX", "RKLB": "Rocket Lab", "LUNR": "Intuitive Machines", "ASTS": "AST SpaceMobile", "RDW": "Redwire",
    "PL": "Planet Labs", "BKSY": "BlackSky", "JOBY": "Joby Aviation", "ACHR": "Archer Aviation",
    "LLY": "Eli Lilly", "UNH": "UnitedHealth", "PFE": "Pfizer", "JNJ": "Johnson & Johnson",
    "MRK": "Merck", "ABBV": "AbbVie", "MRNA": "Moderna", "BNTX": "BioNTech", "VRTX": "Vertex",
    "REGN": "Regeneron", "GILD": "Gilead", "AMGN": "Amgen", "BIIB": "Biogen",
    "BABA": "Alibaba", "PDD": "PDD", "JD": "JD.com", "NIO": "NIO", "LI": "Li Auto", "BIDU": "Baidu",
    "BA": "Boeing", "DAL": "Delta", "AAL": "American Airlines", "UAL": "United Airlines",
    "CCL": "Carnival", "NCLH": "Norwegian Cruise", "RCL": "Royal Caribbean", "WYNN": "Wynn",
    "LVS": "Las Vegas Sands", "MGM": "MGM",
    "F": "Ford", "GM": "General Motors",
    "ETN": "Eaton", "PWR": "Quanta Services", "EME": "EMCOR", "FIX": "Comfort Systems",
    "TT": "Trane Technologies", "WSO": "Watsco", "CARR": "Carrier", "VRT": "Vertiv",
    "HUBB": "Hubbell",
    "XOM": "ExxonMobil", "CVX": "Chevron", "OXY": "Occidental", "DVN": "Devon Energy",
    "FANG": "Diamondback", "SLB": "SLB", "HAL": "Halliburton",
    "JPM": "JPMorgan", "BAC": "Bank of America", "GS": "Goldman Sachs", "MS": "Morgan Stanley",
    "C": "Citigroup", "WFC": "Wells Fargo", "SCHW": "Schwab", "BLK": "BlackRock",
    "V": "Visa", "MA": "Mastercard", "AXP": "American Express",
    "WMT": "Walmart", "TGT": "Target", "COST": "Costco", "HD": "Home Depot", "LOW": "Lowe's",
    "MCD": "McDonald's", "SBUX": "Starbucks", "NKE": "Nike", "DIS": "Disney", "LULU": "Lululemon",
    "SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Russell 2000", "SMH": "Semiconductor ETF",
    "ARKK": "ARK Innovation", "XLE": "Energy ETF", "GDX": "Gold Miners ETF", "SLV": "Silver ETF",
    "GLD": "Gold ETF",
    "DELL": "Dell", "HPE": "HP Enterprise", "ANET": "Arista",
    "T": "AT&T", "VZ": "Verizon", "KO": "Coca-Cola", "PEP": "PepsiCo",
}


def display_name(symbol):
    """'MU' -> 'Micron (MU)'; unknown ticker -> 'MU'. The one place the
    name+ticker string is built, so the recap and agent never disagree."""
    name = COMPANY_NAMES.get(symbol)
    return f"{name} ({symbol})" if name else symbol
