# Architecture

## System Diagram
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ArbitrageMonitor                               │
│                           (monitor/arbitrage_monitor.py)                    │
│                                                                             │
│  Orchestrates connections, processes ticks, detects opportunities           │
└─────────────────────────────────────────────────────────────────────────────┘
        │                    │                    │                    │
        ▼                    ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Gateways   │    │ Order Book   │    │   Executor   │    │   Database   │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
        │                    │                    │                    │
        ▼                    ▼                    ▼                    ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│KalshiWebSocket│    │SymbolBook    │    │ KalshiRest   │    │ SQLite       │
│IBKRClient    │    │(per symbol)  │    │ IBKRClient   │    │ (aiosqlite)  │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
        │                    │                    
        ▼                    ▼                    
┌──────────────┐    ┌──────────────┐    
│ Normalizers  │    │  Arbitrage   │    
│Kalshi → Tick │    │  Detector    │    
│IBKR → Tick   │    │              │    
└──────────────┘    └──────────────┘    
```

## Components

### Gateways
**kalshi_websocket.py** — WebSocket connection with RSA-PSS authentication  
**kalshi_rest.py** — REST API for order placement  
**ibkr_client.py** — ib_insync wrapper for ForecastEx

Gateways emit raw market data to normalizers.

---

### Normalizers
**kalshi_normalizer.py** — Converts Kalshi orderbook deltas to NormalizedTick  
**ibkr_normalizer.py** — Converts IBKR ticker data to NormalizedTick  
**symbol_map.py** — Maps exchange-specific tickers to unified symbols

Normalizers produce uniform ticks regardless of source exchange.

---

### Order Book
**order_book.py** — CentralOrderBook holds SymbolBook per unified symbol  

Each SymbolBook tracks YES/NO ask prices for both exchanges. On update, checks for arbitrage via ArbitrageDetector.

---

### Arbitrage
**arbitrage.py** — ArbitrageDetector evaluates cross-venue combinations  
**fee_model.py** — Calculates Kalshi (7% on profit) and IBKR ($0.01/contract) fees

Detects when: `kalshi_price + ibkr_price + fees < $1.00`

---

### Executor
**executor.py** — Sequential order execution with rollback  

1. Reserve capital on both exchanges  
2. Place Kalshi order, wait for fill  
3. Place IBKR order, wait for fill  
4. If IBKR fails, buy opposite side on Kalshi to hedge

---

### Database
**database.py** — Async SQLite for logging  

Tables: `opportunities`, `spreads`, `executions`, `positions`

---

### Config
**loader.py** — Symbol mappings (unified ↔ exchange tickers)  
**execution_loader.py** — Risk limits and execution mode

---

## Data Flow
```
Exchange ─► Gateway ─► Normalizer ─► NormalizedTick ─► OrderBook ─► ArbitrageDetector
                                                                          │
                                                                          ▼
                                                              ArbitrageOpportunity
                                                                          │
                                                                          ▼
                                                                      Executor
                                                                          │
                                                            ┌─────────────┴─────────────┐
                                                            ▼                           ▼
                                                        Kalshi                        IBKR
                                                      (place order)               (place order)
                                                            │                           │
                                                            └─────────────┬─────────────┘
                                                                          ▼
                                                                      Database
                                                                    (log result)
```