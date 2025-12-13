import asyncio
import json
import time
import base64
import ssl, certifi
from dataclasses import dataclass
from enum import Enum

import websockets
from websockets.asyncio.client import ClientConnection
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from hft_engine.core.normalized_tick import NormalizedTick
from hft_engine.normalizers.kalshi_normalizer import KalshiNormalizer


class Environment(Enum):
    DEMO = "demo"
    PROD = "prod"


@dataclass
class KalshiConfig:
    key_id: str
    private_key: rsa.RSAPrivateKey
    environment: Environment = Environment.PROD
    
    @property
    def ws_url(self) -> str:
        if self.environment == Environment.DEMO:
            return "wss://demo-api.kalshi.co/trade-api/ws/v2"
        return "wss://api.elections.kalshi.com/trade-api/ws/v2"
    
    @property
    def ws_path(self) -> str:
        return "/trade-api/ws/v2"


def load_private_key(path: str) -> rsa.RSAPrivateKey:
    """Load RSA private key from PEM file."""
    with open(path, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
        if isinstance(key, rsa.RSAPrivateKey):
            return key
        else:
            raise TypeError


def _sign_pss(private_key: rsa.RSAPrivateKey, message: str) -> str:
    """Sign message with RSA-PSS and return base64-encoded signature."""
    signature = private_key.sign(
        message.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH
        ),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode("utf-8")


def _get_auth_headers(config: KalshiConfig) -> dict[str, str]:
    """Generate authentication headers for WebSocket connection."""
    timestamp_ms = int(time.time() * 1000)
    timestamp_str = str(timestamp_ms)
    
    message = timestamp_str + "GET" + config.ws_path
    signature = _sign_pss(config.private_key, message)
   
    return {
        "KALSHI-ACCESS-KEY": config.key_id,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp_str,
    }


class KalshiWebSocket:
    """WebSocket client for Kalshi API."""
    
    def __init__(self, config: KalshiConfig):
        self.config = config
        self.ws: ClientConnection | None = None
        self._message_id = 1
        self._connected = False
        self._normalizer = KalshiNormalizer()
    
    @property
    def is_connected(self) -> bool:
        return self._connected and self.ws is not None
    
    async def connect(self) -> None:
        """Establish WebSocket connection."""
        if self._connected:
            return
        
        headers = _get_auth_headers(self.config)
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.ws = await websockets.connect(
            self.config.ws_url,
            additional_headers=headers,
            ssl=ssl_context
        )
        self._connected = True
    
    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        if self.ws:
            await self.ws.close()
            self.ws = None
        self._connected = False
    
    async def subscribe_orderbook(self, market_tickers: list[str]) -> None:
        """Subscribe to orderbook updates for a specific market."""
        if self.ws:
            msg = {
                "id": self._message_id,
                "cmd": "subscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": market_tickers
                }
            }
            self._message_id += 1
            await self.ws.send(json.dumps(msg))
        else:
            raise ConnectionError
    
    async def subscribe_ticker(self) -> None:
        """Subscribe to global ticker updates."""
        if self.ws:
            msg = {
                "id": self._message_id,
                "cmd": "subscribe",
                "params": {
                    "channels": ["ticker"]
                }
            }
            self._message_id += 1
            await self.ws.send(json.dumps(msg))
        else:
            raise ConnectionError
    
    async def unsubscribe(self, sid_list: list[int]) -> None:
        if self.ws:
            msg = {
                "id": self._message_id,
                "cmd": "unsubscribe",
                "params": {
                    "sids": sid_list
                }
            }
            self._message_id += 1
            await self.ws.send(json.dumps(msg))
        else:
            raise ConnectionError
    
    async def receive(self) -> dict:
        """Receive and parse a single message."""
        if self.ws:
            raw = await self.ws.recv() 
            return json.loads(raw)
        else:
            raise ConnectionError
    
    async def drain(self, stop_on_sid: int|None = None, timeout: float = 1):
        """
        Drains the buffer until a timeout occurs OR a specific SID is seen.

        Args:
            stop_on_sid (int): If found, draining stops and this message is returned.
            timeout (float): Max seconds to spend draining.

        Returns:
            dict: The message that triggered the stop_on_sid match.
            None: If the timeout was reached without finding the SID.
        """
        if not self.ws: return
        print(f">>> Draining buffer (Stop on SID: {stop_on_sid}, Timeout: {timeout}s)...")
        end_time = time.time() + timeout
        dropped_count = 0

        while time.time() < end_time:
            try:
                time_left = end_time - time.time()
                if time_left <= 0:
                    break

                # We MUST parse now to check the SID. 
                # using receive_json() or receive() + json.loads()
                raw_msg = await asyncio.wait_for(self.ws.recv(), timeout=time_left)
                msg_data = json.loads(raw_msg)
                msg_sid = msg_data.get("sid")

                if stop_on_sid is not None and msg_sid == stop_on_sid:
                    print(f">>> Drain Found target SID {stop_on_sid}! Returning message.")
                    return msg_data

                dropped_count += 1

            except asyncio.TimeoutError:
                break
            except Exception as e:
                print(f"Drain warning: {e}")
                break
        
        print(f">>> Drained/Dropped {dropped_count} stale messages.")
        return None

    async def receive_normalized(self) -> NormalizedTick:
        """Receive and normalize a single tick message."""
        while True:
            raw = await self.receive()
            tick = self._normalizer.normalize(raw)
            if tick is not None:
                return tick

    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
