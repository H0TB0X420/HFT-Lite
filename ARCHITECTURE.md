# HFT-Lite Architecture Guide

A comprehensive technical deep-dive into the design and implementation of a cross-venue arbitrage system for event prediction markets.

---

## Table of Contents

1. [The Core Problem](#the-core-problem)
2. [Architectural Pattern](#architectural-pattern-event-driven-pipeline)
3. [Component Deep-Dives](#component-deep-dives)
   - [NormalizedTick](#1-normalizedtick--the-canonical-data-format)
   - [BoundedEventQueue](#2-boundedeventqueue--backpressure-handling)
   - [CentralOrderBook](#3-centralorderbook--the-state-machine)
   - [Timestamp Architecture](#4-timestamp-architecture)
   - [Fee Modeling](#5-fee-modeling)
   - [Position Tracking](#6-position-tracking-with-pnl-attribution)
   - [Type System](#7-the-type-system-as-documentation)
   - [Configuration](#8-configuration-philosophy)
4. [Concurrency Model](#concurrency-model)
5. [Production Considerations](#what-would-make-this-production-grade)
6. [Interview Talking Points](#how-to-talk-about-this-in-interviews)

---

## The Core Problem

This system exploits price discrepancies between two venues (Kalshi and Interactive Brokers) that offer economically equivalent event contracts. The challenge isn't the math—it's building infrastructure that can:

1. **Observe** prices from both venues with minimal latency
2. **Detect** opportunities before they disappear (often <100ms lifespan)
3. **Execute** on both legs before the market moves against you
4. **Recover** gracefully when things go wrong (and they will)

---

## Architectural Pattern: Event-Driven Pipeline

```
┌─────────────┐     ┌─────────────┐
│   Kalshi    │     │    IBKR     │
│  WebSocket  │     │   TWS API   │
└──────┬──────┘     └──────┬──────┘
       │                   │
       ▼                   ▼
┌──────────────────────────────────┐
│           Normalizers            │  ← Translate venue-specific → unified format
└──────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────┐
│     BoundedEventQueue (Ticks)    │  ← Backpressure-aware buffer
└──────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────┐
│        CentralOrderBook          │  ← Single source of truth for prices
└──────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────┐
│        ArbitrageEngine           │  ← Signal generation
└──────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────┐
│       ExecutionManager           │  ← Order routing + position tracking
└──────────────────────────────────┘
                 │
         ┌──────┴──────┐
         ▼             ▼
    ┌─────────┐   ┌─────────┐
    │ Kalshi  │   │  IBKR   │
    │  Orders │   │ Orders  │
    └─────────┘   └─────────┘
```

This is a **unidirectional dataflow** architecture. Data moves in one direction: from exchanges, through processing stages, to execution. This eliminates circular dependencies and makes the system easier to reason about under pressure.

---

## Component Deep-Dives

### 1. NormalizedTick — The Canonical Data Format

```python
@dataclass(frozen=True, slots=True)
class NormalizedTick:
    symbol: str
    venue: Venue
    bid_price: Decimal      # Probability [0.01, 0.99]
    bid_size: int
    ask_price: Decimal
    ask_size: int
    timestamp_exchange: int # Nanoseconds
    timestamp_local: int    # Nanoseconds
    sequence: int
```

#### Design Decisions

| Decision | Rationale |
|----------|-----------|
| `frozen=True` | Immutability prevents accidental mutation as ticks flow through the pipeline. If a component needs to modify a tick, it must create a new one—this makes bugs obvious. |
| `slots=True` | Reduces memory footprint by ~40% vs regular classes. When processing thousands of ticks/second, this adds up. |
| `Decimal` not `float` | Floats have rounding errors. `0.1 + 0.2 != 0.3` in IEEE 754. When calculating fees and P&L, these errors compound. Decimal is exact. |
| Nanosecond timestamps | Milliseconds aren't granular enough to measure feed latency or detect which tick arrived first. Nanoseconds give you ~1000x more precision. |
| `sequence` field | Venues assign sequence numbers to messages. If you receive seq 102 after seq 100, you know you missed seq 101 and need to request a snapshot. |

#### Interview Angle

> "We use immutable value objects to guarantee that ticks can't be corrupted as they pass through concurrent processing stages. This is a functional programming principle applied to systems design."

---

### 2. BoundedEventQueue — Backpressure Handling

This is where most naive implementations fail. If your producer (exchange feed) is faster than your consumer (strategy), an unbounded queue will:

1. Grow until you OOM
2. Introduce unbounded latency (old ticks sitting in queue)

```python
class BoundedEventQueue(Generic[T]):
    def __init__(
        self,
        max_size: int = 10000,
        policy: BackpressurePolicy = BackpressurePolicy.DROP_OLDEST,
    ):
```

#### Backpressure Policies

| Policy | Behavior | Use Case |
|--------|----------|----------|
| `BLOCK` | Producer waits until space available | Order queues (can't lose orders) |
| `DROP_OLDEST` | Evict oldest item to make room | Market data (stale data is worthless) |
| `DROP_NEWEST` | Reject incoming item | When you want to preserve historical order |
| `RAISE` | Throw exception | Fail-fast debugging |

#### Why DROP_OLDEST for Ticks

A tick from 500ms ago is not just useless—it's dangerous. Acting on stale prices is how you get adversely selected. By dropping old ticks, we guarantee the strategy always sees the freshest data, even if we're temporarily overwhelmed.

#### Interview Angle

> "Backpressure is the difference between a system that degrades gracefully and one that falls over. We chose drop-oldest semantics for market data because latency is more important than completeness—a stale price is worse than no price."

---

### 3. CentralOrderBook — The State Machine

The order book maintains a **materialized view** of the current market state across venues:

```python
# Structure
{ "SYMBOL": { Venue.KALSHI: tick, Venue.IBKR: tick } }
```

#### Delta vs Snapshot: The Critical Concept

Venues send two types of messages:

- **Snapshots**: Full state ("here's the entire book")
- **Deltas**: Incremental updates ("bid changed from X to Y")

Deltas are efficient but fragile. If you miss one delta (network blip, processing delay), your local state diverges from reality permanently. This is called **delta drift**.

#### Solution: Periodic Snapshot Reconciliation

```python
snapshot_interval_sec: int = 300  # Every 5 minutes
```

Every N minutes, we:

1. Request a full snapshot from the exchange
2. Replace our local state entirely
3. Resume processing deltas

This bounds the maximum time we can be wrong.

#### Interview Angle

> "We treat the order book as an eventually consistent system. Deltas give us low-latency updates, but we periodically reconcile with snapshots to bound our divergence from ground truth. This is similar to how distributed databases use anti-entropy repair."

---

### 4. Timestamp Architecture

We track **two** timestamps for every tick:

```python
timestamp_exchange: int  # When the exchange generated the event
timestamp_local: int     # When we received it
```

#### Why Both?

```
Exchange generates tick    ──────────────────────────►  We receive tick
        t=0                   Network + Processing           t=?
                                   Latency
```

- `timestamp_exchange` tells you when the price actually changed
- `timestamp_local` tells you when you learned about it
- The difference (`latency_ns`) tells you how stale your information is

#### Staleness Check

```python
def is_stale(self, max_age_ns: int = 500_000_000) -> bool:  # 500ms default
    return (time.time_ns() - self.timestamp_local) > max_age_ns
```

Before acting on any tick, we verify it's not stale. Acting on a 500ms-old price in a fast market is suicide.

#### Interview Angle

> "We maintain causal ordering through exchange timestamps but use local timestamps for staleness detection. This lets us reason about both 'when did this happen' and 'how old is my information.'"

---

### 5. Fee Modeling

Arbitrage profit calculation:

```
Gross Edge = Sell Price - Buy Price
Net Edge   = Gross Edge - Buy Fees - Sell Fees - Settlement Fees
```

If you get the fees wrong, you'll execute trades that look profitable but actually lose money.

```python
@dataclass(frozen=True, slots=True)
class FeeSchedule:
    venue: Venue
    maker_fee: Decimal    # Providing liquidity
    taker_fee: Decimal    # Taking liquidity
    per_contract_fee: Decimal
    min_fee: Decimal
    max_fee: Decimal
```

#### Kalshi vs IBKR Fee Structure

| Venue | Maker | Taker | Per-Contract | Notes |
|-------|-------|-------|--------------|-------|
| Kalshi | $0.00 | $0.07 | — | Plus $0.03 settlement on winners |
| IBKR | ~$0.02 | ~$0.05 | — | $1.00 minimum per order |

The asymmetry matters. If you can be the maker (provide liquidity via limit orders) on one leg, you save 7 cents/contract on Kalshi.

#### Interview Angle

> "Fee-aware execution is critical. A 10-cent gross edge sounds profitable until you realize fees eat 7-10 cents. We model maker/taker asymmetry and route orders to minimize total friction."

---

### 6. Position Tracking with P&L Attribution

```python
@dataclass(slots=True)
class Position:
    symbol: str
    venue: Venue
    quantity: int                   # Positive=long, Negative=short
    avg_entry_price: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
```

#### Why Per-Venue Positions?

In arbitrage, you're simultaneously long on one venue and short on another. You need to track them separately to:

1. Enforce per-venue position limits
2. Calculate P&L correctly when positions close at different times
3. Reconcile with each venue's official position reports

#### FIFO vs Average Cost

We use **average cost** accounting:

```python
total_cost = (avg_entry_price * quantity) + (fill_price * fill_size)
new_avg = total_cost / new_quantity
```

This simplifies P&L calculation when you're scaling into and out of positions incrementally.

---

### 7. The Type System as Documentation

The interface definitions serve as executable documentation:

```python
class BaseGateway(ABC):
    @abstractmethod
    async def connect(self) -> None: ...
    
    @abstractmethod
    async def subscribe(self, symbols: list[str]) -> None: ...
    
    @abstractmethod
    async def request_snapshot(self, symbol: str) -> Optional[NormalizedTick]: ...
    
    @abstractmethod
    async def submit_order(self, order: Order) -> Order: ...
```

Every gateway (Kalshi, IBKR, future venues) must implement this interface. This means:

- The rest of the system doesn't care which venue it's talking to
- Adding a new venue is just implementing 6 methods
- You can mock gateways for testing

#### Interview Angle

> "We use abstract base classes to define contracts between components. This gives us compile-time verification that implementations are complete and makes the system venue-agnostic."

---

### 8. Configuration Philosophy

```yaml
# Secrets via environment variables (never committed)
# KALSHI_API_KEY_ID, KALSHI_PRIVATE_KEY, IBKR_ACCOUNT

# Everything else in YAML
risk:
  max_position_per_symbol: 100
  max_daily_loss: 500
  min_edge_bps: 50
```

#### Layered Configuration

1. Hardcoded defaults (safe values)
2. YAML file overrides
3. Environment variables override YAML (for secrets and deployment-specific settings)

#### Safety Switches

```python
enable_trading: bool = False   # Must explicitly enable
paper_trading: bool = True     # Default to paper
```

Live trading requires you to explicitly set `HFT_ENABLE_TRADING=true` AND `HFT_PAPER_TRADING=false`. Two independent flags that both must be flipped. Defense in depth.

---

## Concurrency Model

Everything is **single-threaded async** using `asyncio`.

### Why Not Threads or Multiprocessing?

| Approach | Pros | Cons |
|----------|------|------|
| Threads | Familiar, true parallelism | GIL limits CPU parallelism, race conditions, locks |
| Multiprocessing | True parallelism, no GIL | IPC overhead, complex shared state, serialization costs |
| Asyncio | No locks needed, predictable execution, low overhead | Single core, requires async-aware libraries |

For I/O-bound workloads (which this is—we're waiting on network, not crunching numbers), asyncio gives you:

- **Deterministic execution**: No race conditions because only one coroutine runs at a time
- **Explicit yield points**: You know exactly where context switches happen (`await`)
- **Lower overhead**: No thread creation/destruction, no lock contention

#### Interview Angle

> "We chose cooperative multitasking over preemptive because our bottleneck is network I/O, not CPU. Asyncio eliminates an entire class of concurrency bugs while giving us the throughput we need."

---

## What Would Make This Production-Grade?

Features not yet implemented that a real HFT system would need:

| Feature | Why It Matters |
|---------|----------------|
| **Metrics/Monitoring** | Prometheus/Grafana integration for real-time dashboards |
| **Circuit Breakers** | Auto-disable trading if error rate spikes |
| **Replay System** | Record all ticks to replay and debug issues post-hoc |
| **Hot Path Optimization** | Move signal detection to Cython/Rust for microsecond gains |
| **Colocation** | Physical proximity to exchange matching engines |
| **FPGA/Kernel Bypass** | For true HFT (sub-microsecond), you need hardware acceleration |

---

## How to Talk About This in Interviews

### 1. Start with the Problem

> "I built a cross-venue arbitrage system for event prediction markets. The core challenge is maintaining consistent state across two asynchronous data feeds while executing with sub-second latency."

### 2. Explain a Design Decision

> "We use immutable data structures for market data because it eliminates a class of concurrency bugs. When a tick flows through the pipeline, no component can accidentally mutate it."

### 3. Show You Understand Trade-offs

> "We chose asyncio over threading because we're I/O-bound, not CPU-bound. The GIL isn't a problem when you're waiting on network 99% of the time, and single-threaded async eliminates lock contention entirely."

### 4. Demonstrate Systems Thinking

> "The order book uses eventual consistency—deltas for low-latency updates, periodic snapshots for drift correction. It's the same pattern distributed databases use for replica synchronization."

---

## Project Structure

```
hft_lite/
├── __init__.py              # Package exports
├── main.py                  # Application entry point with graceful shutdown
├── pyproject.toml           # Dependencies & tooling config
├── config/
│   └── config.sample.yaml   # Template configuration
├── core/
│   ├── types.py             # NormalizedTick, Order, Position, ArbitrageSignal
│   ├── interfaces.py        # BaseGateway, BaseNormalizer, BaseOrderBook
│   ├── event_bus.py         # BoundedEventQueue with backpressure
│   └── config.py            # SystemConfig with YAML + env var loading
├── utils/
│   ├── logging.py           # Nanosecond-precision logging, TickLogger
│   └── helpers.py           # Time utils, ID generation, RateLimiter
├── gateways/                # Exchange connectivity (Kalshi, IBKR)
├── strategy/                # Arbitrage detection and signal generation
├── execution/               # Order management and position tracking
└── tests/                   # Test suite
```

---

## Key Metrics to Track

| Metric | Target | Why |
|--------|--------|-----|
| Tick-to-signal latency | <1ms | Time from receiving tick to generating signal |
| Signal-to-order latency | <5ms | Time from signal to order submission |
| Fill rate | >80% | Percentage of signals that result in fills |
| Slippage | <5 bps | Difference between expected and actual fill price |
| Queue depth | <100 | Items waiting in event queue |
| Snapshot drift | 0 | Deltas missed between snapshots |

---

## Dependencies

```toml
[project]
dependencies = [
    "websockets>=12.0",      # Kalshi WebSocket
    "aiohttp>=3.9.0",        # HTTP client
    "ib_insync>=0.9.86",     # IBKR TWS API
    "cryptography>=41.0.0",  # Kalshi auth (Ed25519)
    "pyjwt>=2.8.0",          # JWT tokens
    "pyyaml>=6.0",           # Configuration
]
```

---

## License

MIT

---

*This document is part of the HFT-Lite project portfolio.*