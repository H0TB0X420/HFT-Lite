import os
import pytest
import json
import time
from dotenv import load_dotenv

from .kalshi_websocket import (
    Environment,
    KalshiConfig,
    KalshiWebSocket,
    load_private_key,
)


@pytest.mark.asyncio
async def test_kalshi_websocket_connection():
    load_dotenv()
    key_id = os.environ.get("KALSHI_KEY_ID")
    key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
    
    assert key_id is not None, "KALSHI_KEY_ID not set"
    assert key_path is not None, "KALSHI_PRIVATE_KEY_PATH not set"
    
    private_key = load_private_key(key_path)
    assert private_key is not None, "Failed to load private key"
    
    config = KalshiConfig(
        key_id=key_id,
        private_key=private_key,
        environment=Environment.PROD
    )
    assert config.ws_url == "wss://api.elections.kalshi.com/trade-api/ws/v2"
    
    client = KalshiWebSocket(config)
    assert client.ws is None
    assert client.is_connected is False
    
    await client.connect()
    assert client.is_connected is True
    assert client.ws is not None
    
    await client.subscribe_ticker()
    sid = 0
    for i in range(3):
        msg = await client.receive()
        msg_sid = msg.get("sid")
        msg_type = msg.get("type")
        if msg_sid: 
            sid = int(msg_sid)
        print(f"\nMessage {i+1}: {msg}")
        assert msg_type == "ticker" or msg_type == "subscribed"
        
    
    await client.unsubscribe(sid_list=[sid])
    await client.drain()

    await client.subscribe_orderbook(["KXPRESNOMD-28-GN"])
    for i in range(5):
        msg = await client.receive()
        msg_sid = msg.get("sid")
        msg_type = msg.get("type")
        if msg_sid: 
            sid = int(msg_sid)
        assert msg_type != "ticker"

        print(f"\nMessage {i+1}: {msg}")
    await client.unsubscribe(sid_list=[sid])
    await client.drain()
            


    await client.disconnect()
    assert client.is_connected is False
    assert client.ws is None

@pytest.mark.asyncio
async def test_kalshi_receive_normalized():
    load_dotenv()
    key_id = os.environ.get("KALSHI_KEY_ID")
    key_path = os.environ.get("KALSHI_PRIVATE_KEY_PATH")
    
    assert key_id is not None
    assert key_path is not None
    
    private_key = load_private_key(key_path)
    config = KalshiConfig(
        key_id=key_id,
        private_key=private_key,
        environment=Environment.PROD
    )
    
    client = KalshiWebSocket(config)
    await client.connect()
    assert client.is_connected
    
    await client.subscribe_ticker()
    
    # Receive normalized tick
    tick = await client.receive_normalized()
    
    print(f"\nNormalized: {tick}")
    assert tick.exchange.value == "KALSHI"
    assert tick.bid >= 0 and tick.bid <= 1
    assert tick.ask >= 0 and tick.ask <= 1
    assert tick.timestamp_exchange > 0
    assert tick.timestamp_local > 0
    
    await client.disconnect()