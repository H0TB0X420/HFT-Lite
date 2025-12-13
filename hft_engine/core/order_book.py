"""
Central Order Book.

Holds latest tick per symbol per exchange.
Triggers arbitrage detection on updates.
"""
import asyncio
from dataclasses import dataclass, field
from typing import Callable

from hft_engine.core.normalized_tick import NormalizedTick, Exchange
from hft_engine.core.arbitrage import ArbitrageDetector, ArbitrageOpportunity


@dataclass
class SymbolBook:
    """Order book for a single symbol across exchanges."""
    kalshi: NormalizedTick | None = None
    ibkr: NormalizedTick | None = None
    
    def update(self, tick: NormalizedTick) -> None:
        """Update tick for appropriate exchange."""
        if tick.exchange == Exchange.KALSHI:
            self.kalshi = tick
        elif tick.exchange == Exchange.IBKR:
            self.ibkr = tick
    
    @property
    def has_both(self) -> bool:
        """True if we have ticks from both exchanges."""
        return self.kalshi is not None and self.ibkr is not None


class CentralOrderBook:
    """
    Central order book for all tracked symbols.
    
    Triggers arbitrage detection on each update.
    """
    
    def __init__(
        self,
        detector: ArbitrageDetector | None = None,
        on_opportunity: Callable[[ArbitrageOpportunity], None] | None = None,
    ):
        self._books: dict[str, SymbolBook] = {}
        self._detector = detector or ArbitrageDetector()
        self._on_opportunity = on_opportunity
        self._lock = asyncio.Lock()
    
    async def update(self, tick: NormalizedTick) -> ArbitrageOpportunity | None:
        """
        Update order book with new tick.
        
        Returns ArbitrageOpportunity if detected, else None.
        """
        async with self._lock:
            symbol = tick.symbol
            
            if symbol not in self._books:
                self._books[symbol] = SymbolBook()
            
            book = self._books[symbol]
            book.update(tick)
            
            # Check for arbitrage if we have both sides
            if book.has_both:
                opportunity = self._detector.detect(book.kalshi, book.ibkr)
                
                if opportunity and self._on_opportunity:
                    self._on_opportunity(opportunity)
                
                return opportunity
            
            return None
    
    def get_book(self, symbol: str) -> SymbolBook | None:
        """Get order book for symbol."""
        return self._books.get(symbol)
    
    def get_all_books(self) -> dict[str, SymbolBook]:
        """Get all order books."""
        return self._books.copy()
    
    @property
    def symbols(self) -> list[str]:
        """All tracked symbols."""
        return list(self._books.keys())
