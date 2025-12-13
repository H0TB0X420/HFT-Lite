"""Arbitrage monitor logging."""
from datetime import datetime

from ..core.order_book import CentralOrderBook, SymbolBook
from ..core.arbitrage import ArbitrageOpportunity
from ..core.database import Database
from ..core.executor import ExecutionResult


class SpreadLogger:
    """Logs spread snapshots and arbitrage opportunities to CSV."""
    
    def __init__(self, database: Database, session_id: str | None = None):
            self._db = database
            self._session_id = session_id or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    @property
    def session_id(self) -> str:
        return self._session_id
    
    async def log_opportunity(self, opp: ArbitrageOpportunity, executed: bool = False) -> None:
        """Log detected arbitrage opportunity."""
        await self._db.log_opportunity(
            opp=opp,
            executed=executed,
            session_id=self._session_id,
        )
        
        # Console output
        print(f"\n{'='*60}")
        print(f"🚨 ARBITRAGE OPPORTUNITY DETECTED")
        print(f"{'='*60}")
        print(f"Symbol:        {opp.symbol}")
        print(f"Quantity:      {opp.quantity}")
        print(f"Kalshi:        Buy {opp.kalshi_side} @ ${opp.kalshi_price}")
        print(f"IBKR:          Buy {opp.ibkr_side} @ ${opp.ibkr_price}")
        print(f"Total Cost:    ${opp.total_cost}")
        print(f"Payout:        ${opp.quantity}.00")
        print(f"Gross Profit:  ${opp.gross_profit}")
        print(f"Fees:          ${opp.total_fees}")
        print(f"Net Profit:    ${opp.net_profit}")
        print(f"Margin:        {opp.profit_margin:.2f}%")
        print(f"Executed:      {'Yes' if executed else 'No'}")
        print(f"{'='*60}\n")

    async def log_spreads(self, order_book: CentralOrderBook) -> None:
        """Log current spreads for all symbols."""
        for symbol, book in order_book.get_all_books().items():
            kalshi_yes = book.kalshi.yes_ask if book.kalshi else None
            kalshi_no = book.kalshi.no_ask if book.kalshi else None
            ibkr_yes = book.ibkr.yes_ask if book.ibkr else None
            ibkr_no = book.ibkr.no_ask if book.ibkr else None
            
            await self._db.log_spread(
                symbol=symbol,
                kalshi_yes_ask=kalshi_yes,
                kalshi_no_ask=kalshi_no,
                ibkr_yes_ask=ibkr_yes,
                ibkr_no_ask=ibkr_no,
                session_id=self._session_id,
            )
    
    async def log_execution(self, result: ExecutionResult) -> None:
        """Log execution result."""
        await self._db.log_execution(result=result, session_id=self._session_id)
