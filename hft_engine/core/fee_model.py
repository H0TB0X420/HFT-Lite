# core/fee_model.py
"""
Fee models for each exchange.

Kalshi: Variable fee based on price
IBKR ForecastEx: Free
IBKR CME Events: $0.10/contract
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_UP

class KalshiFeeSchedule:
    """
    Kalshi taker fee calculation.

    Formula: fees = round_up(0.07 * C * P * (1-P))
    Where:
        P = price in dollars (0.50 = 50 cents)
        C = number of contracts
        round_up = rounds to the next cent

    Fees are highest at P=0.50, lowest at extremes.
    """
    def __init__(self, rate: Decimal = Decimal("0.07")):
        self.rate = rate
    
    def taker_fee(self, price: Decimal, quantity: int = 1) -> Decimal:
        """Calculate taker fee for given price and quantity."""
        p = price
        one_minus_p = Decimal("1") - price
        raw_fee = self.rate * quantity * p * one_minus_p
        
        # Round up to next cent
        return raw_fee.quantize(Decimal("0.01"), rounding=ROUND_UP)
    
    def maker_fee(self, price: Decimal, quantity: int = 1) -> Decimal:
        """Maker fee (same formula, may differ in future)."""
        return self.taker_fee(price, quantity)


@dataclass(frozen=True)
class IBKRFeeSchedule:
    """
    IBKR fee schedule.
    
    ForecastEx: $0.00/contract (free)
    CME Event: $0.10/contract + regulatory (estimate ~$0.02)
    """
    forecastex_fee: Decimal = Decimal("0.01")
    
    def fee(
        self,
        contracts: int = 1,
    ) -> Decimal:
        """Calculate fee for given product type."""
        return self.forecastex_fee * contracts


# Default instances
KALSHI_FEES = KalshiFeeSchedule()
IBKR_FEES = IBKRFeeSchedule()