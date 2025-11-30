"""
Core module - contains types, interfaces, and event bus.
"""
from .types import (
    Venue,
    Side,
    OrderType,
    OrderStatus,
    ContractType,
    NormalizedTick,
    ArbitrageSignal,
    Order,
    Position,
    FeeSchedule,
)
from .interfaces import (
    BaseGateway,
    BaseNormalizer,
    BaseOrderBook,
    BaseStrategy,
    BaseExecutionManager,
    BaseRiskManager,
)
from .event_bus import (
    BoundedEventQueue,
    BackpressurePolicy,
    EventBus,
    QueueStats,
)
from .config import (
    SystemConfig,
    KalshiConfig,
    IBKRConfig,
    RiskConfig,
    FeeConfig,
    SymbolMapping,
    LoggingConfig,
)

__all__ = [
    # Types
    "Venue",
    "Side",
    "OrderType",
    "OrderStatus",
    "ContractType",
    "NormalizedTick",
    "ArbitrageSignal",
    "Order",
    "Position",
    "FeeSchedule",
    # Interfaces
    "BaseGateway",
    "BaseNormalizer",
    "BaseOrderBook",
    "BaseStrategy",
    "BaseExecutionManager",
    "BaseRiskManager",
    # Event Bus
    "BoundedEventQueue",
    "BackpressurePolicy",
    "EventBus",
    "QueueStats",
    # Config
    "SystemConfig",
    "KalshiConfig",
    "IBKRConfig",
    "RiskConfig",
    "FeeConfig",
    "SymbolMapping",
    "LoggingConfig",
]
