"""
Configuration management for HFT-Lite.

Loads config from YAML files and environment variables.
Environment variables take precedence over file config.
Sensitive values (API keys) should ONLY be in environment variables.
"""
from dataclasses import dataclass, field
from typing import Optional
from decimal import Decimal
from pathlib import Path
import os
import yaml


@dataclass
class KalshiConfig:
    """Kalshi API configuration."""
    api_base_url: str = "https://trading-api.kalshi.com/trade-api/v2"
    ws_url: str = "wss://trading-api.kalshi.com/trade-api/ws/v2"
    api_key_id: str = ""            # From env: KALSHI_API_KEY_ID
    api_private_key: str = ""       # From env: KALSHI_PRIVATE_KEY (PEM format)
    heartbeat_interval_sec: int = 10
    reconnect_delay_sec: float = 1.0
    max_reconnect_attempts: int = 5
    request_timeout_sec: float = 5.0


@dataclass
class IBKRConfig:
    """Interactive Brokers TWS/Gateway configuration."""
    host: str = "127.0.0.1"
    port: int = 7497                # 7497 for TWS paper, 7496 for live, 4001/4002 for Gateway
    client_id: int = 1
    readonly: bool = False
    account: str = ""               # From env: IBKR_ACCOUNT
    request_timeout_sec: float = 10.0
    market_data_type: int = 1       # 1=Live, 2=Frozen, 3=Delayed, 4=Delayed-Frozen


@dataclass  
class RiskConfig:
    """Risk management parameters."""
    max_position_per_symbol: int = 100          # Max contracts per symbol per venue
    max_total_exposure: Decimal = Decimal("10000")  # Max total $ at risk
    max_daily_loss: Decimal = Decimal("500")    # Stop trading if daily loss exceeds
    max_orders_per_second: int = 5              # Rate limit
    min_edge_bps: Decimal = Decimal("50")       # Minimum edge in basis points to trade
    stale_quote_threshold_ms: int = 500         # Consider quotes stale after this
    max_slippage_bps: Decimal = Decimal("25")   # Max acceptable slippage


@dataclass
class FeeConfig:
    """Fee schedules for each venue."""
    # Kalshi fees (as of 2024)
    kalshi_taker_fee: Decimal = Decimal("0.07")     # 7 cents per contract
    kalshi_maker_fee: Decimal = Decimal("0.00")     # No maker fee
    kalshi_settlement_fee: Decimal = Decimal("0.03") # 3 cents on winning contracts
    
    # IBKR fees vary by product - these are estimates for event contracts
    ibkr_taker_fee: Decimal = Decimal("0.05")
    ibkr_maker_fee: Decimal = Decimal("0.02")
    ibkr_min_fee: Decimal = Decimal("1.00")


@dataclass
class SymbolMapping:
    """Maps unified symbols to venue-specific identifiers."""
    unified_symbol: str             # Our internal symbol (e.g., "FED-RATE-DEC-2024")
    kalshi_ticker: str              # Kalshi ticker (e.g., "FED-24DEC-T4.50")
    ibkr_con_id: int                # IBKR contract ID
    contract_type: str = "YES"      # YES or NO
    multiplier: Decimal = Decimal("1")


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    format: str = "%(asctime)s.%(msecs)03d | %(levelname)-8s | %(name)s | %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"
    file_path: Optional[str] = None
    max_file_size_mb: int = 100
    backup_count: int = 5
    log_ticks: bool = False         # Very verbose - disable in production
    log_orders: bool = True


@dataclass
class SystemConfig:
    """Top-level system configuration."""
    kalshi: KalshiConfig = field(default_factory=KalshiConfig)
    ibkr: IBKRConfig = field(default_factory=IBKRConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    fees: FeeConfig = field(default_factory=FeeConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    symbols: list[SymbolMapping] = field(default_factory=list)
    
    # System behavior
    snapshot_interval_sec: int = 300            # Request snapshots every 5 min
    queue_max_size: int = 10000                 # Max pending ticks in queue
    enable_trading: bool = False                # Safety switch - must explicitly enable
    paper_trading: bool = True                  # Paper trade mode
    
    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> "SystemConfig":
        """
        Load configuration from file and environment variables.
        Environment variables override file config.
        """
        config = cls()
        
        # Load from YAML file if provided
        if config_path and config_path.exists():
            with open(config_path) as f:
                file_config = yaml.safe_load(f)
                config = cls._merge_dict(config, file_config)
        
        # Override with environment variables (sensitive data)
        config.kalshi.api_key_id = os.getenv("KALSHI_API_KEY_ID", config.kalshi.api_key_id)
        config.kalshi.api_private_key = os.getenv("KALSHI_PRIVATE_KEY", config.kalshi.api_private_key)
        config.ibkr.account = os.getenv("IBKR_ACCOUNT", config.ibkr.account)
        
        # System overrides
        if os.getenv("HFT_ENABLE_TRADING", "").lower() == "true":
            config.enable_trading = True
        if os.getenv("HFT_PAPER_TRADING", "").lower() == "false":
            config.paper_trading = False
            
        return config
    
    @classmethod
    def _merge_dict(cls, config: "SystemConfig", data: dict) -> "SystemConfig":
        """Merge dictionary into config object."""
        if not data:
            return config
            
        if "kalshi" in data:
            for k, v in data["kalshi"].items():
                if hasattr(config.kalshi, k):
                    setattr(config.kalshi, k, v)
                    
        if "ibkr" in data:
            for k, v in data["ibkr"].items():
                if hasattr(config.ibkr, k):
                    setattr(config.ibkr, k, v)
                    
        if "risk" in data:
            for k, v in data["risk"].items():
                if hasattr(config.risk, k):
                    # Convert to Decimal if needed
                    if isinstance(getattr(config.risk, k), Decimal):
                        v = Decimal(str(v))
                    setattr(config.risk, k, v)
                    
        if "fees" in data:
            for k, v in data["fees"].items():
                if hasattr(config.fees, k):
                    setattr(config.fees, k, Decimal(str(v)))
                    
        if "logging" in data:
            for k, v in data["logging"].items():
                if hasattr(config.logging, k):
                    setattr(config.logging, k, v)
                    
        if "symbols" in data:
            config.symbols = [
                SymbolMapping(**s) for s in data["symbols"]
            ]
            
        # Top-level settings
        for key in ["snapshot_interval_sec", "queue_max_size", "enable_trading", "paper_trading"]:
            if key in data:
                setattr(config, key, data[key])
                
        return config
    
    def validate(self) -> list[str]:
        """
        Validate configuration. Returns list of error messages.
        Empty list means config is valid.
        """
        errors = []
        
        # Kalshi validation
        if not self.kalshi.api_key_id:
            errors.append("KALSHI_API_KEY_ID not set")
        if not self.kalshi.api_private_key:
            errors.append("KALSHI_PRIVATE_KEY not set")
            
        # IBKR validation  
        if not self.ibkr.account:
            errors.append("IBKR_ACCOUNT not set")
        if self.ibkr.port not in [7496, 7497, 4001, 4002]:
            errors.append(f"Unusual IBKR port: {self.ibkr.port}")
            
        # Risk validation
        if self.risk.max_position_per_symbol <= 0:
            errors.append("max_position_per_symbol must be positive")
        if self.risk.min_edge_bps <= 0:
            errors.append("min_edge_bps must be positive")
            
        # Symbol validation
        if not self.symbols:
            errors.append("No symbols configured")
        for sym in self.symbols:
            if not sym.kalshi_ticker:
                errors.append(f"Missing Kalshi ticker for {sym.unified_symbol}")
            if not sym.ibkr_con_id:
                errors.append(f"Missing IBKR conId for {sym.unified_symbol}")
                
        # Safety check
        if self.enable_trading and not self.paper_trading:
            errors.append("WARNING: Live trading is enabled!")
            
        return errors
