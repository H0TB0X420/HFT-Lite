"""
Abstract base classes defining component interfaces.
All concrete implementations must adhere to these contracts.
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Callable, Optional, Awaitable
from decimal import Decimal
import asyncio

from .types import (
    NormalizedTick, 
    Order, 
    OrderStatus, 
    Venue, 
    ArbitrageSignal,
    Position,
    FeeSchedule
)


class BaseGateway(ABC):
    """
    Abstract base class for all exchange gateways.
    
    Gateways are responsible for:
    1. Managing connection lifecycle (connect, disconnect, reconnect)
    2. Authentication and session management
    3. Subscribing to market data streams
    4. Converting venue-specific data to NormalizedTick
    5. Submitting and managing orders
    """
    
    def __init__(self, venue: Venue):
        self.venue = venue
        self._connected = False
        self._subscriptions: set[str] = set()
        self._callbacks: list[Callable[[NormalizedTick], Awaitable[None]]] = []
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the venue."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully disconnect from the venue."""
        pass
    
    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to market data for given symbols."""
        pass
    
    @abstractmethod
    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribe from market data."""
        pass
    
    @abstractmethod
    async def request_snapshot(self, symbol: str) -> Optional[NormalizedTick]:
        """Request full order book snapshot for reconciliation."""
        pass
    
    @abstractmethod
    async def submit_order(self, order: Order) -> Order:
        """Submit an order to the venue. Returns updated Order with venue_order_id."""
        pass
    
    @abstractmethod
    async def cancel_order(self, order: Order) -> Order:
        """Cancel an existing order."""
        pass
    
    @abstractmethod
    async def get_order_status(self, order: Order) -> Order:
        """Query current order status."""
        pass
    
    def register_callback(self, callback: Callable[[NormalizedTick], Awaitable[None]]) -> None:
        """Register a callback to receive normalized ticks."""
        self._callbacks.append(callback)
    
    async def _emit_tick(self, tick: NormalizedTick) -> None:
        """Emit a tick to all registered callbacks."""
        for callback in self._callbacks:
            try:
                await callback(tick)
            except Exception as e:
                # Log but don't propagate - one bad callback shouldn't kill the feed
                print(f"Callback error: {e}")  # Replace with proper logging


class BaseNormalizer(ABC):
    """
    Abstract base class for data normalizers.
    
    Normalizers convert venue-specific data formats into unified NormalizedTick objects.
    """
    
    def __init__(self, venue: Venue):
        self.venue = venue
    
    @abstractmethod
    def normalize(self, raw_data: dict) -> Optional[NormalizedTick]:
        """
        Convert raw venue data to NormalizedTick.
        Returns None if data is invalid or should be filtered.
        """
        pass
    
    @abstractmethod
    def denormalize_price(self, probability: Decimal) -> any:
        """Convert normalized probability back to venue-specific price format."""
        pass


class BaseOrderBook(ABC):
    """
    Abstract base class for order book state management.
    """
    
    @abstractmethod
    def update(self, tick: NormalizedTick) -> None:
        """Update book state with new tick."""
        pass
    
    @abstractmethod
    def get_best_bid(self, symbol: str, venue: Venue) -> Optional[tuple[Decimal, int]]:
        """Get best bid price and size for symbol at venue."""
        pass
    
    @abstractmethod
    def get_best_ask(self, symbol: str, venue: Venue) -> Optional[tuple[Decimal, int]]:
        """Get best ask price and size for symbol at venue."""
        pass
    
    @abstractmethod
    def get_cross_venue_state(self, symbol: str) -> dict[Venue, NormalizedTick]:
        """Get latest ticks for a symbol across all venues."""
        pass
    
    @abstractmethod
    def clear(self, symbol: Optional[str] = None) -> None:
        """Clear book state. If symbol provided, clear only that symbol."""
        pass


class BaseStrategy(ABC):
    """
    Abstract base class for trading strategies.
    """
    
    @abstractmethod
    async def on_tick(self, tick: NormalizedTick) -> Optional[ArbitrageSignal]:
        """
        Process a new tick and potentially generate a signal.
        Returns ArbitrageSignal if opportunity detected, None otherwise.
        """
        pass
    
    @abstractmethod
    def should_trade(self) -> bool:
        """Check if strategy is allowed to trade (risk limits, etc.)."""
        pass


class BaseExecutionManager(ABC):
    """
    Abstract base class for order execution.
    """
    
    @abstractmethod
    async def execute_signal(self, signal: ArbitrageSignal) -> tuple[Order, Order]:
        """
        Execute an arbitrage signal by placing orders at both venues.
        Returns tuple of (buy_order, sell_order).
        """
        pass
    
    @abstractmethod
    async def unwind_position(self, symbol: str) -> list[Order]:
        """Emergency unwind of a position."""
        pass


class BaseRiskManager(ABC):
    """
    Abstract base class for risk management.
    """
    
    @abstractmethod
    def check_order(self, order: Order) -> tuple[bool, str]:
        """
        Validate an order against risk limits.
        Returns (is_allowed, rejection_reason).
        """
        pass
    
    @abstractmethod
    def check_signal(self, signal: ArbitrageSignal) -> tuple[bool, str]:
        """
        Validate an arbitrage signal against risk limits.
        Returns (is_allowed, rejection_reason).
        """
        pass
    
    @abstractmethod
    def update_position(self, position: Position) -> None:
        """Update tracked position state."""
        pass
    
    @abstractmethod
    def get_position(self, symbol: str, venue: Venue) -> Optional[Position]:
        """Get current position for symbol at venue."""
        pass
    
    @abstractmethod
    def get_total_exposure(self) -> Decimal:
        """Get total exposure across all positions."""
        pass
