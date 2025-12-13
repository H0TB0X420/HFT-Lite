"""Execution configuration."""
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path


@dataclass
class ExecutionConfig:
    """Execution parameters."""
    mode: str  # "logging" or "live"
    max_capital_per_market: Decimal
    max_contracts_per_event: int
    min_net_profit: Decimal
    max_stale_seconds: float
    
    @classmethod
    def load(cls, path: Path | str | None = None) -> "ExecutionConfig":
        if path is None:
            path = Path(__file__).parent / "execution_config.json"
        
        with open(path) as f:
            data = json.load(f)
        
        limits = data.get("limits", {})
        execution = data.get("execution", {})
        
        return cls(
            mode=execution.get("mode", "logging"),
            max_capital_per_market=Decimal(str(limits.get("max_capital_per_market", 50.00))),
            max_contracts_per_event=limits.get("max_contracts_per_event", 100),
            min_net_profit=Decimal(str(limits.get("min_net_profit", 0.00))),
            max_stale_seconds=limits.get("max_stale_seconds", 5),
        )