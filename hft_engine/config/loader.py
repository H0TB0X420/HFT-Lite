"""Config loader for symbol mappings."""
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ContractMapping:
    """Single contract mapping across exchanges."""
    unified_symbol: str
    description: str
    kalshi_ticker: str
    ibkr_yes_conid: int
    ibkr_no_conid: int


class SymbolConfig:
    """Loads and provides lookups for symbol mappings."""
    
    def __init__(self, config_path: Path | str | None = None):
        if config_path is None:
            config_path = Path(__file__).parent / "symbol_mappings.json"
        
        self._config_path = Path(config_path)
        self._mappings: list[ContractMapping] = []
        self._by_unified: dict[str, ContractMapping] = {}
        self._by_kalshi: dict[str, ContractMapping] = {}
        self._by_ibkr_yes_conid: dict[int, ContractMapping] = {}
        self._by_ibkr_no_conid: dict[int, ContractMapping] = {}
        
        self._load()
    
    def _load(self) -> None:
        """Load mappings from JSON file."""
        with open(self._config_path) as f:
            data = json.load(f)
        
        for item in data["mappings"]:
            mapping = ContractMapping(
                unified_symbol=item["unified_symbol"],
                description=item["description"],
                kalshi_ticker=item["kalshi_ticker"],
                ibkr_yes_conid=item["ibkr_yes_conid"],
                ibkr_no_conid=item["ibkr_no_conid"],
            )
            self._mappings.append(mapping)
            self._by_unified[mapping.unified_symbol] = mapping
            self._by_kalshi[mapping.kalshi_ticker] = mapping
            self._by_ibkr_yes_conid[mapping.ibkr_yes_conid] = mapping
            self._by_ibkr_no_conid[mapping.ibkr_no_conid] = mapping
    
    @property
    def mappings(self) -> list[ContractMapping]:
        """All contract mappings."""
        return self._mappings
    
    @property
    def unified_symbols(self) -> list[str]:
        """All unified symbols."""
        return list(self._by_unified.keys())
    
    @property
    def kalshi_tickers(self) -> list[str]:
        """All Kalshi tickers."""
        return list(self._by_kalshi.keys())
    
    @property
    def ibkr_yes_conids(self) -> list[int]:
        """All IBKR YES conIds."""
        return list(self._by_ibkr_yes_conid.keys())
    
    @property
    def ibkr_no_conids(self) -> list[int]:
        """All IBKR NO conIds."""
        return list(self._by_ibkr_no_conid.keys())
    
    @property
    def ibkr_all_conids(self) -> list[int]:
        """All IBKR conIds (YES and NO)."""
        return self.ibkr_yes_conids + self.ibkr_no_conids
    
    def by_unified(self, symbol: str) -> ContractMapping | None:
        """Lookup by unified symbol."""
        return self._by_unified.get(symbol)
    
    def by_kalshi(self, ticker: str) -> ContractMapping | None:
        """Lookup by Kalshi ticker."""
        return self._by_kalshi.get(ticker)
    
    def by_ibkr_conid(self, conid: int) -> tuple[ContractMapping | None, str | None]:
        """
        Lookup by IBKR conId.
        
        Returns (mapping, side) where side is "YES" or "NO".
        """
        if conid in self._by_ibkr_yes_conid:
            return self._by_ibkr_yes_conid[conid], "YES"
        if conid in self._by_ibkr_no_conid:
            return self._by_ibkr_no_conid[conid], "NO"
        return None, None
    
    def kalshi_to_unified(self, ticker: str) -> str:
        """Convert Kalshi ticker to unified symbol."""
        mapping = self._by_kalshi.get(ticker)
        return mapping.unified_symbol if mapping else ticker
    
    def ibkr_to_unified(self, conid: int) -> tuple[str, str | None]:
        """
        Convert IBKR conId to unified symbol.
        
        Returns (unified_symbol, side) where side is "YES" or "NO".
        """
        mapping, side = self.by_ibkr_conid(conid)
        if mapping:
            return mapping.unified_symbol, side
        return str(conid), None