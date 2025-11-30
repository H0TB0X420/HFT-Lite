"""
Tests for core types and functionality.
"""
import pytest
from decimal import Decimal
import time

from hft_lite.core import (
    Venue,
    Side,
    OrderType,
    OrderStatus,
    NormalizedTick,
    ArbitrageSignal,
    Order,
    Position,
    FeeSchedule,
)


class TestNormalizedTick:
    """Tests for NormalizedTick dataclass."""
    
    def test_creation(self):
        """Test basic tick creation."""
        tick = NormalizedTick(
            symbol="TEST-SYM",
            venue=Venue.KALSHI,
            bid_price=Decimal("0.45"),
            bid_size=100,
            ask_price=Decimal("0.55"),
            ask_size=50,
            timestamp_exchange=time.time_ns(),
        )
        assert tick.symbol == "TEST-SYM"
        assert tick.venue == Venue.KALSHI
        assert tick.bid_price == Decimal("0.45")
        assert tick.ask_price == Decimal("0.55")
    
    def test_spread_calculation(self):
        """Test spread property."""
        tick = NormalizedTick(
            symbol="TEST",
            venue=Venue.KALSHI,
            bid_price=Decimal("0.40"),
            bid_size=100,
            ask_price=Decimal("0.60"),
            ask_size=100,
            timestamp_exchange=time.time_ns(),
        )
        assert tick.spread == Decimal("0.20")
    
    def test_mid_price_calculation(self):
        """Test mid price property."""
        tick = NormalizedTick(
            symbol="TEST",
            venue=Venue.KALSHI,
            bid_price=Decimal("0.40"),
            bid_size=100,
            ask_price=Decimal("0.60"),
            ask_size=100,
            timestamp_exchange=time.time_ns(),
        )
        assert tick.mid_price == Decimal("0.50")
    
    def test_stale_check(self):
        """Test staleness detection."""
        # Fresh tick
        tick = NormalizedTick(
            symbol="TEST",
            venue=Venue.KALSHI,
            bid_price=Decimal("0.50"),
            bid_size=100,
            ask_price=Decimal("0.51"),
            ask_size=100,
            timestamp_exchange=time.time_ns(),
        )
        assert not tick.is_stale(max_age_ns=1_000_000_000)  # 1 second
        
        # Stale tick (timestamp in past)
        old_tick = NormalizedTick(
            symbol="TEST",
            venue=Venue.KALSHI,
            bid_price=Decimal("0.50"),
            bid_size=100,
            ask_price=Decimal("0.51"),
            ask_size=100,
            timestamp_exchange=time.time_ns() - 2_000_000_000,
            timestamp_local=time.time_ns() - 2_000_000_000,
        )
        assert old_tick.is_stale(max_age_ns=1_000_000_000)
    
    def test_immutability(self):
        """Test that ticks are immutable (frozen dataclass)."""
        tick = NormalizedTick(
            symbol="TEST",
            venue=Venue.KALSHI,
            bid_price=Decimal("0.50"),
            bid_size=100,
            ask_price=Decimal("0.51"),
            ask_size=100,
            timestamp_exchange=time.time_ns(),
        )
        with pytest.raises(AttributeError):
            tick.bid_price = Decimal("0.60")


class TestArbitrageSignal:
    """Tests for ArbitrageSignal dataclass."""
    
    def test_creation(self):
        """Test signal creation."""
        signal = ArbitrageSignal(
            symbol="TEST",
            buy_venue=Venue.KALSHI,
            sell_venue=Venue.IBKR,
            buy_price=Decimal("0.45"),
            sell_price=Decimal("0.55"),
            size=10,
            expected_profit=Decimal("1.00"),
            expected_profit_net=Decimal("0.80"),
        )
        assert signal.buy_venue == Venue.KALSHI
        assert signal.sell_venue == Venue.IBKR
    
    def test_edge_calculation(self):
        """Test edge basis points calculation."""
        signal = ArbitrageSignal(
            symbol="TEST",
            buy_venue=Venue.KALSHI,
            sell_venue=Venue.IBKR,
            buy_price=Decimal("0.50"),
            sell_price=Decimal("0.55"),
            size=10,
            expected_profit=Decimal("0.50"),
            expected_profit_net=Decimal("0.40"),
        )
        # Edge = (0.55 - 0.50) / 0.50 * 10000 = 1000 bps
        assert signal.edge_bps == Decimal("1000.00")


class TestPosition:
    """Tests for Position tracking."""
    
    def test_long_position_update(self):
        """Test updating a long position."""
        pos = Position(symbol="TEST", venue=Venue.KALSHI)
        
        # Buy 10 at 0.50
        pos.update_from_fill(Side.BID, Decimal("0.50"), 10)
        assert pos.quantity == 10
        assert pos.avg_entry_price == Decimal("0.50")
        
        # Buy 10 more at 0.60
        pos.update_from_fill(Side.BID, Decimal("0.60"), 10)
        assert pos.quantity == 20
        assert pos.avg_entry_price == Decimal("0.55")  # Average
    
    def test_closing_long_position(self):
        """Test closing a long position."""
        pos = Position(symbol="TEST", venue=Venue.KALSHI)
        
        # Buy 10 at 0.50
        pos.update_from_fill(Side.BID, Decimal("0.50"), 10)
        
        # Sell 10 at 0.60 (profit)
        pos.update_from_fill(Side.ASK, Decimal("0.60"), 10)
        assert pos.quantity == 0
        assert pos.realized_pnl == Decimal("1.00")  # (0.60 - 0.50) * 10


class TestFeeSchedule:
    """Tests for fee calculations."""
    
    def test_kalshi_fees(self):
        """Test Kalshi fee calculation."""
        fees = FeeSchedule(
            venue=Venue.KALSHI,
            maker_fee=Decimal("0"),
            taker_fee=Decimal("0.07"),  # 7 cents per contract
            per_contract_fee=Decimal("0"),
        )
        
        # Buy 10 contracts at $0.50 as taker
        fee = fees.calculate(Decimal("0.50"), 10, is_maker=False)
        assert fee == Decimal("0.35")  # 0.50 * 10 * 0.07
    
    def test_min_max_fees(self):
        """Test min/max fee constraints."""
        fees = FeeSchedule(
            venue=Venue.IBKR,
            maker_fee=Decimal("0.02"),
            taker_fee=Decimal("0.05"),
            per_contract_fee=Decimal("0"),
            min_fee=Decimal("1.00"),
            max_fee=Decimal("10.00"),
        )
        
        # Small order should hit minimum
        small_fee = fees.calculate(Decimal("0.50"), 1, is_maker=False)
        assert small_fee == Decimal("1.00")  # Min fee applied
        
        # Large order should hit maximum
        large_fee = fees.calculate(Decimal("0.50"), 1000, is_maker=False)
        assert large_fee == Decimal("10.00")  # Max fee applied


class TestSide:
    """Tests for Side enum."""
    
    def test_opposite(self):
        """Test opposite side property."""
        assert Side.BID.opposite == Side.ASK
        assert Side.ASK.opposite == Side.BID


class TestOrder:
    """Tests for Order dataclass."""
    
    def test_order_lifecycle(self):
        """Test order state transitions."""
        order = Order(
            order_id="TEST-001",
            symbol="TEST",
            venue=Venue.KALSHI,
            side=Side.BID,
            price=Decimal("0.50"),
            size=10,
            order_type=OrderType.LIMIT,
        )
        
        assert order.status == OrderStatus.PENDING
        assert not order.is_terminal
        assert order.remaining_size == 10
        
        # Simulate partial fill
        order.status = OrderStatus.PARTIAL
        order.filled_size = 5
        assert order.remaining_size == 5
        assert not order.is_terminal
        
        # Simulate complete fill
        order.status = OrderStatus.FILLED
        order.filled_size = 10
        assert order.remaining_size == 0
        assert order.is_terminal
