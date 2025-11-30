"""
Central Event Bus for HFT-Lite.

Implements a bounded async queue with backpressure handling.
This is the central nervous system - all ticks flow through here.
"""
import asyncio
from typing import Generic, TypeVar, Optional, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum, auto
import time
import logging

logger = logging.getLogger(__name__)

T = TypeVar('T')


class BackpressurePolicy(Enum):
    """How to handle queue overflow."""
    BLOCK = auto()      # Block producer until space available
    DROP_OLDEST = auto() # Drop oldest item to make room
    DROP_NEWEST = auto() # Drop the incoming item
    RAISE = auto()      # Raise exception


@dataclass
class QueueStats:
    """Statistics for monitoring queue health."""
    current_size: int
    max_size: int
    total_enqueued: int
    total_dequeued: int
    total_dropped: int
    avg_wait_time_ns: float
    max_wait_time_ns: int
    
    @property
    def utilization(self) -> float:
        """Queue utilization as a percentage."""
        return (self.current_size / self.max_size) * 100 if self.max_size > 0 else 0


class BoundedEventQueue(Generic[T]):
    """
    A bounded async queue with backpressure handling and monitoring.
    
    Features:
    - Configurable overflow policy
    - Built-in statistics tracking
    - Optional callback on overflow
    - Thread-safe for async operations
    """
    
    def __init__(
        self,
        max_size: int = 10000,
        policy: BackpressurePolicy = BackpressurePolicy.DROP_OLDEST,
        overflow_callback: Optional[Callable[[T], Awaitable[None]]] = None,
        name: str = "event_queue"
    ):
        self._queue: asyncio.Queue[tuple[T, int]] = asyncio.Queue(maxsize=max_size)
        self._max_size = max_size
        self._policy = policy
        self._overflow_callback = overflow_callback
        self._name = name
        
        # Statistics
        self._total_enqueued = 0
        self._total_dequeued = 0
        self._total_dropped = 0
        self._wait_times: list[int] = []
        self._max_wait_time_ns = 0
        
        # For DROP_OLDEST policy, we need a lock to safely manipulate
        self._lock = asyncio.Lock()
        
    async def put(self, item: T, timeout: Optional[float] = None) -> bool:
        """
        Put an item on the queue.
        
        Returns True if item was queued, False if dropped.
        Raises asyncio.QueueFull if policy is RAISE and queue is full.
        """
        enqueue_time = time.time_ns()
        
        if self._queue.full():
            if self._policy == BackpressurePolicy.BLOCK:
                # Block until space available
                try:
                    await asyncio.wait_for(
                        self._queue.put((item, enqueue_time)),
                        timeout=timeout
                    )
                    self._total_enqueued += 1
                    return True
                except asyncio.TimeoutError:
                    self._total_dropped += 1
                    return False
                    
            elif self._policy == BackpressurePolicy.DROP_OLDEST:
                async with self._lock:
                    # Remove oldest item
                    try:
                        dropped = self._queue.get_nowait()
                        self._total_dropped += 1
                        if self._overflow_callback:
                            await self._overflow_callback(dropped[0])
                    except asyncio.QueueEmpty:
                        pass
                    # Now add new item
                    try:
                        self._queue.put_nowait((item, enqueue_time))
                        self._total_enqueued += 1
                        return True
                    except asyncio.QueueFull:
                        # Race condition - another producer filled it
                        self._total_dropped += 1
                        return False
                        
            elif self._policy == BackpressurePolicy.DROP_NEWEST:
                self._total_dropped += 1
                if self._overflow_callback:
                    await self._overflow_callback(item)
                return False
                
            elif self._policy == BackpressurePolicy.RAISE:
                raise asyncio.QueueFull(f"Queue {self._name} is full")
        else:
            try:
                self._queue.put_nowait((item, enqueue_time))
                self._total_enqueued += 1
                return True
            except asyncio.QueueFull:
                # Race condition
                return await self.put(item, timeout)
    
    async def get(self, timeout: Optional[float] = None) -> T:
        """
        Get an item from the queue.
        
        Raises asyncio.TimeoutError if timeout expires.
        """
        if timeout:
            item, enqueue_time = await asyncio.wait_for(
                self._queue.get(),
                timeout=timeout
            )
        else:
            item, enqueue_time = await self._queue.get()
            
        self._total_dequeued += 1
        
        # Track wait time
        wait_time = time.time_ns() - enqueue_time
        self._wait_times.append(wait_time)
        if wait_time > self._max_wait_time_ns:
            self._max_wait_time_ns = wait_time
            
        # Keep only recent wait times for averaging
        if len(self._wait_times) > 1000:
            self._wait_times = self._wait_times[-1000:]
            
        return item
    
    def get_nowait(self) -> T:
        """Get an item without waiting. Raises QueueEmpty if empty."""
        item, enqueue_time = self._queue.get_nowait()
        self._total_dequeued += 1
        
        wait_time = time.time_ns() - enqueue_time
        self._wait_times.append(wait_time)
        if wait_time > self._max_wait_time_ns:
            self._max_wait_time_ns = wait_time
        if len(self._wait_times) > 1000:
            self._wait_times = self._wait_times[-1000:]
            
        return item
    
    def qsize(self) -> int:
        """Return current queue size."""
        return self._queue.qsize()
    
    def empty(self) -> bool:
        """Return True if queue is empty."""
        return self._queue.empty()
    
    def full(self) -> bool:
        """Return True if queue is full."""
        return self._queue.full()
    
    def get_stats(self) -> QueueStats:
        """Get queue statistics."""
        avg_wait = sum(self._wait_times) / len(self._wait_times) if self._wait_times else 0
        return QueueStats(
            current_size=self._queue.qsize(),
            max_size=self._max_size,
            total_enqueued=self._total_enqueued,
            total_dequeued=self._total_dequeued,
            total_dropped=self._total_dropped,
            avg_wait_time_ns=avg_wait,
            max_wait_time_ns=self._max_wait_time_ns
        )
    
    def reset_stats(self) -> None:
        """Reset statistics counters."""
        self._total_enqueued = 0
        self._total_dequeued = 0
        self._total_dropped = 0
        self._wait_times.clear()
        self._max_wait_time_ns = 0


class EventBus:
    """
    Central event bus for the system.
    
    Provides named queues for different event types and
    pub/sub functionality for components.
    """
    
    def __init__(self, default_queue_size: int = 10000):
        self._queues: dict[str, BoundedEventQueue] = {}
        self._default_size = default_queue_size
        self._subscribers: dict[str, list[Callable]] = {}
        
    def create_queue(
        self,
        name: str,
        max_size: Optional[int] = None,
        policy: BackpressurePolicy = BackpressurePolicy.DROP_OLDEST
    ) -> BoundedEventQueue:
        """Create a named queue."""
        if name in self._queues:
            raise ValueError(f"Queue {name} already exists")
        
        queue = BoundedEventQueue(
            max_size=max_size or self._default_size,
            policy=policy,
            name=name
        )
        self._queues[name] = queue
        return queue
    
    def get_queue(self, name: str) -> Optional[BoundedEventQueue]:
        """Get a queue by name."""
        return self._queues.get(name)
    
    async def publish(self, channel: str, event: any) -> None:
        """Publish an event to all subscribers of a channel."""
        if channel in self._subscribers:
            for callback in self._subscribers[channel]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event)
                    else:
                        callback(event)
                except Exception as e:
                    logger.error(f"Subscriber error on channel {channel}: {e}")
    
    def subscribe(self, channel: str, callback: Callable) -> None:
        """Subscribe to a channel."""
        if channel not in self._subscribers:
            self._subscribers[channel] = []
        self._subscribers[channel].append(callback)
    
    def unsubscribe(self, channel: str, callback: Callable) -> None:
        """Unsubscribe from a channel."""
        if channel in self._subscribers:
            self._subscribers[channel] = [
                cb for cb in self._subscribers[channel] if cb != callback
            ]
    
    def get_all_stats(self) -> dict[str, QueueStats]:
        """Get statistics for all queues."""
        return {name: queue.get_stats() for name, queue in self._queues.items()}
