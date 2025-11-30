"""
Core type definitions for HFT-Lite.
All components communicate using these standardized types.
"""
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional
from decimal import Decimal
import time


class Venue(Enum):
    """Supported trading venues."""
    KALSHI = auto()
    IBKR = auto()


class Side(Enum):
    """Order/quote side."""
    BID = auto()
    ASK = auto()
    
    @property
    def opposite(self) -> "Side":
        return Side.ASK if self == Side.BID else Side.BID


class OrderType(Enum):
    """Supported order types."""
    LIMIT = auto()
    MARKET = auto()
    FOK = auto()      # Fill-or-Kill
    IOC = auto()      # Immediate-or-Cancel


class OrderStatus(Enum):
    """Order lifecycle states."""
    PENDING = auto()
    SUBMITTED = auto()
    PARTIAL = auto()
    FILLED = auto()
    CANCELLED = auto()
    REJECTED = auto()


class ContractType(Enum):
    """Type of prediction market contract."""
    YES = auto()
    NO = auto()


@dataclass(frozen=True, slots=True)
class NormalizedTick:
    """
    Unified tick format across all venues.
    
    All probabilities are expressed as Decimal in [0.01, 0.99].
    Timestamps are Unix epoch nanoseconds for precision.
    """
    symbol: str                     # Unified symbol ID (e.g., "FED-RATE-DEC-2024")
    venue: Venue
    bid_price: Decimal              # Best bid probability
    bid_size: int                   # Contracts available at bid
    ask_price: Decimal              # Best ask probability
    ask_size: int                   # Contracts available at ask
    timestamp_exchange: int         # Exchange timestamp (nanos)
    timestamp_local: int = field(   # Local receipt timestamp (nanos)
        default_factory=lambda: time.time_ns()
    )
    sequence: int = 0               # Venue-specific sequence number for ordering
    
    @property
    def spread(self) -> Decimal:
        """Bid-ask spread in probability terms."""
        return self.ask_price - self.bid_price
    
    @property
    def mid_price(self) -> Decimal:
        """Midpoint price."""
        return (self.bid_price + self.ask_price) / 2
    
    @property
    def latency_ns(self) -> int:
        """Feed latency in nanoseconds."""
        return self.timestamp_local - self.timestamp_exchange
    
    def is_stale(self, max_age_ns: int = 500_000_000) -> bool:
        """Check if tick is stale (default 500ms)."""
        return (time.time_ns() - self.timestamp_local) > max_age_ns


@dataclass(frozen=True, slots=True)
class ArbitrageSignal:
    """
    Emitted when a profitable arbitrage opportunity is detected.
    """
    symbol: str
    buy_venue: Venue
    sell_venue: Venue
    buy_price: Decimal              # Price to pay (ask)
    sell_price: Decimal             # Price to receive (bid)
    size: int                       # Max executable size
    expected_profit: Decimal        # Gross profit before fees
    expected_profit_net: Decimal    # Net profit after fees
    timestamp: int = field(default_factory=time.time_ns)
    signal_id: str = ""             # Unique identifier for tracking
    
    @property
    def edge_bps(self) -> Decimal:
        """Edge in basis points."""
        if self.buy_price == 0:
            return Decimal(0)
        return ((self.sell_price - self.buy_price) / self.buy_price) * 10000


@dataclass(slots=True)
class Order:
    """
    Order representation for execution.
    """
    order_id: str
    symbol: str
    venue: Venue
    side: Side
    price: Decimal
    size: int
    order_type: OrderType
    status: OrderStatus = OrderStatus.PENDING
    filled_size: int = 0
    filled_price: Optional[Decimal] = None
    created_at: int = field(default_factory=time.time_ns)
    updated_at: int = field(default_factory=time.time_ns)
    venue_order_id: Optional[str] = None
    parent_signal_id: Optional[str] = None  # Links back to ArbitrageSignal
    
    @property
    def is_terminal(self) -> bool:
        """Check if order is in a terminal state."""
        return self.status in (
            OrderStatus.FILLED, 
            OrderStatus.CANCELLED, 
            OrderStatus.REJECTED
        )
    
    @property
    def remaining_size(self) -> int:
        return self.size - self.filled_size


@dataclass(slots=True)
class Position:
    """
    Current position in a contract.
    """
    symbol: str
    venue: Venue
    quantity: int = 0               # Positive = long, Negative = short
    avg_entry_price: Decimal = Decimal(0)
    realized_pnl: Decimal = Decimal(0)
    unrealized_pnl: Decimal = Decimal(0)
    
    def update_from_fill(self, side: Side, fill_price: Decimal, fill_size: int) -> None:
        """Update position from a fill."""
        if side == Side.BID:  # Buying
            if self.quantity >= 0:  # Adding to long
                total_cost = (self.avg_entry_price * self.quantity) + (fill_price * fill_size)
                self.quantity += fill_size
                self.avg_entry_price = total_cost / self.quantity if self.quantity else Decimal(0)
            else:  # Covering short
                self.realized_pnl += (self.avg_entry_price - fill_price) * min(fill_size, abs(self.quantity))
                self.quantity += fill_size
        else:  # Selling
            if self.quantity <= 0:  # Adding to short
                total_cost = (self.avg_entry_price * abs(self.quantity)) + (fill_price * fill_size)
                self.quantity -= fill_size
                self.avg_entry_price = total_cost / abs(self.quantity) if self.quantity else Decimal(0)
            else:  # Closing long
                self.realized_pnl += (fill_price - self.avg_entry_price) * min(fill_size, self.quantity)
                self.quantity -= fill_size


@dataclass(frozen=True, slots=True)
class FeeSchedule:
    """
    Fee structure for a venue.
    All fees expressed as Decimal fractions (e.g., 0.01 = 1%).
    """
    venue: Venue
    maker_fee: Decimal              # Fee for providing liquidity
    taker_fee: Decimal              # Fee for taking liquidity
    per_contract_fee: Decimal       # Fixed fee per contract
    min_fee: Decimal = Decimal(0)   # Minimum fee per order
    max_fee: Decimal = Decimal("inf")  # Maximum fee per order
    
    def calculate(self, price: Decimal, size: int, is_maker: bool) -> Decimal:
        """Calculate total fee for a trade."""
        rate = self.maker_fee if is_maker else self.taker_fee
        percentage_fee = price * size * rate
        fixed_fee = self.per_contract_fee * size
        total = percentage_fee + fixed_fee
        return max(self.min_fee, min(total, self.max_fee))
