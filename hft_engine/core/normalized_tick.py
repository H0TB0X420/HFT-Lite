"""
Normalized tick representation for cross-exchange arbitrage.

All prices normalized to decimal (0.00-1.00) for event contracts.
All timestamps in nanoseconds.
"""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class Exchange(Enum):
    KALSHI = "KALSHI"
    IBKR = "IBKR"


@dataclass(frozen=True)
class NormalizedTick:
    """Normalized tick from any exchange."""
    exchange: Exchange
    symbol: str
    timestamp_exchange: int
    timestamp_local: int
    yes_ask: Decimal      # Price to BUY YES
    no_ask: Decimal       # Price to BUY NO
    yes_ask_size: int     # Contracts available at yes_ask
    no_ask_size: int      # Contracts available at no_ask
    last: Decimal | None
    last_size: int | None
    
    @property
    def spread(self) -> Decimal:
        """Gap from parity. Negative = arb opportunity."""
        return (self.yes_ask + self.no_ask) - Decimal("1.00")
    
    @property
    def mid(self) -> Decimal:
        """Implied YES probability."""
        return self.yes_ask

    def __post_init__(self):
        if not (Decimal("0") <= self.yes_ask <= Decimal("1")):
            raise ValueError(f"yes_ask must be 0.00-1.00, got {self.yes_ask}")
        if not (Decimal("0") <= self.no_ask <= Decimal("1")):
            raise ValueError(f"no_ask must be 0.00-1.00, got {self.no_ask}")