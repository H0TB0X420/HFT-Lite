"""
Arbitrage Monitor Orchestrator.

Connects to both exchanges, subscribes to all mapped contracts,
and monitors for arbitrage opportunities.
"""
import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from ..config.loader import SymbolConfig
from ..config.execution_loader import ExecutionConfig
from ..core.order_book import CentralOrderBook
from ..core.arbitrage import ArbitrageDetector, ArbitrageOpportunity
from ..core.account_state import CapitalManager
from ..core.normalized_tick import NormalizedTick, Exchange
from ..gateways.kalshi_websocket import KalshiWebSocket, KalshiConfig
from ..gateways.ibkr_client import IBKRClient, IBKRConfig
from ..monitor.logger import SpreadLogger
from ..normalizers.symbol_map import add_mapping
from ..core.executor import OrderExecutor, ExecutionResult
from ..gateways.kalshi_rest import KalshiRestClient
from ..core.database import Database



@dataclass
class IBKRPartialTick:
    """Holds partial IBKR data until we have both YES and NO."""
    yes_ask: Decimal | None = None
    yes_ask_size: int = 0
    no_ask: Decimal | None = None
    no_ask_size: int = 0
    timestamp_ns: int = 0
    
    @property
    def is_complete(self) -> bool:
        return self.yes_ask is not None and self.no_ask is not None
    
    def is_stale(self, max_age_seconds: float) -> bool:
        """Check if tick is older than max_age_seconds."""
        if self.timestamp_ns == 0:
            return True
        age_ns = time.time_ns() - self.timestamp_ns
        return age_ns > (max_age_seconds * 1_000_000_000)


@dataclass
class KalshiTickCache:
    """Cache Kalshi tick with staleness tracking."""
    tick: NormalizedTick | None = None
    timestamp_ns: int = 0
    
    def update(self, tick: NormalizedTick) -> None:
        self.tick = tick
        self.timestamp_ns = time.time_ns()
    
    def is_stale(self, max_age_seconds: float) -> bool:
        if self.tick is None or self.timestamp_ns == 0:
            return True
        age_ns = time.time_ns() - self.timestamp_ns
        return age_ns > (max_age_seconds * 1_000_000_000)


class ArbitrageMonitor:
    """
    Main arbitrage monitoring orchestrator.
    
    Connects to Kalshi and IBKR, subscribes to mapped contracts,
    and logs spreads + opportunities.
    """
    
    def __init__(
        self,
        kalshi_config: KalshiConfig,
        ibkr_config: IBKRConfig,
        symbol_config: SymbolConfig | None = None,
        execution_config: ExecutionConfig | None = None,
        log_dir: str = "logs",
        spread_log_interval: float = 30.0,
        initial_kalshi_balance: Decimal = Decimal("0"),
        initial_ibkr_balance: Decimal = Decimal("0"),
    ):
        self._kalshi_config = kalshi_config
        self._ibkr_config = ibkr_config
        self._symbol_config = symbol_config or SymbolConfig()
        self._execution_config = execution_config or ExecutionConfig.load()
        self._spread_log_interval = spread_log_interval
        
        # Capital management
        self._capital = CapitalManager(
            max_capital_per_market=self._execution_config.max_capital_per_market,
            max_contracts_per_event=self._execution_config.max_contracts_per_event,
        )
        self._capital.set_balances(initial_kalshi_balance, initial_ibkr_balance)
        
        # Components
        self._db = Database(db_path=Path(log_dir) / "hft_engine.db")
        self._logger = SpreadLogger(database=self._db)
        self._detector = ArbitrageDetector(
            min_profit=self._execution_config.min_net_profit,
        )
        self._order_book = CentralOrderBook(
            detector=self._detector,
            on_opportunity=self._handle_opportunity,
        )

        # Staleness tracking
        self._kalshi_cache: dict[str, KalshiTickCache] = {}
        self._ibkr_partials: dict[str, IBKRPartialTick] = {}
        
        # Gateways
        self._kalshi = KalshiWebSocket(self._kalshi_config)
        self._ibkr = IBKRClient(self._ibkr_config)
        
        # Control
        self._running = False
        self._tasks: list[asyncio.Task] = []
        
        # Stats
        self._opportunities_detected = 0
        self._opportunities_valid = 0
        self._opportunities_stale = 0
        
        self._kalshi_rest = KalshiRestClient(self._kalshi_config)
        self._executor = OrderExecutor(
            kalshi_client=self._kalshi_rest,
            ibkr_client=self._ibkr,
            capital_manager=self._capital,
            symbol_config=self._symbol_config,
        )

        # Register symbol mappings
        self._register_mappings()
    
    def _register_mappings(self) -> None:
        """Register all symbol mappings for normalizers."""
        for mapping in self._symbol_config.mappings:
            add_mapping(
                mapping.kalshi_ticker,
                mapping.ibkr_yes_conid,
                mapping.unified_symbol,
                mapping.ibkr_no_conid,
            )
    
    def _handle_opportunity(self, opp: ArbitrageOpportunity) -> None:
        """Handle detected opportunity with validation."""
        self._opportunities_detected += 1
        
        # Check staleness
        kalshi_cache = self._kalshi_cache.get(opp.symbol)
        ibkr_partial = self._ibkr_partials.get(opp.symbol)
        
        max_stale = self._execution_config.max_stale_seconds
        
        if kalshi_cache is None or kalshi_cache.is_stale(max_stale):
            self._opportunities_stale += 1
            return
        
        if ibkr_partial is None or ibkr_partial.is_stale(max_stale):
            self._opportunities_stale += 1
            return
        
        # Calculate max quantity
        max_qty = self._capital.calculate_max_quantity(
            symbol=opp.symbol,
            kalshi_side=opp.kalshi_side,
            kalshi_price=opp.kalshi_price,
            ibkr_side=opp.ibkr_side,
            ibkr_price=opp.ibkr_price,
        )
        
        if max_qty <= 0:
            return
        
        # Validate
        is_valid, reason = self._capital.validate_opportunity(
            symbol=opp.symbol,
            kalshi_side=opp.kalshi_side,
            kalshi_price=opp.kalshi_price,
            ibkr_side=opp.ibkr_side,
            ibkr_price=opp.ibkr_price,
            quantity=max_qty,
        )
        
        if not is_valid:
            return
        
        # Recalculate opportunity with actual quantity
        scaled_opp = self._scale_opportunity(opp, max_qty)
        
        # Check if still profitable after fees at scale
        if scaled_opp.net_profit <= Decimal("0"):
            return
        
        self._opportunities_valid += 1
    
        # Execute or log based on mode
        if self._execution_config.mode == "live":
            asyncio.create_task(self._execute_opportunity(scaled_opp, max_qty))
        else:
            asyncio.create_task(self._log_opportunity_only(scaled_opp))
            print(f"  [LOGGING] {scaled_opp.symbol}: {max_qty} contracts @ ${scaled_opp.total_cost:.2f} | "
                f"Gross ${scaled_opp.gross_profit:.2f} - Fees ${scaled_opp.total_fees:.2f} = Net ${scaled_opp.net_profit:.2f}")

    async def _log_opportunity_only(self, opp: ArbitrageOpportunity) -> None:
        """Log opportunity without execution."""
        await self._logger.log_opportunity(opp, executed=False)

    async def _execute_opportunity(self, opp: ArbitrageOpportunity, quantity: int) -> None:
        """Execute opportunity and log result."""
        result = await self._executor.execute(opp, quantity)
        
        # Log opportunity with execution status
        await self._logger.log_opportunity(opp, executed=result.success)
        
        # Log execution details
        await self._logger.log_execution(result)
        
        # Console output
        self._log_execution(result)


    def _scale_opportunity(self, opp: ArbitrageOpportunity, quantity: int) -> ArbitrageOpportunity:
        """Recalculate opportunity for given quantity with accurate fees."""
        from ..core.fee_model import KALSHI_FEES, IBKR_FEES
        
        total_cost = (opp.kalshi_price + opp.ibkr_price) * quantity
        gross_profit = (Decimal("1.00") - opp.kalshi_price - opp.ibkr_price) * quantity
        
        kalshi_fee = KALSHI_FEES.taker_fee(opp.kalshi_price, quantity)
        ibkr_fee = IBKR_FEES.fee(quantity)
        total_fees = kalshi_fee + ibkr_fee
        
        slippage = self._detector.slippage_buffer * quantity
        net_profit = gross_profit - total_fees - slippage
        
        return ArbitrageOpportunity(
            symbol=opp.symbol,
            side=opp.side,
            kalshi_side=opp.kalshi_side,
            kalshi_price=opp.kalshi_price,
            ibkr_side=opp.ibkr_side,
            ibkr_price=opp.ibkr_price,
            total_cost=total_cost,
            gross_profit=gross_profit,
            kalshi_fee=kalshi_fee,
            ibkr_fee=ibkr_fee,
            total_fees=total_fees,
            slippage_buffer=slippage,
            net_profit=net_profit,
            timestamp_ns=opp.timestamp_ns,
        )
    
    def _log_execution(self, result: ExecutionResult) -> None:
        """Log execution result."""
        if result.success:
            print(f"  ✅ EXECUTED: {result.symbol} × {result.quantity}")
            print(f"     Kalshi {result.kalshi_side} @ ${result.kalshi_fill_price} (order {result.kalshi_order_id})")
            print(f"     IBKR {result.ibkr_side} @ ${result.ibkr_fill_price} (order {result.ibkr_order_id})")
            print(f"     Net profit: ${result.net_profit:.2f}")
        elif result.rolled_back:
            print(f"  ⚠️ ROLLED BACK: {result.symbol}")
            print(f"     Error: {result.error}")
            print(f"     Rollback: {result.rollback_details}")
        else:
            print(f"  ❌ FAILED: {result.symbol}")
            print(f"     Error: {result.error}")
    
    async def start(self, duration_seconds: float | None = None) -> None:
        """Start monitoring."""
        print(f"\n{'='*60}")
        print("ARBITRAGE MONITOR STARTING")
        print(f"{'='*60}")
        print(f"Mode: {self._execution_config.mode.upper()}")
        print(f"Events: {len(self._symbol_config.mappings)}")
        print(f"IBKR subscriptions: {len(self._symbol_config.ibkr_all_conids)} (YES + NO)")
        print(f"Max capital per market: ${self._execution_config.max_capital_per_market}")
        print(f"Max contracts per event: {self._execution_config.max_contracts_per_event}")
        print(f"Max stale seconds: {self._execution_config.max_stale_seconds}")
        print(f"Kalshi balance: ${self._capital.kalshi.cash_available}")
        print(f"IBKR balance: ${self._capital.ibkr.cash_available}")
        print(f"Spread log interval: {self._spread_log_interval}s")
        print(f"{'='*60}\n")
        
        self._running = True
        
        try:
            await self._db.connect()
            await self._connect()
            await self._subscribe_all()
            
            self._tasks = [
                asyncio.create_task(self._process_kalshi(), name="kalshi"),
                asyncio.create_task(self._process_ibkr(), name="ibkr"),
                asyncio.create_task(self._log_spreads_periodic(), name="logger"),
            ]
            
            if duration_seconds:
                self._tasks.append(
                    asyncio.create_task(self._timeout(duration_seconds), name="timeout")
                )
            
            await asyncio.gather(*self._tasks, return_exceptions=True)
            
        except asyncio.CancelledError:
            print("\nMonitor cancelled.")
        except Exception as e:
            print(f"\nMonitor error: {e}")
            raise
        finally:
            await self.stop()
    
    async def stop(self) -> None:
        """Stop monitoring and cleanup."""
        print("\nStopping monitor...")
        self._running = False
        
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        try:
            await self._kalshi.disconnect()
        except Exception:
            pass
        
        try:
            await self._kalshi_rest.disconnect()
        except Exception:
            pass
        
        try:
            await self._ibkr.disconnect()
        except Exception:
            pass
        
        # Print P&L summary
        pnl = await self._db.get_pnl_summary(session_id=self._logger.session_id)
        
        print(f"\n{'='*60}")
        print("SESSION SUMMARY")
        print(f"{'='*60}")
        print(f"Session ID:           {self._logger.session_id}")
        print(f"Opportunities:        {self._opportunities_detected} detected, {self._opportunities_valid} valid, {self._opportunities_stale} stale")
        print(f"Executed:             {pnl.total_executed}")
        print(f"Total Cost:           ${pnl.total_cost:.2f}")
        print(f"Total Fees:           ${pnl.total_fees:.2f}")
        print(f"Net Profit:           ${pnl.net_profit:.2f}")
        print(f"{'='*60}")
        print(f"\nDatabase: {self._db._db_path}")
        
        await self._db.close()

    async def _connect(self) -> None:
        """Connect to both exchanges."""
        print("Connecting to Kalshi WebSocket...")
        await self._kalshi.connect()
        print("  ✓ Kalshi WebSocket connected")
        
        print("Connecting to Kalshi REST...")
        await self._kalshi_rest.connect()
        print("  ✓ Kalshi REST connected")
        
        print("Connecting to IBKR...")
        await self._ibkr.connect()
        print("  ✓ IBKR connected")
    
    async def _subscribe_all(self) -> None:
        """Subscribe to all mapped contracts on both exchanges."""
        print("\nSubscribing to contracts...")
        
        kalshi_tickers = [m.kalshi_ticker for m in self._symbol_config.mappings]
        await self._kalshi.subscribe_orderbook(kalshi_tickers)
        for ticker in kalshi_tickers:
            print(f"  ✓ Kalshi: {ticker}")
        
        for mapping in self._symbol_config.mappings:
            await self._ibkr.subscribe(mapping.ibkr_yes_conid)
            print(f"  ✓ IBKR YES: {mapping.ibkr_yes_conid} ({mapping.unified_symbol})")
            await asyncio.sleep(0.1)
            
            await self._ibkr.subscribe(mapping.ibkr_no_conid)
            print(f"  ✓ IBKR NO:  {mapping.ibkr_no_conid} ({mapping.unified_symbol})")
            await asyncio.sleep(0.1)
        
        print(f"\nSubscribed to {len(self._symbol_config.mappings)} events")
    
    async def _process_kalshi(self) -> None:
        """Process Kalshi tick stream."""
        print("\nKalshi stream started")
        
        while self._running:
            try:
                tick = await self._kalshi.receive_normalized()
                
                # Update cache with staleness tracking
                if tick.symbol not in self._kalshi_cache:
                    self._kalshi_cache[tick.symbol] = KalshiTickCache()
                self._kalshi_cache[tick.symbol].update(tick)
                
                await self._order_book.update(tick)
                
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Kalshi error: {e}")
                await asyncio.sleep(1)
    
    async def _process_ibkr(self) -> None:
        """Process IBKR tick stream, combining YES and NO into single ticks."""
        print("IBKR stream started")
        
        while self._running:
            try:
                raw = await self._ibkr.receive(timeout=5.0)
                
                if raw.get("type") != "tick":
                    continue
                
                con_id = raw.get("con_id")
                if not con_id:
                    continue
                
                mapping, side = self._symbol_config.by_ibkr_conid(con_id)
                if not mapping or not side:
                    continue
                
                symbol = mapping.unified_symbol
                
                if symbol not in self._ibkr_partials:
                    self._ibkr_partials[symbol] = IBKRPartialTick()
                
                partial = self._ibkr_partials[symbol]
                partial.timestamp_ns = time.time_ns()
                
                ask = raw.get("ask")
                if ask is None or (isinstance(ask, float) and (ask < 0 or ask != ask)):
                    continue
                
                ask_decimal = Decimal(str(ask))
                ask_size = int(raw.get("ask_size", 0) or 0)
                
                if side == "YES":
                    partial.yes_ask = ask_decimal
                    partial.yes_ask_size = ask_size
                else:
                    partial.no_ask = ask_decimal
                    partial.no_ask_size = ask_size
                
                if partial.is_complete:
                    tick = NormalizedTick(
                        exchange=Exchange.IBKR,
                        symbol=symbol,
                        timestamp_exchange=partial.timestamp_ns,
                        timestamp_local=time.time_ns(),
                        yes_ask=partial.yes_ask, # type: ignore
                        no_ask=partial.no_ask, # type: ignore
                        yes_ask_size=partial.yes_ask_size,
                        no_ask_size=partial.no_ask_size,
                        last=None,
                        last_size=None,
                    )
                    await self._order_book.update(tick)
                
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"IBKR error: {e}")
                await asyncio.sleep(1)
    
    async def _log_spreads_periodic(self) -> None:
        """Periodically log spread snapshots."""
        while self._running:
            await asyncio.sleep(self._spread_log_interval)
            
            if self._running:
                await self._logger.log_spreads(self._order_book)
                
                books = self._order_book.get_all_books()
                active = sum(1 for b in books.values() if b.has_both)
                print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] "
                    f"Logged {len(books)} symbols, {active} with both sides | "
                    f"Opps: {self._opportunities_detected} detected, {self._opportunities_valid} valid, {self._opportunities_stale} stale")
    
    async def _timeout(self, seconds: float) -> None:
        """Stop after duration."""
        await asyncio.sleep(seconds)
        print(f"\nDuration ({seconds}s) reached.")
        self._running = False
        