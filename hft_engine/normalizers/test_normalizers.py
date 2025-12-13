"""Tests for normalizers."""
import math
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from hft_engine.core.normalized_tick import Exchange, NormalizedTick
from hft_engine.normalizers.kalshi_normalizer import KalshiNormalizer
from hft_engine.normalizers.ibkr_normalizer import IBKRNormalizer
from hft_engine.normalizers.symbol_map import (
    add_mapping,
    kalshi_to_unified,
    ibkr_to_unified,
)

class TestKalshiNormalizer:
    """Tests for Kalshi normalizer."""
    
    def setup_method(self):
        self.normalizer = KalshiNormalizer()
    
    def test_normalize_ticker_message(self):
        """Basic ticker normalization."""
        raw = {
            "type": "ticker",
            "sid": 1,
            "msg": {
                "market_ticker": "KXETHATH-25DEC31",
                "yes_bid": 42,
                "yes_ask": 44,
                "price": 43,
                "volume": 1000,
                "ts": 1700000000,
            }
        }
        
        tick = self.normalizer.normalize(raw)
        
        assert tick is not None
        assert tick.exchange == Exchange.KALSHI
        assert tick.symbol == "KXETHATH-25DEC31"
        assert tick.bid == Decimal("0.42")
        assert tick.ask == Decimal("0.44")
        assert tick.last == Decimal("0.43")
        assert tick.timestamp_exchange == 1700000000 * 1_000_000_000
    
    def test_normalize_returns_none_for_non_ticker(self):
        """Non-ticker messages return None."""
        raw = {"type": "subscribed", "id": 1}
        assert self.normalizer.normalize(raw) is None
    
    def test_normalize_returns_none_for_zero_prices(self):
        """Zero bid/ask returns None."""
        raw = {
            "type": "ticker",
            "msg": {
                "market_ticker": "TEST",
                "yes_bid": 0,
                "yes_ask": 0,
                "ts": 1700000000,
            }
        }
        assert self.normalizer.normalize(raw) is None
    
    def test_price_range_cents_to_decimal(self):
        """Verify cents (1-99) converts to decimal (0.01-0.99)."""
        raw = {
            "type": "ticker",
            "msg": {
                "market_ticker": "TEST",
                "yes_bid": 1,
                "yes_ask": 99,
                "ts": 1700000000,
            }
        }
        
        tick = self.normalizer.normalize(raw)
        assert tick is not None
        assert tick.bid == Decimal("0.01")
        assert tick.ask == Decimal("0.99")
    
    def test_bid_size_ask_size_are_zero(self):
        """Kalshi ticker doesn't provide sizes."""
        raw = {
            "type": "ticker",
            "msg": {
                "market_ticker": "TEST",
                "yes_bid": 50,
                "yes_ask": 51,
                "ts": 1700000000,
            }
        }
        
        tick = self.normalizer.normalize(raw)
        assert tick is not None
        assert tick.bid_size == 0
        assert tick.ask_size == 0


class TestIBKRNormalizer:
    """Tests for IBKR normalizer."""
    
    def setup_method(self):
        self.normalizer = IBKRNormalizer()
    
    def test_normalize_tick_message(self):
        """Basic tick normalization."""
        raw = {
            "type": "tick",
            "con_id": 12345,
            "symbol": "TEST",
            "bid": 0.42,
            "ask": 0.44,
            "bid_size": 100.0,
            "ask_size": 150.0,
            "last": 0.43,
            "last_size": 10.0,
            "time": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        }
        
        tick = self.normalizer.normalize(raw)
        
        assert tick is not None
        assert tick.exchange == Exchange.IBKR
        assert tick.symbol == "TEST"
        assert tick.bid == Decimal("0.42")
        assert tick.ask == Decimal("0.44")
        assert tick.bid_size == 100
        assert tick.ask_size == 150
        assert tick.last == Decimal("0.43")
        assert tick.last_size == 10
    
    def test_normalize_returns_none_for_non_tick(self):
        """Non-tick messages return None."""
        raw = {"type": "connection", "status": "ok"}
        assert self.normalizer.normalize(raw) is None
    
    def test_nan_handling_returns_none(self):
        """NaN bid/ask returns None."""
        raw = {
            "type": "tick",
            "con_id": 12345,
            "symbol": "TEST",
            "bid": float("nan"),
            "ask": float("nan"),
            "bid_size": float("nan"),
            "ask_size": float("nan"),
            "time": None,
        }
        
        tick = self.normalizer.normalize(raw)
        assert tick is None
    
    def test_partial_nan_handling(self):
        """Valid bid/ask with NaN sizes still works."""
        raw = {
            "type": "tick",
            "con_id": 12345,
            "symbol": "TEST",
            "bid": 0.50,
            "ask": 0.52,
            "bid_size": float("nan"),
            "ask_size": float("nan"),
            "last": float("nan"),
            "last_size": float("nan"),
            "time": None,
        }
        
        tick = self.normalizer.normalize(raw)
        
        assert tick is not None
        assert tick.bid == Decimal("0.50")
        assert tick.ask == Decimal("0.52")
        assert tick.bid_size == 0
        assert tick.ask_size == 0
        assert tick.last is None
        assert tick.last_size is None
    
    def test_inverted_bid_ask_returns_none(self):
        """Bid > ask (stale data) returns None."""
        raw = {
            "type": "tick",
            "con_id": 12345,
            "symbol": "TEST",
            "bid": 0.55,
            "ask": 0.50,
            "bid_size": 100,
            "ask_size": 100,
            "time": None,
        }
        
        tick = self.normalizer.normalize(raw)
        assert tick is None
    
    def test_datetime_to_nanoseconds(self):
        """Datetime converts to nanoseconds."""
        dt = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        expected_ns = int(dt.timestamp() * 1_000_000_000)
        
        raw = {
            "type": "tick",
            "con_id": 12345,
            "symbol": "TEST",
            "bid": 0.50,
            "ask": 0.52,
            "bid_size": 100,
            "ask_size": 100,
            "time": dt,
        }
        
        tick = self.normalizer.normalize(raw)
        assert tick is not None
        assert tick.timestamp_exchange == expected_ns


class TestSymbolMapping:
    """Tests for symbol mapping."""
    
    def test_kalshi_unmapped_returns_original(self):
        """Unmapped Kalshi ticker returns original."""
        assert kalshi_to_unified("UNKNOWN-TICKER") == "UNKNOWN-TICKER"
    
    def test_ibkr_unmapped_returns_symbol(self):
        """Unmapped IBKR conId falls back to symbol."""
        assert ibkr_to_unified(99999, "FALLBACK") == "FALLBACK"
    
    def test_add_mapping(self):
        """Runtime mapping works."""
        add_mapping("KALSHI-TEST", 11111, "UNIFIED_TEST")
        
        assert kalshi_to_unified("KALSHI-TEST") == "UNIFIED_TEST"
        assert ibkr_to_unified(11111, "ignored") == "UNIFIED_TEST"


class TestNormalizedTick:
    """Tests for NormalizedTick dataclass."""
    
    def test_spread_calculation(self):
        """Spread property works."""
        tick = NormalizedTick(
            exchange=Exchange.KALSHI,
            symbol="TEST",
            timestamp_exchange=0,
            timestamp_local=0,
            bid=Decimal("0.42"),
            ask=Decimal("0.44"),
            bid_size=0,
            ask_size=0,
        )
        
        assert tick.spread == Decimal("0.02")
    
    def test_mid_calculation(self):
        """Mid property works."""
        tick = NormalizedTick(
            exchange=Exchange.KALSHI,
            symbol="TEST",
            timestamp_exchange=0,
            timestamp_local=0,
            bid=Decimal("0.40"),
            ask=Decimal("0.50"),
            bid_size=0,
            ask_size=0,
        )
        
        assert tick.mid == Decimal("0.45")
    
    def test_latency_calculation(self):
        """Latency property works."""
        tick = NormalizedTick(
            exchange=Exchange.KALSHI,
            symbol="TEST",
            timestamp_exchange=1000,
            timestamp_local=1500,
            bid=Decimal("0.50"),
            ask=Decimal("0.51"),
            bid_size=0,
            ask_size=0,
        )
        
        assert tick.latency_ns == 500
    
    def test_invalid_bid_raises(self):
        """Bid > 1.00 raises ValueError."""
        with pytest.raises(ValueError, match="bid must be"):
            NormalizedTick(
                exchange=Exchange.KALSHI,
                symbol="TEST",
                timestamp_exchange=0,
                timestamp_local=0,
                bid=Decimal("1.50"),
                ask=Decimal("1.60"),
                bid_size=0,
                ask_size=0,
            )
    
    def test_bid_greater_than_ask_raises(self):
        """Bid > ask raises ValueError."""
        with pytest.raises(ValueError, match="bid .* > ask"):
            NormalizedTick(
                exchange=Exchange.KALSHI,
                symbol="TEST",
                timestamp_exchange=0,
                timestamp_local=0,
                bid=Decimal("0.60"),
                ask=Decimal("0.50"),
                bid_size=0,
                ask_size=0,
            )
    
    def test_frozen_immutable(self):
        """Tick is immutable."""
        tick = NormalizedTick(
            exchange=Exchange.KALSHI,
            symbol="TEST",
            timestamp_exchange=0,
            timestamp_local=0,
            bid=Decimal("0.50"),
            ask=Decimal("0.51"),
            bid_size=0,
            ask_size=0,
        )
        
        with pytest.raises(AttributeError):
            tick.bid = Decimal("0.99")
