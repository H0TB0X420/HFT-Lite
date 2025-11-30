"""
Utility functions for HFT-Lite.
"""
import time
import uuid
from datetime import datetime, timezone
from typing import Optional
import hashlib


# ============================================================================
# Time Utilities
# ============================================================================

def now_ns() -> int:
    """Get current time in nanoseconds since epoch."""
    return time.time_ns()


def now_ms() -> int:
    """Get current time in milliseconds since epoch."""
    return int(time.time() * 1000)


def now_us() -> int:
    """Get current time in microseconds since epoch."""
    return int(time.time() * 1_000_000)


def ns_to_datetime(timestamp_ns: int) -> datetime:
    """Convert nanosecond timestamp to datetime (UTC)."""
    return datetime.fromtimestamp(timestamp_ns / 1_000_000_000, tz=timezone.utc)


def ms_to_datetime(timestamp_ms: int) -> datetime:
    """Convert millisecond timestamp to datetime (UTC)."""
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


def datetime_to_ns(dt: datetime) -> int:
    """Convert datetime to nanosecond timestamp."""
    return int(dt.timestamp() * 1_000_000_000)


def datetime_to_ms(dt: datetime) -> int:
    """Convert datetime to millisecond timestamp."""
    return int(dt.timestamp() * 1000)


def iso_to_ns(iso_string: str) -> int:
    """Convert ISO format string to nanosecond timestamp."""
    dt = datetime.fromisoformat(iso_string.replace('Z', '+00:00'))
    return datetime_to_ns(dt)


def ns_to_iso(timestamp_ns: int) -> str:
    """Convert nanosecond timestamp to ISO format string."""
    return ns_to_datetime(timestamp_ns).isoformat()


def latency_ns_to_human(latency_ns: int) -> str:
    """Convert nanosecond latency to human-readable string."""
    if latency_ns < 1000:
        return f"{latency_ns}ns"
    elif latency_ns < 1_000_000:
        return f"{latency_ns / 1000:.2f}μs"
    elif latency_ns < 1_000_000_000:
        return f"{latency_ns / 1_000_000:.2f}ms"
    else:
        return f"{latency_ns / 1_000_000_000:.2f}s"


# ============================================================================
# ID Generation
# ============================================================================

def generate_order_id(prefix: str = "ORD") -> str:
    """
    Generate a unique order ID.
    
    Format: PREFIX-YYYYMMDD-HHMMSS-RANDOM
    Example: ORD-20241215-143052-a1b2c3
    """
    now = datetime.now(timezone.utc)
    date_part = now.strftime("%Y%m%d-%H%M%S")
    random_part = uuid.uuid4().hex[:6]
    return f"{prefix}-{date_part}-{random_part}"


def generate_signal_id() -> str:
    """Generate a unique signal ID."""
    return generate_order_id(prefix="SIG")


def generate_correlation_id() -> str:
    """Generate a correlation ID for linking related events."""
    return uuid.uuid4().hex


def generate_session_id() -> str:
    """Generate a session ID for connection tracking."""
    return f"SES-{uuid.uuid4().hex[:12]}"


# ============================================================================
# Hashing and Checksums
# ============================================================================

def hash_order_params(symbol: str, side: str, price: str, size: int) -> str:
    """
    Generate a hash of order parameters.
    Useful for deduplication.
    """
    content = f"{symbol}:{side}:{price}:{size}:{now_ms()}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# ============================================================================
# Rate Limiting
# ============================================================================

class RateLimiter:
    """
    Simple rate limiter using token bucket algorithm.
    """
    
    def __init__(self, rate: float, capacity: int):
        """
        Args:
            rate: Tokens added per second
            capacity: Maximum tokens in bucket
        """
        self.rate = rate
        self.capacity = capacity
        self._tokens = capacity
        self._last_update = time.monotonic()
    
    def acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens. Returns True if successful.
        """
        now = time.monotonic()
        elapsed = now - self._last_update
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_update = now
        
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False
    
    async def wait(self, tokens: int = 1) -> None:
        """
        Wait until tokens are available.
        """
        import asyncio
        while not self.acquire(tokens):
            await asyncio.sleep(0.01)
    
    @property
    def available(self) -> float:
        """Get current available tokens."""
        now = time.monotonic()
        elapsed = now - self._last_update
        return min(self.capacity, self._tokens + elapsed * self.rate)


class SlidingWindowCounter:
    """
    Sliding window rate counter.
    Useful for monitoring request rates.
    """
    
    def __init__(self, window_size_sec: float = 1.0):
        self.window_size = window_size_sec
        self._events: list[float] = []
    
    def record(self) -> None:
        """Record an event."""
        now = time.monotonic()
        self._events.append(now)
        self._cleanup(now)
    
    def count(self) -> int:
        """Get count of events in current window."""
        now = time.monotonic()
        self._cleanup(now)
        return len(self._events)
    
    def rate(self) -> float:
        """Get events per second."""
        return self.count() / self.window_size
    
    def _cleanup(self, now: float) -> None:
        """Remove events outside the window."""
        cutoff = now - self.window_size
        self._events = [t for t in self._events if t > cutoff]


# ============================================================================
# Retry Logic
# ============================================================================

class RetryConfig:
    """Configuration for retry logic."""
    
    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 0.1,
        max_delay: float = 10.0,
        exponential_base: float = 2.0,
        jitter: float = 0.1
    ):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number."""
        import random
        delay = self.initial_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)
        # Add jitter
        jitter_amount = delay * self.jitter
        delay += random.uniform(-jitter_amount, jitter_amount)
        return max(0, delay)


async def retry_async(
    func,
    config: Optional[RetryConfig] = None,
    exceptions: tuple = (Exception,)
):
    """
    Retry an async function with exponential backoff.
    
    Args:
        func: Async function to call
        config: Retry configuration
        exceptions: Tuple of exceptions to catch and retry
        
    Returns:
        Result of successful function call
        
    Raises:
        Last exception if all retries fail
    """
    import asyncio
    
    if config is None:
        config = RetryConfig()
    
    last_exception = None
    
    for attempt in range(config.max_attempts):
        try:
            return await func()
        except exceptions as e:
            last_exception = e
            if attempt < config.max_attempts - 1:
                delay = config.get_delay(attempt)
                await asyncio.sleep(delay)
    
    raise last_exception
