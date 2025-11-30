"""
Tests for event bus and queue functionality.
"""
import pytest
import asyncio
from hft_lite.core import (
    BoundedEventQueue,
    BackpressurePolicy,
    EventBus,
)


class TestBoundedEventQueue:
    """Tests for BoundedEventQueue."""
    
    @pytest.mark.asyncio
    async def test_basic_put_get(self):
        """Test basic enqueue/dequeue."""
        queue = BoundedEventQueue[str](max_size=10)
        
        await queue.put("test_item")
        result = await queue.get()
        
        assert result == "test_item"
        assert queue.empty()
    
    @pytest.mark.asyncio
    async def test_fifo_ordering(self):
        """Test FIFO ordering is maintained."""
        queue = BoundedEventQueue[int](max_size=10)
        
        for i in range(5):
            await queue.put(i)
        
        for i in range(5):
            result = await queue.get()
            assert result == i
    
    @pytest.mark.asyncio
    async def test_drop_oldest_policy(self):
        """Test DROP_OLDEST backpressure policy."""
        queue = BoundedEventQueue[int](
            max_size=3,
            policy=BackpressurePolicy.DROP_OLDEST
        )
        
        # Fill the queue
        await queue.put(1)
        await queue.put(2)
        await queue.put(3)
        assert queue.full()
        
        # Add one more - should drop oldest (1)
        success = await queue.put(4)
        assert success
        
        # Verify oldest was dropped
        results = []
        while not queue.empty():
            results.append(queue.get_nowait())
        
        assert results == [2, 3, 4]
    
    @pytest.mark.asyncio
    async def test_drop_newest_policy(self):
        """Test DROP_NEWEST backpressure policy."""
        queue = BoundedEventQueue[int](
            max_size=3,
            policy=BackpressurePolicy.DROP_NEWEST
        )
        
        # Fill the queue
        await queue.put(1)
        await queue.put(2)
        await queue.put(3)
        
        # Try to add - should be dropped
        success = await queue.put(4)
        assert not success
        
        # Verify original items remain
        results = []
        while not queue.empty():
            results.append(queue.get_nowait())
        
        assert results == [1, 2, 3]
    
    @pytest.mark.asyncio
    async def test_raise_policy(self):
        """Test RAISE backpressure policy."""
        queue = BoundedEventQueue[int](
            max_size=2,
            policy=BackpressurePolicy.RAISE
        )
        
        await queue.put(1)
        await queue.put(2)
        
        with pytest.raises(asyncio.QueueFull):
            await queue.put(3)
    
    @pytest.mark.asyncio
    async def test_statistics_tracking(self):
        """Test queue statistics are tracked correctly."""
        queue = BoundedEventQueue[int](
            max_size=3,
            policy=BackpressurePolicy.DROP_OLDEST
        )
        
        # Enqueue 5 items (2 will cause drops)
        for i in range(5):
            await queue.put(i)
        
        stats = queue.get_stats()
        assert stats.total_enqueued == 5
        assert stats.total_dropped == 2
        assert stats.current_size == 3
        
        # Dequeue all
        for _ in range(3):
            await queue.get()
        
        stats = queue.get_stats()
        assert stats.total_dequeued == 3
        assert stats.current_size == 0
    
    @pytest.mark.asyncio
    async def test_get_nowait_empty(self):
        """Test get_nowait raises on empty queue."""
        queue = BoundedEventQueue[str](max_size=10)
        
        with pytest.raises(asyncio.QueueEmpty):
            queue.get_nowait()
    
    @pytest.mark.asyncio
    async def test_reset_stats(self):
        """Test statistics reset."""
        queue = BoundedEventQueue[int](max_size=10)
        
        await queue.put(1)
        await queue.get()
        
        stats = queue.get_stats()
        assert stats.total_enqueued == 1
        
        queue.reset_stats()
        
        stats = queue.get_stats()
        assert stats.total_enqueued == 0
        assert stats.total_dequeued == 0


class TestEventBus:
    """Tests for EventBus pub/sub functionality."""
    
    def test_create_queue(self):
        """Test queue creation."""
        bus = EventBus()
        
        queue = bus.create_queue("test_queue", max_size=100)
        assert queue is not None
        
        # Should raise on duplicate
        with pytest.raises(ValueError):
            bus.create_queue("test_queue")
    
    def test_get_queue(self):
        """Test queue retrieval."""
        bus = EventBus()
        
        bus.create_queue("my_queue")
        
        queue = bus.get_queue("my_queue")
        assert queue is not None
        
        missing = bus.get_queue("nonexistent")
        assert missing is None
    
    @pytest.mark.asyncio
    async def test_publish_subscribe(self):
        """Test pub/sub functionality."""
        bus = EventBus()
        received = []
        
        async def handler(event):
            received.append(event)
        
        bus.subscribe("test_channel", handler)
        
        await bus.publish("test_channel", "event_1")
        await bus.publish("test_channel", "event_2")
        
        assert received == ["event_1", "event_2"]
    
    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        """Test multiple subscribers on same channel."""
        bus = EventBus()
        received_1 = []
        received_2 = []
        
        async def handler_1(event):
            received_1.append(event)
        
        async def handler_2(event):
            received_2.append(event)
        
        bus.subscribe("channel", handler_1)
        bus.subscribe("channel", handler_2)
        
        await bus.publish("channel", "test_event")
        
        assert received_1 == ["test_event"]
        assert received_2 == ["test_event"]
    
    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        """Test unsubscribe functionality."""
        bus = EventBus()
        received = []
        
        async def handler(event):
            received.append(event)
        
        bus.subscribe("channel", handler)
        await bus.publish("channel", "event_1")
        
        bus.unsubscribe("channel", handler)
        await bus.publish("channel", "event_2")
        
        assert received == ["event_1"]
    
    @pytest.mark.asyncio
    async def test_subscriber_error_isolation(self):
        """Test that one failing subscriber doesn't affect others."""
        bus = EventBus()
        received = []
        
        async def bad_handler(event):
            raise RuntimeError("Intentional error")
        
        async def good_handler(event):
            received.append(event)
        
        bus.subscribe("channel", bad_handler)
        bus.subscribe("channel", good_handler)
        
        # Should not raise, and good_handler should still receive
        await bus.publish("channel", "test")
        
        assert received == ["test"]
    
    def test_get_all_stats(self):
        """Test getting stats for all queues."""
        bus = EventBus()
        
        bus.create_queue("queue_1")
        bus.create_queue("queue_2")
        
        stats = bus.get_all_stats()
        
        assert "queue_1" in stats
        assert "queue_2" in stats
