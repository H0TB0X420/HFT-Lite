"""
Interactive Brokers exchange normalizer.

Converts IBKR tick messages to NormalizedTick format.
"""
import math
import time
from datetime import datetime
from decimal import Decimal

from ..core.normalized_tick import Exchange, NormalizedTick
from .base import BaseNormalizer
from .symbol_map import ibkr_to_unified


class IBKRNormalizer(BaseNormalizer):
    """Normalizes IBKR tick messages."""
    
    def normalize(self, raw_message: dict) -> NormalizedTick | None:
        """Convert IBKR tick message to NormalizedTick."""
        if raw_message.get("type") != "tick":
            return None
        
        con_id = raw_message.get("con_id")
        symbol = raw_message.get("symbol", "")
        
        if not con_id:
            return None
        
        unified_symbol = ibkr_to_unified(con_id, symbol)
        
        # IBKR provides bid/ask for the contract (YES)
        # bid = price to sell YES
        # ask = price to buy YES
        yes_ask = self._to_decimal(raw_message.get("ask"))
        yes_bid = self._to_decimal(raw_message.get("bid"))
        
        if yes_ask is None or yes_bid is None:
            return None
        
        # NO ask = 1 - YES bid (to buy NO, you sell YES)
        # But ForecastEx has separate NO contracts, so we approximate:
        # no_ask ≈ 1 - yes_bid
        no_ask = Decimal("1.00") - yes_bid
        
        ask_size = self._to_int(raw_message.get("ask_size"))
        bid_size = self._to_int(raw_message.get("bid_size"))
        
        last = self._to_decimal(raw_message.get("last"))
        last_size = self._to_int(raw_message.get("last_size")) if last is not None else None
        
        timestamp_exchange = self._datetime_to_ns(raw_message.get("time"))
        timestamp_local = time.time_ns()
        
        return NormalizedTick(
            exchange=Exchange.IBKR,
            symbol=unified_symbol,
            timestamp_exchange=timestamp_exchange,
            timestamp_local=timestamp_local,
            yes_ask=yes_ask,
            no_ask=no_ask,
            yes_ask_size=ask_size,
            no_ask_size=bid_size,  # Approximation
            last=last,
            last_size=last_size,
        )
    
    @staticmethod
    def _to_decimal(value) -> Decimal | None:
        """Convert float to Decimal, handling nan/None/-1."""
        if value is None:
            return None
        if isinstance(value, float):
            if math.isnan(value):
                return None
            if value < 0:  # IBKR uses -1 for no data
                return None
        return Decimal(str(value))

    @staticmethod
    def _to_int(value) -> int:
        """Convert to int, handling nan/None."""
        if value is None:
            return 0
        if isinstance(value, float):
            if math.isnan(value):
                return 0
            return int(value)
        return int(value)
    
    @staticmethod
    def _datetime_to_ns(dt: datetime | None) -> int:
        """Convert datetime to nanoseconds since epoch."""
        if dt is None:
            return time.time_ns()
        return int(dt.timestamp() * 1_000_000_000)
