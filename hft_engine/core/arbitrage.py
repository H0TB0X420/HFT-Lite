# core/arbitrage.py
"""
Arbitrage detection engine.
"""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from hft_engine.core.normalized_tick import NormalizedTick, Exchange
from hft_engine.core.fee_model import (
    KalshiFeeSchedule,
    IBKRFeeSchedule,
    KALSHI_FEES,
    IBKR_FEES,
)


class Side(Enum):
    BUY_YES_KALSHI_NO_IBKR = "BUY_YES_KALSHI_NO_IBKR"
    BUY_NO_KALSHI_YES_IBKR = "BUY_NO_KALSHI_YES_IBKR"


@dataclass(frozen=True)
class ArbitrageOpportunity:
    """Detected arbitrage opportunity."""
    symbol: str
    side: Side
    
    # What to buy on each exchange
    kalshi_side: str          # "YES" or "NO"
    kalshi_price: Decimal
    ibkr_side: str            # "YES" or "NO"
    ibkr_price: Decimal
    
    # Costs and profit
    
    total_cost: Decimal       # kalshi_price + ibkr_price
    gross_profit: Decimal     # 1.00 - total_cost
    kalshi_fee: Decimal
    ibkr_fee: Decimal
    total_fees: Decimal
    slippage_buffer: Decimal
    net_profit: Decimal       # gross - fees - slippage
    
    # Metadata
    timestamp_ns: int

    quantity: int = 1
    
    @property
    def is_profitable(self) -> bool:
        return self.net_profit > 0
    
    @property
    def profit_margin(self) -> Decimal:
        """Net profit as percentage of total cost."""
        if self.total_cost == 0:
            return Decimal("0")
        return (self.net_profit / self.total_cost) * 100
    
    @property
    def parity_gap(self) -> Decimal:
        """How far below $1.00 the combined cost is."""
        return Decimal("1.00") - self.total_cost

class ArbitrageDetector:
    """Detects cross-exchange arbitrage by buying both sides."""
    
    def __init__(
        self,
        kalshi_fees: KalshiFeeSchedule = KALSHI_FEES,
        ibkr_fees: IBKRFeeSchedule = IBKR_FEES,
        slippage_buffer: Decimal = Decimal("0.01"),
        min_profit: Decimal = Decimal("0.00"),
    ):
        self.kalshi_fees = kalshi_fees
        self.ibkr_fees = ibkr_fees
        self.slippage_buffer = slippage_buffer
        self.min_profit = min_profit
    
    def detect(
        self,
        kalshi_tick: NormalizedTick,
        ibkr_tick: NormalizedTick,
    ) -> "ArbitrageOpportunity | None":
        """
        Detect arbitrage by buying both sides across exchanges.
        
        Profit exists if: yes_ask(A) + no_ask(B) < 1.00 - fees - slippage
        """
        # Import here to avoid circular import
        from .arbitrage import ArbitrageOpportunity, Side
        
        if kalshi_tick.symbol != ibkr_tick.symbol:
            return None
        
        timestamp = max(kalshi_tick.timestamp_local, ibkr_tick.timestamp_local)
        
        # Option 1: Buy YES on Kalshi + Buy NO on IBKR
        opp1 = self._check_opportunity(
            kalshi_price=kalshi_tick.yes_ask,
            kalshi_side="YES",
            ibkr_price=ibkr_tick.no_ask,
            ibkr_side="NO",
            side=Side.BUY_YES_KALSHI_NO_IBKR,
            symbol=kalshi_tick.symbol,
            timestamp=timestamp,
        )
        
        # Option 2: Buy NO on Kalshi + Buy YES on IBKR
        opp2 = self._check_opportunity(
            kalshi_price=kalshi_tick.no_ask,
            kalshi_side="NO",
            ibkr_price=ibkr_tick.yes_ask,
            ibkr_side="YES",
            side=Side.BUY_NO_KALSHI_YES_IBKR,
            symbol=kalshi_tick.symbol,
            timestamp=timestamp,
        )
        
        # Return best opportunity
        if opp1 and opp2:
            return opp1 if opp1.net_profit > opp2.net_profit else opp2
        return opp1 or opp2
    
    def _check_opportunity(
        self,
        kalshi_price: Decimal,
        kalshi_side: str,
        ibkr_price: Decimal,
        ibkr_side: str,
        side,
        symbol: str,
        timestamp: int,
        quantity: int = 1,
    ) -> "ArbitrageOpportunity | None":
        """Check if a specific combination is profitable."""
        from .arbitrage import ArbitrageOpportunity
        
        total_cost = (kalshi_price + ibkr_price) * quantity
        
        if (kalshi_price + ibkr_price) >= Decimal("1.00"):
            return None
        
        gross_profit = (Decimal("1.00") - kalshi_price - ibkr_price) * quantity
        
        # Calculate fees with quantity
        kalshi_fee = self.kalshi_fees.taker_fee(kalshi_price, quantity)
        ibkr_fee = self.ibkr_fees.fee(quantity)
        total_fees = kalshi_fee + ibkr_fee
        
        net_profit = gross_profit - total_fees - (self.slippage_buffer * quantity)
        
        if net_profit < self.min_profit:
            return None
        
        return ArbitrageOpportunity(
            symbol=symbol,
            side=side,
            kalshi_side=kalshi_side,
            kalshi_price=kalshi_price,
            ibkr_side=ibkr_side,
            ibkr_price=ibkr_price,
            total_cost=total_cost,
            gross_profit=gross_profit,
            kalshi_fee=kalshi_fee,
            ibkr_fee=ibkr_fee,
            total_fees=total_fees,
            slippage_buffer=self.slippage_buffer * quantity,
            net_profit=net_profit,
            timestamp_ns=timestamp,
        )