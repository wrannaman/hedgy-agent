"""
Variant interface — every strategy variant exposes these objects/functions.

A variant is the full spec of: when to enter, what instrument, what strike/expiration,
when to exit. Two variants with the same name are the same variant.

Contract each variant module must expose:
    name: str                                                # unique identifier
    description: str                                         # one-line human description
    def entry_signals(market_state) -> list[EntrySignal]
    def compose_order(signal, market_state, client) -> Order | None
    def manage_position(position, market_state) -> ManagementAction
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple


@dataclass
class EntrySignal:
    """One 'we should consider entering here' emitted by a variant."""
    symbol: str
    reason: str
    target_dte: Tuple[int, int] = (28, 45)
    target_otm_pct: Tuple[float, float] = (7.0, 10.0)
    instrument: str = "cash_secured_put"
    priority: int = 0
    meta: dict = field(default_factory=dict)


@dataclass
class Order:
    """Concrete order composed from a signal + live option chain."""
    action: str               # "SELL_TO_OPEN" | "BUY_TO_CLOSE"
    instrument: str           # "cash_secured_put" | "put_spread" | "covered_call"
    symbol: str
    sell_strike: float
    buy_strike: Optional[float]
    expiration: str           # YYYY-MM-DD
    contracts: int
    limit_price: float
    duration: str = "DAY"
    current_price: Optional[float] = None
    otm_pct: Optional[float] = None
    delta: Optional[float] = None
    dte: Optional[int] = None


@dataclass
class ManagementAction:
    """What to do about an open position given current state."""
    action: str               # "close" | "hold" | "alert" | "roll"
    reason: str
    urgency: str = "normal"   # "immediate" | "normal" | "info"
