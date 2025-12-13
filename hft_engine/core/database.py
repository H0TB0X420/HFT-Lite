"""SQLite database for logging and P&L tracking."""
import aiosqlite
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .arbitrage import ArbitrageOpportunity


@dataclass
class PnLSummary:
    """P&L summary statistics."""
    total_opportunities: int
    total_executed: int
    total_cost: Decimal
    total_payout: Decimal
    total_fees: Decimal
    gross_profit: Decimal
    net_profit: Decimal
    win_rate: float


class Database:
    """Async SQLite database for HFT engine."""
    
    def __init__(self, db_path: Path | str = "hft_engine.db"):
        self._db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None
    
    async def connect(self) -> None:
        """Open database connection and initialize tables."""
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._init_tables()
    
    async def close(self) -> None:
        """Close database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
    
    async def _init_tables(self) -> None:
        """Initialize database tables."""
        # Opportunities table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS opportunities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                session_id TEXT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                kalshi_side TEXT NOT NULL,
                kalshi_price REAL NOT NULL,
                ibkr_side TEXT NOT NULL,
                ibkr_price REAL NOT NULL,
                total_cost REAL NOT NULL,
                gross_profit REAL NOT NULL,
                kalshi_fee REAL NOT NULL,
                ibkr_fee REAL NOT NULL,
                total_fees REAL NOT NULL,
                slippage_buffer REAL NOT NULL,
                net_profit REAL NOT NULL,
                profit_margin_pct REAL NOT NULL,
                executed INTEGER NOT NULL DEFAULT 0
            )
        """)
        
        # Spreads table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS spreads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                session_id TEXT,
                symbol TEXT NOT NULL,
                kalshi_yes_ask REAL,
                kalshi_no_ask REAL,
                kalshi_sum REAL,
                ibkr_yes_ask REAL,
                ibkr_no_ask REAL,
                ibkr_sum REAL,
                combo_yes_kalshi_no_ibkr REAL,
                combo_no_kalshi_yes_ibkr REAL
            )
        """)
        
        # Executions table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                session_id TEXT,
                symbol TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                kalshi_order_id TEXT,
                kalshi_side TEXT NOT NULL,
                kalshi_limit_price REAL NOT NULL,
                kalshi_fill_price REAL,
                kalshi_fill_quantity INTEGER DEFAULT 0,
                kalshi_filled INTEGER NOT NULL DEFAULT 0,
                ibkr_order_id INTEGER,
                ibkr_side TEXT NOT NULL,
                ibkr_con_id INTEGER,
                ibkr_limit_price REAL NOT NULL,
                ibkr_fill_price REAL,
                ibkr_fill_quantity INTEGER DEFAULT 0,
                ibkr_filled INTEGER NOT NULL DEFAULT 0,
                total_cost REAL NOT NULL,
                expected_payout REAL NOT NULL,
                actual_fees REAL NOT NULL,
                net_profit REAL NOT NULL,
                success INTEGER NOT NULL DEFAULT 0,
                rolled_back INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                rollback_details TEXT
            )
        """)
        
        # Positions table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                session_id TEXT,
                symbol TEXT NOT NULL,
                exchange TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                avg_cost REAL NOT NULL,
                UNIQUE(symbol, exchange, side)
            )
        """)
        
        # Create indexes
        await self._conn.execute("CREATE INDEX IF NOT EXISTS idx_opp_timestamp ON opportunities(timestamp)")
        await self._conn.execute("CREATE INDEX IF NOT EXISTS idx_opp_symbol ON opportunities(symbol)")
        await self._conn.execute("CREATE INDEX IF NOT EXISTS idx_opp_session ON opportunities(session_id)")
        await self._conn.execute("CREATE INDEX IF NOT EXISTS idx_spread_timestamp ON spreads(timestamp)")
        await self._conn.execute("CREATE INDEX IF NOT EXISTS idx_exec_timestamp ON executions(timestamp)")
        await self._conn.execute("CREATE INDEX IF NOT EXISTS idx_exec_session ON executions(session_id)")
        
        await self._conn.commit()
    
    async def log_opportunity(
        self,
        opp: ArbitrageOpportunity,
        executed: bool = False,
        session_id: str | None = None,
    ) -> int:
        """Log an arbitrage opportunity."""
        timestamp = datetime.utcnow().isoformat()
        
        cursor = await self._conn.execute("""
            INSERT INTO opportunities (
                timestamp, session_id, symbol, side, quantity,
                kalshi_side, kalshi_price, ibkr_side, ibkr_price,
                total_cost, gross_profit, kalshi_fee, ibkr_fee,
                total_fees, slippage_buffer, net_profit, profit_margin_pct,
                executed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp,
            session_id,
            opp.symbol,
            opp.side.value,
            opp.quantity,
            opp.kalshi_side,
            float(opp.kalshi_price),
            opp.ibkr_side,
            float(opp.ibkr_price),
            float(opp.total_cost),
            float(opp.gross_profit),
            float(opp.kalshi_fee),
            float(opp.ibkr_fee),
            float(opp.total_fees),
            float(opp.slippage_buffer),
            float(opp.net_profit),
            float(opp.profit_margin),
            1 if executed else 0,
        ))
        await self._conn.commit()
        return cursor.lastrowid
    
    async def log_spread(
        self,
        symbol: str,
        kalshi_yes_ask: Decimal | None,
        kalshi_no_ask: Decimal | None,
        ibkr_yes_ask: Decimal | None,
        ibkr_no_ask: Decimal | None,
        session_id: str | None = None,
    ) -> int:
        """Log a spread snapshot."""
        timestamp = datetime.utcnow().isoformat()
        
        kalshi_sum = None
        if kalshi_yes_ask is not None and kalshi_no_ask is not None:
            kalshi_sum = float(kalshi_yes_ask + kalshi_no_ask)
        
        ibkr_sum = None
        if ibkr_yes_ask is not None and ibkr_no_ask is not None:
            ibkr_sum = float(ibkr_yes_ask + ibkr_no_ask)
        
        combo_yes_kalshi = None
        combo_no_kalshi = None
        if all(v is not None for v in [kalshi_yes_ask, kalshi_no_ask, ibkr_yes_ask, ibkr_no_ask]):
            combo_yes_kalshi = float(kalshi_yes_ask + ibkr_no_ask)
            combo_no_kalshi = float(kalshi_no_ask + ibkr_yes_ask)
        
        cursor = await self._conn.execute("""
            INSERT INTO spreads (
                timestamp, session_id, symbol,
                kalshi_yes_ask, kalshi_no_ask, kalshi_sum,
                ibkr_yes_ask, ibkr_no_ask, ibkr_sum,
                combo_yes_kalshi_no_ibkr, combo_no_kalshi_yes_ibkr
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp,
            session_id,
            symbol,
            float(kalshi_yes_ask) if kalshi_yes_ask else None,
            float(kalshi_no_ask) if kalshi_no_ask else None,
            kalshi_sum,
            float(ibkr_yes_ask) if ibkr_yes_ask else None,
            float(ibkr_no_ask) if ibkr_no_ask else None,
            ibkr_sum,
            combo_yes_kalshi,
            combo_no_kalshi,
        ))
        await self._conn.commit()
        return cursor.lastrowid
    
    async def log_execution(
        self,
        result: "ExecutionResult",
        session_id: str | None = None,
    ) -> int:
        """Log an execution result."""
        from .executor import ExecutionResult
        
        cursor = await self._conn.execute("""
            INSERT INTO executions (
                timestamp, session_id, symbol, quantity,
                kalshi_order_id, kalshi_side, kalshi_limit_price,
                kalshi_fill_price, kalshi_fill_quantity, kalshi_filled,
                ibkr_order_id, ibkr_side, ibkr_con_id, ibkr_limit_price,
                ibkr_fill_price, ibkr_fill_quantity, ibkr_filled,
                total_cost, expected_payout, actual_fees, net_profit,
                success, rolled_back, error, rollback_details
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.timestamp,
            session_id,
            result.symbol,
            result.quantity,
            result.kalshi_order_id,
            result.kalshi_side,
            float(result.kalshi_limit_price),
            float(result.kalshi_fill_price) if result.kalshi_fill_price else None,
            result.kalshi_fill_quantity,
            1 if result.kalshi_filled else 0,
            result.ibkr_order_id,
            result.ibkr_side,
            result.ibkr_con_id,
            float(result.ibkr_limit_price),
            float(result.ibkr_fill_price) if result.ibkr_fill_price else None,
            result.ibkr_fill_quantity,
            1 if result.ibkr_filled else 0,
            float(result.total_cost),
            float(result.expected_payout),
            float(result.actual_fees),
            float(result.net_profit),
            1 if result.success else 0,
            1 if result.rolled_back else 0,
            result.error,
            result.rollback_details,
        ))
        await self._conn.commit()
        return cursor.lastrowid
    
    async def update_position(
        self,
        symbol: str,
        exchange: str,
        side: str,
        quantity: int,
        avg_cost: Decimal,
        session_id: str | None = None,
    ) -> None:
        """Update or insert a position."""
        timestamp = datetime.utcnow().isoformat()
        
        await self._conn.execute("""
            INSERT INTO positions (timestamp, session_id, symbol, exchange, side, quantity, avg_cost)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, exchange, side) DO UPDATE SET
                timestamp = excluded.timestamp,
                quantity = excluded.quantity,
                avg_cost = excluded.avg_cost
        """, (
            timestamp,
            session_id,
            symbol,
            exchange,
            side,
            quantity,
            float(avg_cost),
        ))
        await self._conn.commit()
    
    async def get_pnl_summary(self, session_id: str | None = None) -> PnLSummary:
        """Get P&L summary for a session or all time."""
        if session_id:
            cursor = await self._conn.execute("""
                SELECT
                    COUNT(*) as total_opportunities,
                    SUM(executed) as total_executed,
                    SUM(CASE WHEN executed = 1 THEN total_cost ELSE 0 END) as total_cost,
                    SUM(CASE WHEN executed = 1 THEN quantity ELSE 0 END) as total_payout,
                    SUM(CASE WHEN executed = 1 THEN total_fees ELSE 0 END) as total_fees,
                    SUM(CASE WHEN executed = 1 THEN gross_profit ELSE 0 END) as gross_profit,
                    SUM(CASE WHEN executed = 1 THEN net_profit ELSE 0 END) as net_profit
                FROM opportunities
                WHERE session_id = ?
            """, (session_id,))
        else:
            cursor = await self._conn.execute("""
                SELECT
                    COUNT(*) as total_opportunities,
                    SUM(executed) as total_executed,
                    SUM(CASE WHEN executed = 1 THEN total_cost ELSE 0 END) as total_cost,
                    SUM(CASE WHEN executed = 1 THEN quantity ELSE 0 END) as total_payout,
                    SUM(CASE WHEN executed = 1 THEN total_fees ELSE 0 END) as total_fees,
                    SUM(CASE WHEN executed = 1 THEN gross_profit ELSE 0 END) as gross_profit,
                    SUM(CASE WHEN executed = 1 THEN net_profit ELSE 0 END) as net_profit
                FROM opportunities
            """)
        
        row = await cursor.fetchone()
        
        total_executed = row["total_executed"] or 0
        total_opportunities = row["total_opportunities"] or 0
        
        return PnLSummary(
            total_opportunities=total_opportunities,
            total_executed=total_executed,
            total_cost=Decimal(str(row["total_cost"] or 0)),
            total_payout=Decimal(str(row["total_payout"] or 0)),
            total_fees=Decimal(str(row["total_fees"] or 0)),
            gross_profit=Decimal(str(row["gross_profit"] or 0)),
            net_profit=Decimal(str(row["net_profit"] or 0)),
            win_rate=total_executed / total_opportunities if total_opportunities > 0 else 0.0,
        )
    
    async def get_executions(self, session_id: str | None = None, limit: int = 100) -> list[dict]:
        """Get recent executions."""
        if session_id:
            cursor = await self._conn.execute("""
                SELECT * FROM executions
                WHERE session_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (session_id, limit))
        else:
            cursor = await self._conn.execute("""
                SELECT * FROM executions
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
        
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]