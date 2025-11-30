"""
HFT-Lite Main Entry Point

This is the application bootstrap that:
1. Loads configuration
2. Initializes all components
3. Starts the event loop
4. Handles graceful shutdown
"""
import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional
import argparse

from hft_lite.core import (
    SystemConfig,
    EventBus,
    BackpressurePolicy,
)
from hft_lite.utils import setup_logging, get_logger


class Application:
    """
    Main application orchestrator.
    
    Manages lifecycle of all components and coordinates shutdown.
    """
    
    def __init__(self, config: SystemConfig):
        self.config = config
        self.logger = get_logger("hft_lite.main")
        self.event_bus = EventBus(default_queue_size=config.queue_max_size)
        self._shutdown_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        
        # Component references (populated during startup)
        self._gateways: list = []
        self._order_book = None
        self._strategy = None
        self._execution_manager = None
        self._risk_manager = None
    
    async def startup(self) -> None:
        """Initialize and start all components."""
        self.logger.info("=" * 60)
        self.logger.info("HFT-Lite Starting Up")
        self.logger.info("=" * 60)
        
        # Validate configuration
        errors = self.config.validate()
        for error in errors:
            if error.startswith("WARNING"):
                self.logger.warning(error)
            else:
                self.logger.error(f"Config error: {error}")
        
        if any(not e.startswith("WARNING") for e in errors):
            raise RuntimeError("Configuration validation failed")
        
        # Create event queues
        self.event_bus.create_queue(
            "ticks",
            max_size=self.config.queue_max_size,
            policy=BackpressurePolicy.DROP_OLDEST
        )
        self.event_bus.create_queue(
            "signals",
            max_size=1000,
            policy=BackpressurePolicy.DROP_OLDEST
        )
        self.event_bus.create_queue(
            "orders",
            max_size=1000,
            policy=BackpressurePolicy.BLOCK
        )
        
        self.logger.info("Event queues created")
        
        # TODO: Initialize gateways (Step 2 & 3)
        # self._gateways.append(KalshiGateway(self.config.kalshi))
        # self._gateways.append(IBKRGateway(self.config.ibkr))
        
        # TODO: Initialize order book (Step 5)
        # self._order_book = CentralOrderBook()
        
        # TODO: Initialize strategy (Step 6)
        # self._strategy = ArbitrageEngine(self._order_book, self.config.risk)
        
        # TODO: Initialize execution (Step 6)
        # self._execution_manager = ExecutionManager(self._gateways)
        
        # Log startup state
        self.logger.info(f"Paper trading: {self.config.paper_trading}")
        self.logger.info(f"Trading enabled: {self.config.enable_trading}")
        self.logger.info(f"Symbols configured: {len(self.config.symbols)}")
        
        self.logger.info("Startup complete")
    
    async def run(self) -> None:
        """Main event loop."""
        self.logger.info("Entering main event loop")
        
        # TODO: Start gateway connections
        # for gateway in self._gateways:
        #     task = asyncio.create_task(gateway.connect())
        #     self._tasks.append(task)
        
        # TODO: Start order book consumer
        # task = asyncio.create_task(self._order_book.run())
        # self._tasks.append(task)
        
        # TODO: Start strategy loop
        # task = asyncio.create_task(self._strategy.run())
        # self._tasks.append(task)
        
        # Placeholder: Just wait for shutdown signal
        self.logger.info("System ready - waiting for shutdown signal")
        await self._shutdown_event.wait()
    
    async def shutdown(self) -> None:
        """Graceful shutdown procedure."""
        self.logger.info("=" * 60)
        self.logger.info("Initiating Shutdown")
        self.logger.info("=" * 60)
        
        # Signal shutdown
        self._shutdown_event.set()
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        # Disconnect gateways
        for gateway in self._gateways:
            try:
                await gateway.disconnect()
            except Exception as e:
                self.logger.error(f"Error disconnecting gateway: {e}")
        
        # Log final stats
        stats = self.event_bus.get_all_stats()
        for name, stat in stats.items():
            self.logger.info(
                f"Queue '{name}': enqueued={stat.total_enqueued}, "
                f"dequeued={stat.total_dequeued}, dropped={stat.total_dropped}"
            )
        
        self.logger.info("Shutdown complete")
    
    def request_shutdown(self) -> None:
        """Request graceful shutdown (called by signal handler)."""
        self._shutdown_event.set()


def setup_signal_handlers(app: Application, loop: asyncio.AbstractEventLoop) -> None:
    """Configure signal handlers for graceful shutdown."""
    
    def signal_handler(sig: signal.Signals) -> None:
        app.logger.info(f"Received signal {sig.name}")
        app.request_shutdown()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler, sig)


async def main(config_path: Optional[Path] = None) -> int:
    """
    Application main entry point.
    
    Args:
        config_path: Path to configuration file
        
    Returns:
        Exit code (0 for success)
    """
    # Load configuration
    config = SystemConfig.load(config_path)
    
    # Setup logging
    setup_logging(
        level=config.logging.level,
        file_path=config.logging.file_path,
        max_file_size_mb=config.logging.max_file_size_mb,
        backup_count=config.logging.backup_count,
    )
    
    logger = get_logger("hft_lite.main")
    
    # Create application
    app = Application(config)
    
    # Setup signal handlers
    loop = asyncio.get_running_loop()
    setup_signal_handlers(app, loop)
    
    try:
        await app.startup()
        await app.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        return 1
    finally:
        await app.shutdown()
    
    return 0


def cli() -> None:
    """Command-line interface entry point."""
    parser = argparse.ArgumentParser(
        description="HFT-Lite: Event Prediction Market Arbitrage System"
    )
    parser.add_argument(
        "-c", "--config",
        type=Path,
        default=Path("config/config.yaml"),
        help="Path to configuration file"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate configuration and exit"
    )
    
    args = parser.parse_args()
    
    if args.validate:
        config = SystemConfig.load(args.config)
        errors = config.validate()
        if errors:
            print("Configuration errors:")
            for error in errors:
                print(f"  - {error}")
            sys.exit(1)
        else:
            print("Configuration is valid")
            sys.exit(0)
    
    exit_code = asyncio.run(main(args.config))
    sys.exit(exit_code)


if __name__ == "__main__":
    cli()
