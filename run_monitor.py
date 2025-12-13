#!/usr/bin/env python
"""
Arbitrage Monitor CLI

Usage:
    python run_monitor.py                          # Run until Ctrl+C
    python run_monitor.py --duration 3600          # Run for 1 hour
    python run_monitor.py --duration 86400         # Run for 24 hours
    python run_monitor.py --log-interval 60        # Log spreads every 60s
"""
import argparse
import asyncio
import os
import signal
from dotenv import load_dotenv
from decimal import Decimal


from hft_engine.config.loader import SymbolConfig
from hft_engine.gateways.kalshi_websocket import KalshiConfig, load_private_key
from hft_engine.gateways.ibkr_client import IBKRConfig
from hft_engine.monitor.arbitrage_monitor import ArbitrageMonitor
from hft_engine.config.execution_loader import ExecutionConfig



def parse_args():
    parser = argparse.ArgumentParser(description="Arbitrage Monitor")
    
    # Duration
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Run duration in seconds (default: run until Ctrl+C)",
    )
    
    # Logging
    parser.add_argument(
        "--log-interval",
        type=float,
        default=30.0,
        help="Spread log interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default="logs",
        help="Output directory for logs (default: logs)",
    )
    
    # IBKR config
    parser.add_argument(
        "--ibkr-host",
        type=str,
        default="127.0.0.1",
        help="IBKR Gateway host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--ibkr-port",
        type=int,
        default=4001,
        help="IBKR Gateway port (default: 4001)",
    )
    parser.add_argument(
        "--ibkr-client-id",
        type=int,
        default=1,
        help="IBKR client ID (default: 1)",
    )
    
    # Symbol config
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to symbol_mappings.json (default: config/symbol_mappings.json)",
    )

    parser.add_argument(
    "--kalshi-balance",
    type=float,
    default=0.0,
    help="Initial Kalshi cash balance (default: 0)",
    )

    parser.add_argument(
        "--ibkr-balance",
        type=float,
        default=0.0,
        help="Initial IBKR cash balance (default: 0)",
    )

    parser.add_argument(
        "--execution-config",
        type=str,
        default=None,
        help="Path to execution_config.json",
    )
    
    return parser.parse_args()


async def main():
    args = parse_args()
    load_dotenv()
    key_id = os.environ.get("KALSHI_KEY_ID")
    key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
    
    assert key_id is not None, "KALSHI_KEY_ID not set"
    assert key_path is not None, "KALSHI_PRIVATE_KEY_PATH not set"
    private_key = load_private_key(key_path)
    assert private_key is not None, "Failed to load private key"

    kalshi_config = KalshiConfig(
        key_id=key_id,
        private_key=private_key,
    )
    
    ibkr_config = IBKRConfig(
        host=args.ibkr_host,
        port=args.ibkr_port,
        client_id=args.ibkr_client_id,
    )
    
    symbol_config = SymbolConfig(args.config) if args.config else SymbolConfig()
    
    execution_config = ExecutionConfig.load(args.execution_config) if args.execution_config else ExecutionConfig.load()

    monitor = ArbitrageMonitor(
        kalshi_config=kalshi_config,
        ibkr_config=ibkr_config,
        symbol_config=symbol_config,
        execution_config=execution_config,
        log_dir=args.log_dir,
        spread_log_interval=args.log_interval,
        initial_kalshi_balance=Decimal(str(args.kalshi_balance)),
        initial_ibkr_balance=Decimal(str(args.ibkr_balance)),
    )
    
    # Handle Ctrl+C
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        print("\nReceived interrupt signal...")
        asyncio.create_task(monitor.stop())
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
    # Run
    await monitor.start(duration_seconds=args.duration)


if __name__ == "__main__":
    asyncio.run(main())
