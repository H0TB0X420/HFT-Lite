"""Account state tracking for capital management."""
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


class Exchange(Enum):
    KALSHI = "KALSHI"
    IBKR = "IBKR"


@dataclass
class Position:
    """Position in a single contract."""
    symbol: str
    side: str  # "YES" or "NO"
    quantity: int
    avg_cost: Decimal
    
    @property
    def total_cost(self) -> Decimal:
        return self.avg_cost * self.quantity


@dataclass
class AccountState:
    """Tracks cash and positions for one exchange."""
    exchange: Exchange
    cash_available: Decimal = Decimal("0")
    cash_reserved: Decimal = Decimal("0")  # Pending orders
    positions: dict[str, Position] = field(default_factory=dict)
    
    @property
    def cash_total(self) -> Decimal:
        return self.cash_available + self.cash_reserved
    
    def can_afford(self, amount: Decimal) -> bool:
        return self.cash_available >= amount
    
    def reserve(self, amount: Decimal) -> bool:
        """Reserve cash for pending order."""
        if not self.can_afford(amount):
            return False
        self.cash_available -= amount
        self.cash_reserved += amount
        return True
    
    def release(self, amount: Decimal) -> None:
        """Release reserved cash (order cancelled/rejected)."""
        self.cash_reserved -= amount
        self.cash_available += amount
    
    def confirm_spend(self, amount: Decimal) -> None:
        """Confirm reserved cash was spent (order filled)."""
        self.cash_reserved -= amount
    
    def add_position(self, symbol: str, side: str, quantity: int, cost: Decimal) -> None:
        """Add or update position after fill."""
        key = f"{symbol}_{side}"
        if key in self.positions:
            pos = self.positions[key]
            total_qty = pos.quantity + quantity
            total_cost = pos.total_cost + cost
            pos.quantity = total_qty
            pos.avg_cost = total_cost / total_qty
        else:
            self.positions[key] = Position(
                symbol=symbol,
                side=side,
                quantity=quantity,
                avg_cost=cost / quantity,
            )
    
    def get_position_quantity(self, symbol: str, side: str) -> int:
        """Get current position quantity."""
        key = f"{symbol}_{side}"
        if key in self.positions:
            return self.positions[key].quantity
        return 0


@dataclass 
class CapitalManager:
    """Manages capital across both exchanges."""
    kalshi: AccountState = field(default_factory=lambda: AccountState(Exchange.KALSHI))
    ibkr: AccountState = field(default_factory=lambda: AccountState(Exchange.IBKR))
    
    # Limits
    max_capital_per_market: Decimal = Decimal("50.00")
    max_contracts_per_event: int = 100
    
    def set_balances(self, kalshi_cash: Decimal, ibkr_cash: Decimal) -> None:
        """Set initial cash balances."""
        self.kalshi.cash_available = kalshi_cash
        self.ibkr.cash_available = ibkr_cash
    
    def validate_opportunity(
        self,
        symbol: str,
        kalshi_side: str,
        kalshi_price: Decimal,
        ibkr_side: str,
        ibkr_price: Decimal,
        quantity: int = 1,
    ) -> tuple[bool, str]:
        """
        Validate if we can execute this opportunity.
        
        Returns (is_valid, reason).
        """
        total_cost = (kalshi_price + ibkr_price) * quantity
        kalshi_cost = kalshi_price * quantity
        ibkr_cost = ibkr_price * quantity
        
        # Check capital per market limit
        if total_cost > self.max_capital_per_market:
            return False, f"Exceeds max capital per market: ${total_cost} > ${self.max_capital_per_market}"
        
        # Check position limits
        kalshi_pos = self.kalshi.get_position_quantity(symbol, kalshi_side)
        ibkr_pos = self.ibkr.get_position_quantity(symbol, ibkr_side)
        
        if kalshi_pos + quantity > self.max_contracts_per_event:
            return False, f"Kalshi position limit: {kalshi_pos} + {quantity} > {self.max_contracts_per_event}"
        
        if ibkr_pos + quantity > self.max_contracts_per_event:
            return False, f"IBKR position limit: {ibkr_pos} + {quantity} > {self.max_contracts_per_event}"
        
        # Check available cash
        if not self.kalshi.can_afford(kalshi_cost):
            return False, f"Insufficient Kalshi cash: need ${kalshi_cost}, have ${self.kalshi.cash_available}"
        
        if not self.ibkr.can_afford(ibkr_cost):
            return False, f"Insufficient IBKR cash: need ${ibkr_cost}, have ${self.ibkr.cash_available}"
        
        return True, "OK"
    
    def calculate_max_quantity(
        self,
        symbol: str,
        kalshi_side: str,
        kalshi_price: Decimal,
        ibkr_side: str,
        ibkr_price: Decimal,
    ) -> int:
        """Calculate maximum contracts we can buy given limits."""
        cost_per_pair = kalshi_price + ibkr_price
        
        # Limit by capital per market
        max_by_capital = int(self.max_capital_per_market / cost_per_pair)
        
        # Limit by position size
        kalshi_pos = self.kalshi.get_position_quantity(symbol, kalshi_side)
        ibkr_pos = self.ibkr.get_position_quantity(symbol, ibkr_side)
        max_by_position = min(
            self.max_contracts_per_event - kalshi_pos,
            self.max_contracts_per_event - ibkr_pos,
        )
        
        # Limit by available cash
        max_by_kalshi_cash = int(self.kalshi.cash_available / kalshi_price)
        max_by_ibkr_cash = int(self.ibkr.cash_available / ibkr_price)
        
        return max(0, min(
            max_by_capital,
            max_by_position,
            max_by_kalshi_cash,
            max_by_ibkr_cash,
        ))