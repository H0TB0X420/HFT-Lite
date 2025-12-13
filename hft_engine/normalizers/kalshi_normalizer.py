"""
Kalshi exchange normalizer.

Converts Kalshi ticker messages to NormalizedTick format.
"""
import time
from decimal import Decimal

from ..core.normalized_tick import Exchange, NormalizedTick
from .base import BaseNormalizer
from .symbol_map import kalshi_to_unified


class KalshiNormalizer(BaseNormalizer):
    """Normalizes Kalshi WebSocket messages."""

    def normalize(self, raw_message: dict) -> NormalizedTick | None:
        """Convert Kalshi orderbook message to NormalizedTick."""
        msg_type = raw_message.get("type")
        
        if msg_type not in ("orderbook_snapshot", "orderbook_delta"):
            return None
        
        msg = raw_message.get("msg", {})
        market_ticker = msg.get("market_ticker")
        
        if not market_ticker:
            return None
        
        yes_orders = msg.get("yes", [])  # [[price_cents, size], ...]
        no_orders = msg.get("no", [])
        
        if not yes_orders or not no_orders:
            return None
        
        # Kalshi: buying YES = taking the lowest YES offer
        # But Kalshi shows bids, not asks. You buy by hitting the other side.
        # YES price to buy = 100 - highest NO bid
        # NO price to buy = 100 - highest YES bid
        
        highest_yes_bid = max(order[0] for order in yes_orders)
        highest_no_bid = max(order[0] for order in no_orders)
        
        yes_ask = (Decimal(100) - Decimal(highest_no_bid)) / Decimal(100)
        no_ask = (Decimal(100) - Decimal(highest_yes_bid)) / Decimal(100)
        
        # Sizes at best prices
        yes_ask_size = next(order[1] for order in no_orders if order[0] == highest_no_bid)
        no_ask_size = next(order[1] for order in yes_orders if order[0] == highest_yes_bid)
        
        timestamp_local = time.time_ns()
        unified_symbol = kalshi_to_unified(market_ticker)

        return NormalizedTick(
            exchange=Exchange.KALSHI,
            symbol=unified_symbol,
            timestamp_exchange=timestamp_local,
            timestamp_local=timestamp_local,
            yes_ask=yes_ask,
            no_ask=no_ask,
            yes_ask_size=yes_ask_size,
            no_ask_size=no_ask_size,
            last=None,
            last_size=None,
        )