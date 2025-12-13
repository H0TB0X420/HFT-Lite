"""Kalshi REST API client for order management."""
import base64
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from .kalshi_websocket import KalshiConfig, Environment


class OrderAction(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderSide(Enum):
    YES = "yes"
    NO = "no"


class OrderType(Enum):
    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(Enum):
    RESTING = "resting"
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    EXECUTED = "executed"
    CANCELED = "canceled"
    CANCELLED = "cancelled"  # API might use either spelling
    EXPIRED = "expired"


@dataclass
class KalshiOrder:
    """Kalshi order response."""
    order_id: str
    client_order_id: str
    ticker: str
    action: OrderAction
    side: OrderSide
    type: OrderType
    status: OrderStatus
    initial_count: int
    remaining_count: int
    fill_count: int
    price: Decimal
    
    @classmethod
    def from_response(cls, data: dict) -> "KalshiOrder":
        # Handle status - might have different values
        status_str = data.get("status", "pending")
        try:
            status = OrderStatus(status_str)
        except ValueError:
            status = OrderStatus.PENDING
        
        # Price in cents
        price_cents = data.get("yes_price") or data.get("no_price") or 0
        
        return cls(
            order_id=data.get("order_id", ""),
            client_order_id=data.get("client_order_id", ""),
            ticker=data.get("ticker", ""),
            action=OrderAction(data.get("action", "buy")),
            side=OrderSide(data.get("side", "yes")),
            type=OrderType(data.get("type", "limit")),
            status=status,
            initial_count=data.get("initial_count", 0),
            remaining_count=data.get("remaining_count", 0),
            fill_count=data.get("fill_count", 0),
            price=Decimal(price_cents) / 100,
        )
    
    @property
    def is_filled(self) -> bool:
        return self.remaining_count == 0 and self.fill_count > 0
    
    @property
    def is_open(self) -> bool:
        return self.status == OrderStatus.RESTING or self.remaining_count > 0


class KalshiRestClient:
    """REST client for Kalshi order management."""
    
    def __init__(self, config: KalshiConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None
    
    @property
    def base_url(self) -> str:
        if self.config.environment == Environment.DEMO:
            return "https://demo-api.kalshi.co"
        return "https://api.elections.kalshi.com"
    
    async def connect(self) -> None:
        """Initialize HTTP client."""
        self._client = httpx.AsyncClient(timeout=30.0)
    
    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    def _sign(self, timestamp: str, method: str, path: str) -> str:
        """Sign request with RSA-PSS."""
        message = timestamp + method + path
        signature = self.config.private_key.sign(
            message.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        return base64.b64encode(signature).decode("utf-8")
    
    def _get_headers(self, method: str, path: str) -> dict[str, str]:
        """Generate authenticated headers."""
        timestamp = str(int(time.time() * 1000))
        signature = self._sign(timestamp, method, path)
        
        return {
            "KALSHI-ACCESS-KEY": self.config.key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
            "Content-Type": "application/json",
        }
    
    async def place_order(
        self,
        ticker: str,
        side: OrderSide,
        count: int,
        price_cents: int,
        action: OrderAction = OrderAction.BUY,
        order_type: OrderType = OrderType.LIMIT,
        client_order_id: str | None = None,
    ) -> KalshiOrder:
        """
        Place an order on Kalshi.
        
        Args:
            ticker: Market ticker (e.g., "CONTROLH-2026-D")
            side: YES or NO
            count: Number of contracts
            price_cents: Limit price in cents (1-99)
            action: BUY or SELL
            order_type: LIMIT or MARKET
            client_order_id: Optional client-provided ID
        
        Returns:
            KalshiOrder with order details
        """
        if not self._client:
            raise ConnectionError("Client not connected. Call connect() first.")
        
        path = "/trade-api/v2/portfolio/orders"
        
        if client_order_id is None:
            client_order_id = str(uuid.uuid4())
        
        order_data = {
            "ticker": ticker,
            "action": action.value,
            "side": side.value,
            "count": count,
            "type": order_type.value,
            "client_order_id": client_order_id,
        }
        
        # Set price based on side
        if side == OrderSide.YES:
            order_data["yes_price"] = price_cents
        else:
            order_data["no_price"] = price_cents
        
        headers = self._get_headers("POST", path)
        response = await self._client.post(
            self.base_url + path,
            headers=headers,
            json=order_data,
        )
        
        if response.status_code == 201:
            return KalshiOrder.from_response(response.json()["order"])
        else:
            raise Exception(f"Order failed: {response.status_code} - {response.text}")
    
    async def cancel_order(self, order_id: str) -> KalshiOrder:
        """
        Cancel an open order.
        
        Args:
            order_id: The order ID to cancel
        
        Returns:
            KalshiOrder with updated status
        """
        if not self._client:
            raise ConnectionError("Client not connected. Call connect() first.")
        
        path = f"/trade-api/v2/portfolio/orders/{order_id}"
        headers = self._get_headers("DELETE", path)
        
        response = await self._client.delete(
            self.base_url + path,
            headers=headers,
        )
        
        if response.status_code == 200:
            return KalshiOrder.from_response(response.json()["order"])
        else:
            raise Exception(f"Cancel failed: {response.status_code} - {response.text}")
    
    async def get_order(self, order_id: str) -> KalshiOrder:
        """
        Get order status.
        
        Args:
            order_id: The order ID to query
        
        Returns:
            KalshiOrder with current status
        """
        if not self._client:
            raise ConnectionError("Client not connected. Call connect() first.")
        
        path = f"/trade-api/v2/portfolio/orders/{order_id}"
        headers = self._get_headers("GET", path)
        
        response = await self._client.get(
            self.base_url + path,
            headers=headers,
        )
        
        if response.status_code == 200:
            return KalshiOrder.from_response(response.json()["order"])
        else:
            raise Exception(f"Get order failed: {response.status_code} - {response.text}")
    
    async def get_balance(self) -> Decimal:
        """
        Get account balance.
        
        Returns:
            Available balance in dollars
        """
        if not self._client:
            raise ConnectionError("Client not connected. Call connect() first.")
        
        path = "/trade-api/v2/portfolio/balance"
        headers = self._get_headers("GET", path)
        
        response = await self._client.get(
            self.base_url + path,
            headers=headers,
        )
        
        if response.status_code == 200:
            # Balance is returned in cents
            balance_cents = response.json()["balance"]
            return Decimal(balance_cents) / 100
        else:
            raise Exception(f"Get balance failed: {response.status_code} - {response.text}")
    
    async def get_positions(self) -> list[dict]:
        """
        Get open positions.
        
        Returns:
            List of position dictionaries
        """
        if not self._client:
            raise ConnectionError("Client not connected. Call connect() first.")
        
        path = "/trade-api/v2/portfolio/positions"
        headers = self._get_headers("GET", path)
        
        response = await self._client.get(
            self.base_url + path,
            headers=headers,
        )
        
        if response.status_code == 200:
            return response.json().get("positions", [])
        else:
            raise Exception(f"Get positions failed: {response.status_code} - {response.text}")
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()