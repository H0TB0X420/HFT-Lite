"""
Logging configuration for HFT-Lite.

Provides high-precision timestamping and structured logging
suitable for post-trade analysis.
"""
import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime
import json
import time


class NanosecondFormatter(logging.Formatter):
    """
    Custom formatter that includes nanosecond precision timestamps.
    Essential for correlating events in HFT systems.
    """
    
    def formatTime(self, record: logging.LogRecord, datefmt: Optional[str] = None) -> str:
        # Get the current time with nanosecond precision
        ct = datetime.fromtimestamp(record.created)
        # Get additional nanoseconds (Python's time.time() only gives microseconds)
        nanos = int((record.created % 1) * 1_000_000_000)
        
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            s = ct.strftime("%Y-%m-%d %H:%M:%S")
        
        return f"{s}.{nanos:09d}"


class JsonFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.
    Useful for log aggregation systems like ELK stack.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "timestamp_ns": int(record.created * 1_000_000_000),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
            
        # Add any extra fields
        if hasattr(record, "extra_fields"):
            log_entry.update(record.extra_fields)
            
        return json.dumps(log_entry)


class TickLogger:
    """
    Specialized logger for market data ticks.
    
    Writes to a separate file for post-trade analysis.
    Uses binary format for efficiency when enabled.
    """
    
    def __init__(self, log_dir: Path, enabled: bool = True):
        self.enabled = enabled
        self.log_dir = log_dir
        self._file = None
        
        if enabled:
            log_dir.mkdir(parents=True, exist_ok=True)
            filename = log_dir / f"ticks_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            self._file = open(filename, 'w')
            # Write header
            self._file.write(
                "timestamp_local,timestamp_exchange,symbol,venue,"
                "bid_price,bid_size,ask_price,ask_size,sequence\n"
            )
    
    def log_tick(
        self,
        timestamp_local: int,
        timestamp_exchange: int,
        symbol: str,
        venue: str,
        bid_price: str,
        bid_size: int,
        ask_price: str,
        ask_size: int,
        sequence: int
    ) -> None:
        """Log a single tick to the tick log file."""
        if not self.enabled or not self._file:
            return
            
        self._file.write(
            f"{timestamp_local},{timestamp_exchange},{symbol},{venue},"
            f"{bid_price},{bid_size},{ask_price},{ask_size},{sequence}\n"
        )
    
    def flush(self) -> None:
        """Flush the log file."""
        if self._file:
            self._file.flush()
    
    def close(self) -> None:
        """Close the log file."""
        if self._file:
            self._file.close()
            self._file = None


def setup_logging(
    level: str = "INFO",
    log_format: Optional[str] = None,
    date_format: Optional[str] = None,
    file_path: Optional[str] = None,
    max_file_size_mb: int = 100,
    backup_count: int = 5,
    json_format: bool = False
) -> logging.Logger:
    """
    Configure logging for the application.
    
    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Custom log format string
        date_format: Custom date format string
        file_path: Path to log file (None for console only)
        max_file_size_mb: Max size of each log file before rotation
        backup_count: Number of backup files to keep
        json_format: Use JSON formatting for structured logs
        
    Returns:
        Root logger instance
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Create formatter
    if json_format:
        formatter = JsonFormatter()
    else:
        if not log_format:
            log_format = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
        formatter = NanosecondFormatter(fmt=log_format, datefmt=date_format)
    
    # Console handler (always)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (optional)
    if file_path:
        log_path = Path(file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.handlers.RotatingFileHandler(
            filename=log_path,
            maxBytes=max_file_size_mb * 1024 * 1024,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # Suppress noisy loggers
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a named logger."""
    return logging.getLogger(name)
