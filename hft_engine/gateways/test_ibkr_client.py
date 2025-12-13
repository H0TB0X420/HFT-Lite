"""
Integration test for IBKR client.

Prerequisites:
- TWS or IB Gateway running and logged in
- API enabled on port 4001

Run: pytest test_ibkr_client.py -v -s
"""
import pytest
import asyncio
from .ibkr_client import IBKRConfig, IBKRClient

CON_ID = 762089343

@pytest.mark.asyncio
async def test_ibkr_client_connection():
    # Create config
    config = IBKRConfig(
        host="127.0.0.1",
        port=4001,
        client_id=1
    )
    assert config.port == 4001
    
    # Create client
    client = IBKRClient(config)
    print(client.is_connected)
    assert client.is_connected is False
    
    # Connect
    await client.connect()
    print(client.is_connected)
    assert client.is_connected is True
    
    # Subscribe to AAPL
    await client.subscribe(CON_ID)
    assert CON_ID in client._subscriptions
    
    received = 0
    for i in range(3):
        try:
            msg = await client.receive(timeout=5.0)
            print(f"\nMessage {i+1}: {msg}")
            assert msg["type"] == "tick"
            received += 1
        except asyncio.TimeoutError:
            print(f"\nTimeout on message {i+1} (market may be closed)")
            break

    assert received >= 1, "Should receive at least one tick"
    
    # Unsubscribe
    client.unsubscribe(CON_ID)
    assert CON_ID not in client._subscriptions
    
    # Disconnect
    await client.disconnect()
    assert client.is_connected is False

@pytest.mark.asyncio
async def test_ibkr_receive_normalized():
    config = IBKRConfig(host="127.0.0.1", port=4001, client_id=2)
    
    client = IBKRClient(config)
    await client.connect()
    assert client.is_connected
    
    await client.subscribe(CON_ID)
    
    # Receive normalized tick
    try:

        tick = await client.receive_normalized(timeout=10.0)
        
        print(f"\nNormalized: {tick}")
        assert tick.exchange.value == "IBKR"
        assert tick.bid >= 0 and tick.bid <= 1
        assert tick.ask >= 0 and tick.ask <= 1
        assert tick.timestamp_exchange > 0
        assert tick.timestamp_local > 0
    except asyncio.TimeoutError:
        if client.is_connected:
            await client.disconnect()
        pytest.skip("Market closed, no ticks received")
    
    client.unsubscribe(CON_ID)
    if client.is_connected:
        await client.disconnect()