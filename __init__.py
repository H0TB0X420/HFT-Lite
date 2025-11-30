"""
HFT-Lite: A Python-based event prediction market arbitrage system.

This package provides infrastructure for cross-venue arbitrage between
Kalshi and Interactive Brokers event contract markets.

Architecture:
    Exchange → Gateway → Normalizer → EventBus → OrderBook → Strategy → Execution

Key Components:
    - core: Type definitions, interfaces, configuration, event bus
    - gateways: Exchange connectivity (Kalshi WebSocket, IBKR TWS)
    - strategy: Arbitrage detection and signal generation
    - execution: Order management and position tracking
    - utils: Logging, time handling, rate limiting

Usage:
    from hft_lite import SystemConfig, EventBus
    from hft_lite.gateways import KalshiGateway, IBKRGateway
    
    config = SystemConfig.load(Path("config.yaml"))
    # ... setup and run
"""

__version__ = "0.1.0"
__author__ = "Your Name"

from .core import (
    # Types
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
    # Interfaces
    BaseGateway,
    BaseNormalizer,
    BaseOrderBook,
    BaseStrategy,
    BaseExecutionManager,
    BaseRiskManager,
    # Event Bus
    BoundedEventQueue,
    BackpressurePolicy,
    EventBus,
    QueueStats,
    # Config
    SystemConfig,
)

from .utils import (
    setup_logging,
    get_logger,
)

__all__ = [
    # Version
    "__version__",
    # Core Types
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
    # Utils
    "setup_logging",
    "get_logger",
]
