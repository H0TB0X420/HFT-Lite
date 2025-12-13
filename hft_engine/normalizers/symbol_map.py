"""
Symbol mapping between exchanges.

Maps exchange-specific identifiers to unified symbols for cross-exchange comparison.
"""

# Kalshi market_ticker -> Unified symbol
KALSHI_SYMBOL_MAP: dict[str, str] = {
    # Add mappings as you identify equivalent contracts
    # "KXFEDFUNDS-25DEC": "FED_FUNDS_DEC25",
}

# IBKR conId -> Unified symbol
IBKR_SYMBOL_MAP: dict[int, str] = {
    # Add mappings as you identify equivalent contracts
    # 745923962: "FED_FUNDS_DEC25",
}


def kalshi_to_unified(market_ticker: str) -> str:
    """
    Convert Kalshi market ticker to unified symbol.
    
    Returns the original ticker if no mapping exists.
    """
    return KALSHI_SYMBOL_MAP.get(market_ticker, market_ticker)


def ibkr_to_unified(con_id: int, symbol: str) -> str:
    """
    Convert IBKR contract to unified symbol.
    
    Falls back to IBKR symbol if no mapping exists.
    """
    return IBKR_SYMBOL_MAP.get(con_id, symbol)


def add_mapping(
    kalshi_ticker: str,
    ibkr_yes_con_id: int,
    unified_symbol: str,
    ibkr_no_con_id: int | None = None,
) -> None:
    """Add a symbol mapping at runtime."""
    KALSHI_SYMBOL_MAP[kalshi_ticker] = unified_symbol
    IBKR_SYMBOL_MAP[ibkr_yes_con_id] = unified_symbol
    if ibkr_no_con_id is not None:
        IBKR_SYMBOL_MAP[ibkr_no_con_id] = unified_symbol