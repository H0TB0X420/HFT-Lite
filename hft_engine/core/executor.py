"""
Order executor for atomic arbitrage execution across exchanges.
"""
import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime

from .arbitrage import ArbitrageOpportunity
from .account_state import CapitalManager
from .fee_model import KALSHI_FEES, IBKR_FEES
from ..gateways.kalshi_rest import KalshiRestClient, OrderSide as KalshiSide
from ..gateways.ibkr_client import IBKRClient
from ..config.loader import SymbolConfig


@dataclass
class ExecutionResult:
    """Result of an execution attempt."""
    success: bool
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # What we attempted
    symbol: str = ""
    quantity: int = 0
    
    # Kalshi leg
    kalshi_filled: bool = False
    kalshi_order_id: str | None = None
    kalshi_side: str = ""
    kalshi_limit_price: Decimal = Decimal("0")
    kalshi_fill_price: Decimal | None = None
    kalshi_fill_quantity: int = 0
    
    # IBKR leg
    ibkr_filled: bool = False
    ibkr_order_id: int | None = None
    ibkr_side: str = ""
    ibkr_con_id: int = 0
    ibkr_limit_price: Decimal = Decimal("0")
    ibkr_fill_price: Decimal | None = None
    ibkr_fill_quantity: int = 0
    
    # Financials
    total_cost: Decimal = Decimal("0")
    expected_payout: Decimal = Decimal("0")
    actual_fees: Decimal = Decimal("0")
    net_profit: Decimal = Decimal("0")
    
    # Error handling
    error: str | None = None
    rolled_back: bool = False
    rollback_details: str | None = None


class OrderExecutor:
    """
    Executes arbitrage trades across Kalshi and IBKR.
    
    Sequence:
    1. Reserve capital on both exchanges
    2. Place Kalshi order, wait for fill
    3. Place IBKR order, wait for fill
    4. If IBKR fails, rollback by closing Kalshi position
    """
    
    def __init__(
        self,
        kalshi_client: KalshiRestClient,
        ibkr_client: IBKRClient,
        capital_manager: CapitalManager,
        symbol_config: SymbolConfig,
        order_timeout: float = 10.0,
        poll_interval: float = 0.5,
    ):
        self._kalshi = kalshi_client
        self._ibkr = ibkr_client
        self._capital = capital_manager
        self._symbols = symbol_config
        self._timeout = order_timeout
        self._poll_interval = poll_interval
    
    async def execute(
        self,
        opportunity: ArbitrageOpportunity,
        quantity: int,
    ) -> ExecutionResult:
        """
        Execute an arbitrage opportunity.
        
        Args:
            opportunity: The validated opportunity
            quantity: Number of contracts to trade
        
        Returns:
            ExecutionResult with outcome details
        """
        result = ExecutionResult(
            success=False,
            symbol=opportunity.symbol,
            quantity=quantity,
            kalshi_side=opportunity.kalshi_side,
            kalshi_limit_price=opportunity.kalshi_price,
            ibkr_side=opportunity.ibkr_side,
            ibkr_limit_price=opportunity.ibkr_price,
            expected_payout=Decimal(quantity),  # $1.00 per contract pair
        )
        
        # Get IBKR conId for the side we're buying
        mapping = self._symbols.by_unified(opportunity.symbol)
        if not mapping:
            result.error = f"Unknown symbol: {opportunity.symbol}"
            return result
        
        if opportunity.ibkr_side == "YES":
            result.ibkr_con_id = mapping.ibkr_yes_conid
        else:
            result.ibkr_con_id = mapping.ibkr_no_conid
        
        # Calculate costs
        kalshi_cost = opportunity.kalshi_price * quantity
        ibkr_cost = opportunity.ibkr_price * quantity
        result.total_cost = kalshi_cost + ibkr_cost
        
        # 1. Reserve capital
        if not self._capital.kalshi.reserve(kalshi_cost):
            result.error = f"Insufficient Kalshi capital: need ${kalshi_cost}"
            return result
        
        if not self._capital.ibkr.reserve(ibkr_cost):
            self._capital.kalshi.release(kalshi_cost)
            result.error = f"Insufficient IBKR capital: need ${ibkr_cost}"
            return result
        
        try:
            # 2. Place Kalshi order
            kalshi_result = await self._execute_kalshi(
                ticker=mapping.kalshi_ticker,
                side=opportunity.kalshi_side,
                quantity=quantity,
                price=opportunity.kalshi_price,
            )
            
            result.kalshi_order_id = kalshi_result.get("order_id")
            result.kalshi_filled = kalshi_result.get("filled", False)
            result.kalshi_fill_quantity = kalshi_result.get("fill_quantity", 0)
            result.kalshi_fill_price = kalshi_result.get("fill_price")
            
            if not result.kalshi_filled:
                # Kalshi failed - release all capital
                self._capital.kalshi.release(kalshi_cost)
                self._capital.ibkr.release(ibkr_cost)
                result.error = kalshi_result.get("error", "Kalshi order not filled")
                return result
            
            # 3. Place IBKR order
            ibkr_result = await self._execute_ibkr(
                con_id=result.ibkr_con_id,
                quantity=quantity,
                price=opportunity.ibkr_price,
            )
            
            result.ibkr_order_id = ibkr_result.get("order_id")
            result.ibkr_filled = ibkr_result.get("filled", False)
            result.ibkr_fill_quantity = ibkr_result.get("fill_quantity", 0)
            result.ibkr_fill_price = ibkr_result.get("fill_price")
            
            if not result.ibkr_filled:
                # IBKR failed - rollback Kalshi
                self._capital.ibkr.release(ibkr_cost)
                
                rollback = await self._rollback_kalshi(
                    ticker=mapping.kalshi_ticker,
                    side=opportunity.kalshi_side,
                    quantity=result.kalshi_fill_quantity,
                )
                
                result.rolled_back = True
                result.rollback_details = rollback.get("details")
                result.error = ibkr_result.get("error", "IBKR order not filled")
                return result
            
            # 4. Success - update state
            self._capital.kalshi.confirm_spend(kalshi_cost)
            self._capital.ibkr.confirm_spend(ibkr_cost)
            
            self._capital.kalshi.add_position(
                symbol=opportunity.symbol,
                side=opportunity.kalshi_side,
                quantity=result.kalshi_fill_quantity,
                cost=result.kalshi_fill_price * result.kalshi_fill_quantity if result.kalshi_fill_price else kalshi_cost,
            )
            
            self._capital.ibkr.add_position(
                symbol=opportunity.symbol,
                side=opportunity.ibkr_side,
                quantity=result.ibkr_fill_quantity,
                cost=result.ibkr_fill_price * result.ibkr_fill_quantity if result.ibkr_fill_price else ibkr_cost,
            )
            
            # Calculate actual P&L
            actual_kalshi_cost = result.kalshi_fill_price * result.kalshi_fill_quantity if result.kalshi_fill_price else kalshi_cost
            actual_ibkr_cost = result.ibkr_fill_price * result.ibkr_fill_quantity if result.ibkr_fill_price else ibkr_cost
            
            kalshi_fee = KALSHI_FEES.taker_fee(result.kalshi_fill_price or opportunity.kalshi_price, result.kalshi_fill_quantity)
            ibkr_fee = IBKR_FEES.fee(result.ibkr_fill_quantity)
            result.actual_fees = kalshi_fee + ibkr_fee
            
            result.total_cost = actual_kalshi_cost + actual_ibkr_cost
            result.net_profit = result.expected_payout - result.total_cost - result.actual_fees
            result.success = True
            
            return result
            
        except Exception as e:
            # Emergency cleanup
            self._capital.kalshi.release(kalshi_cost)
            self._capital.ibkr.release(ibkr_cost)
            result.error = f"Execution error: {str(e)}"
            return result
    
    async def _execute_kalshi(
        self,
        ticker: str,
        side: str,
        quantity: int,
        price: Decimal,
    ) -> dict:
        """Place and wait for Kalshi order fill."""
        try:
            kalshi_side = KalshiSide.YES if side == "YES" else KalshiSide.NO
            price_cents = int(price * 100)
            
            order = await self._kalshi.place_order(
                ticker=ticker,
                side=kalshi_side,
                count=quantity,
                price_cents=price_cents,
            )
            
            # Wait for fill
            deadline = asyncio.get_event_loop().time() + self._timeout
            
            while asyncio.get_event_loop().time() < deadline:
                order = await self._kalshi.get_order(order.order_id)
                
                if order.is_filled:
                    return {
                        "order_id": order.order_id,
                        "filled": True,
                        "fill_quantity": order.fill_count,
                        "fill_price": order.price,
                    }

                if not order.is_open:
                    return {
                        "order_id": order.order_id,
                        "filled": False,
                        "error": f"Order {order.status.value}",
                    }
                
                await asyncio.sleep(self._poll_interval)
            
            # Timeout - cancel order
            await self._kalshi.cancel_order(order.order_id)
            
            return {
                "order_id": order.order_id,
                "filled": False,
                "fill_quantity": order.fill_count,
                "error": "Timeout waiting for fill",
            }
            
        except Exception as e:
            return {"filled": False, "error": str(e)}
    
    async def _execute_ibkr(
        self,
        con_id: int,
        quantity: int,
        price: Decimal,
    ) -> dict:
        """Place and wait for IBKR order fill."""
        try:
            order = await self._ibkr.place_order(
                con_id=con_id,
                quantity=quantity,
                limit_price=price,
            )
            
            # Wait for fill
            order = await self._ibkr.wait_for_fill(
                order.order_id,
                timeout=self._timeout,
                poll_interval=self._poll_interval,
            )
            
            if order.is_filled:
                return {
                    "order_id": order.order_id,
                    "filled": True,
                    "fill_quantity": order.filled_quantity,
                    "fill_price": order.avg_fill_price,
                }
            
            # Not filled - cancel
            if order.is_open:
                await self._ibkr.cancel_order(order.order_id)
            
            return {
                "order_id": order.order_id,
                "filled": False,
                "fill_quantity": order.filled_quantity,
                "error": f"Order {order.status.value}",
            }
            
        except Exception as e:
            return {"filled": False, "error": str(e)}
    
    async def _rollback_kalshi(
        self,
        ticker: str,
        side: str,
        quantity: int,
    ) -> dict:
        """
        Rollback a Kalshi position by buying the opposite side.
        
        If we bought YES, buy NO to hedge.
        If we bought NO, buy YES to hedge.
        """
        opposite_side = KalshiSide.NO if side == "YES" else KalshiSide.YES
        
        try:
            # Buy opposite at 99 cents (market-like)
            order = await self._kalshi.place_order(
                ticker=ticker,
                side=opposite_side,
                count=quantity,
                price_cents=99,
            )
            
            # Wait briefly for fill
            await asyncio.sleep(2.0)
            order = await self._kalshi.get_order(order.order_id)
            
            if order.is_filled:
                return {
                    "success": True,
                    "details": f"Hedged with {quantity} {opposite_side.value} @ ${order.price}",
                }
            else:
                return {
                    "success": False,
                    "details": f"Hedge order {order.status.value} - MANUAL INTERVENTION REQUIRED",
                }
                
        except Exception as e:
            return {
                "success": False,
                "details": f"Rollback failed: {str(e)} - MANUAL INTERVENTION REQUIRED",
            }