"""
Interactive Brokers client via ib_insync.
"""
import asyncio
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from ib_insync import IB, Contract, Ticker, LimitOrder, Trade, OrderStatus

from hft_engine.core.normalized_tick import NormalizedTick
from hft_engine.normalizers.ibkr_normalizer import IBKRNormalizer


@dataclass
class IBKRConfig:
    host: str = "127.0.0.1"
    port: int = 4001
    client_id: int = 1


class IBKROrderStatus(Enum):
    PENDING = "PendingSubmit"
    SUBMITTED = "Submitted"
    FILLED = "Filled"
    CANCELLED = "Cancelled"
    INACTIVE = "Inactive"


@dataclass
class IBKROrder:
    """IBKR order result."""
    order_id: int
    con_id: int
    action: str  # "BUY"
    quantity: int
    limit_price: Decimal
    status: IBKROrderStatus
    filled_quantity: int
    avg_fill_price: Decimal | None
    
    @property
    def is_filled(self) -> bool:
        return self.status == IBKROrderStatus.FILLED
    
    @property
    def is_open(self) -> bool:
        return self.status in (IBKROrderStatus.PENDING, IBKROrderStatus.SUBMITTED)


class IBKRClient:
    """Client for Interactive Brokers TWS/Gateway API."""
    
    def __init__(self, config: IBKRConfig):
        self.config = config
        self.ib = IB()
        self._tick_queue: asyncio.Queue[dict] = asyncio.Queue()
        self._subscriptions: dict[int, Contract] = {}
        self._normalizer = IBKRNormalizer()
        self._trades: dict[int, Trade] = {}  # order_id -> Trade
    
    @property
    def is_connected(self) -> bool:
        return self.ib.isConnected()
    
    async def connect(self) -> None:
        """Connect to TWS/Gateway."""
        if self.is_connected:
            return
        await self.ib.connectAsync(
            self.config.host,
            self.config.port,
            clientId=self.config.client_id
        )
        self.ib.pendingTickersEvent += self._on_pending_tickers
    
    async def disconnect(self) -> None:
        """Disconnect from TWS/Gateway."""
        try:
            if self.is_connected:
                self.ib.pendingTickersEvent -= self._on_pending_tickers
                self.ib.disconnect()
        except Exception:
            pass  # Ignore cleanup errors
    
    async def subscribe(self, con_id: int, exchange: str = "FORECASTX") -> None:
        """Subscribe to market data for a contract."""
        contract = Contract(conId=con_id, exchange=exchange)
        await self.ib.qualifyContractsAsync(contract)
        self.ib.reqMktData(contract)
        self._subscriptions[con_id] = contract
    
    def unsubscribe(self, con_id: int) -> None:
        """Unsubscribe from market data."""
        if con_id in self._subscriptions:
            contract = self._subscriptions.pop(con_id)
            self.ib.cancelMktData(contract)
    
    def _on_pending_tickers(self, tickers: list[Ticker]) -> None:
        """Callback when any ticker updates."""
        for ticker in tickers:
            if ticker.contract is None:
                continue
            tick_data = {
                "type": "tick",
                "con_id": ticker.contract.conId,
                "symbol": ticker.contract.symbol,
                "bid": ticker.bid,
                "bid_size": ticker.bidSize,
                "ask": ticker.ask,
                "ask_size": ticker.askSize,
                "last": ticker.last,
                "last_size": ticker.lastSize,
                "time": ticker.time,
            }
            try:
                self._tick_queue.put_nowait(tick_data)
            except asyncio.QueueFull:
                pass
    
    async def receive(self, timeout: float = 5.0) -> dict:
        """Receive next tick. Blocks until data arrives or timeout."""
        deadline = asyncio.get_event_loop().time() + timeout
        while self._tick_queue.empty():
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError()
            await asyncio.sleep(0.1)
        return self._tick_queue.get_nowait()

    async def receive_normalized(self, timeout: float = 5.0) -> NormalizedTick:
        """Receive and normalize a single tick message."""
        while True:
            raw = await self.receive(timeout=timeout)
            tick = self._normalizer.normalize(raw)
            if tick is not None:
                return tick
    
    # ==================== ORDER METHODS ====================
    
    async def place_order(
        self,
        con_id: int,
        quantity: int,
        limit_price: Decimal,
        exchange: str = "FORECASTX",
    ) -> IBKROrder:
        """
        Place a limit buy order on ForecastEx.
        
        Note: ForecastEx only allows BUY orders. To close a position,
        buy the opposing contract.
        
        Args:
            con_id: Contract ID
            quantity: Number of contracts
            limit_price: Limit price (0.00 - 1.00)
            exchange: Exchange (default FORECASTX)
        
        Returns:
            IBKROrder with order details
        """
        # Get or create contract
        if con_id in self._subscriptions:
            contract = self._subscriptions[con_id]
        else:
            contract = Contract(conId=con_id, exchange=exchange)
            await self.ib.qualifyContractsAsync(contract)
        
        # Create limit order (ForecastEx only allows BUY)
        order = LimitOrder(
            action="BUY",
            totalQuantity=quantity,
            lmtPrice=float(limit_price),
            tif="GTC",  # Good-til-cancelled
        )
        
        # Place order
        trade = self.ib.placeOrder(contract, order)
        self._trades[trade.order.orderId] = trade
        
        # Wait briefly for submission
        await asyncio.sleep(0.1)
        
        return self._trade_to_order(trade)
    
    async def cancel_order(self, order_id: int) -> IBKROrder:
        """
        Cancel an open order.
        
        Args:
            order_id: The order ID to cancel
        
        Returns:
            IBKROrder with updated status
        """
        if order_id not in self._trades:
            raise ValueError(f"Unknown order ID: {order_id}")
        
        trade = self._trades[order_id]
        self.ib.cancelOrder(trade.order)
        
        # Wait for cancellation
        await asyncio.sleep(0.5)
        
        return self._trade_to_order(trade)
    
    async def get_order(self, order_id: int) -> IBKROrder:
        """
        Get order status.
        
        Args:
            order_id: The order ID to query
        
        Returns:
            IBKROrder with current status
        """
        if order_id not in self._trades:
            raise ValueError(f"Unknown order ID: {order_id}")
        
        trade = self._trades[order_id]
        return self._trade_to_order(trade)
    
    async def wait_for_fill(
        self,
        order_id: int,
        timeout: float = 10.0,
        poll_interval: float = 0.5,
    ) -> IBKROrder:
        """
        Wait for an order to fill.
        
        Args:
            order_id: The order ID to wait for
            timeout: Max seconds to wait
            poll_interval: Seconds between status checks
        
        Returns:
            IBKROrder with final status
        """
        if order_id not in self._trades:
            raise ValueError(f"Unknown order ID: {order_id}")
        
        trade = self._trades[order_id]
        deadline = asyncio.get_event_loop().time() + timeout
        
        while asyncio.get_event_loop().time() < deadline:
            order = self._trade_to_order(trade)
            
            if order.is_filled:
                return order
            
            if not order.is_open:
                return order  # Cancelled or inactive
            
            await asyncio.sleep(poll_interval)
        
        # Timeout - return current state
        return self._trade_to_order(trade)
    
    def _trade_to_order(self, trade: Trade) -> IBKROrder:
        """Convert ib_insync Trade to IBKROrder."""
        status_map = {
            "PendingSubmit": IBKROrderStatus.PENDING,
            "PreSubmitted": IBKROrderStatus.PENDING,
            "Submitted": IBKROrderStatus.SUBMITTED,
            "Filled": IBKROrderStatus.FILLED,
            "Cancelled": IBKROrderStatus.CANCELLED,
            "Inactive": IBKROrderStatus.INACTIVE,
        }
        
        status_str = trade.orderStatus.status
        status = status_map.get(status_str, IBKROrderStatus.INACTIVE)
        
        avg_price = None
        if trade.orderStatus.avgFillPrice:
            avg_price = Decimal(str(trade.orderStatus.avgFillPrice))
        
        return IBKROrder(
            order_id=trade.order.orderId,
            con_id=trade.contract.conId,
            action=trade.order.action,
            quantity=int(trade.order.totalQuantity),
            limit_price=Decimal(str(trade.order.lmtPrice)),
            status=status,
            filled_quantity=int(trade.orderStatus.filled),
            avg_fill_price=avg_price,
        )
    
    async def get_balance(self) -> Decimal:
        """
        Get available cash balance.
        
        Returns:
            Available cash in dollars
        """
        account_values = self.ib.accountValues()
        
        for av in account_values:
            if av.tag == "AvailableFunds" and av.currency == "USD":
                return Decimal(av.value)
        
        # Fallback to CashBalance
        for av in account_values:
            if av.tag == "CashBalance" and av.currency == "USD":
                return Decimal(av.value)
        
        return Decimal("0")
    
    async def get_positions(self) -> list[dict]:
        """
        Get open positions.
        
        Returns:
            List of position dictionaries
        """
        positions = self.ib.positions()
        
        result = []
        for pos in positions:
            result.append({
                "con_id": pos.contract.conId,
                "symbol": pos.contract.symbol,
                "quantity": pos.position,
                "avg_cost": pos.avgCost,
            })
        
        return result
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()