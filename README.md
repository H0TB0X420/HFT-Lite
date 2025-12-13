# HFT-Lite

Cross-venue arbitrage engine for prediction markets.

## Overview

HFT-Lite exploits pricing inefficiencies between prediction market platforms (Kalshi, Interactive Brokers ForecastEx) by detecting opportunities where complementary binary contracts can be purchased across venues for less than the guaranteed $1.00 settlement payout.

### Key Insight

Unlike traditional securities arbitrage, prediction markets allow a "buy-both-sides" strategy: purchase YES on one exchange and NO on another. If the combined cost is less than $1.00 minus fees, profit is locked in regardless of outcome.

### Results

- Coming Soon

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Upcoming Improvements
- Additional Gateways Polymarket, Gemini Titan.
- Advanced Strategies: Conditional probability model, Implied probability surface, Bayesian network, Time decay arbitrage 
- Exectution: Parallel order placement, Dynamic position sizing based on Kelly criterion
- Infrastructure: WebSocket reconnection with exponential backoff, Dashboard for real-time monitoring
- Risk Management: Exposure limits per event category, Max drawdown limits
