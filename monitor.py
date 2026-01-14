import os
import time
import json
import datetime
import sqlite3
import psycopg2
from decimal import Decimal
from typing import List, Dict, Any

# Import your library
from kraken_futures import KrakenFuturesApi

# --- Configuration ---
API_KEY = os.getenv("KRAKEN_FUTURES_KEY")
API_SECRET = os.getenv("KRAKEN_FUTURES_SECRET")
DATABASE_URL = os.getenv("DATABASE_URL")
VOLUME_DIR = os.getenv("VOLUME_DIR", "/mnt/data")
DB_PATH = os.path.join(VOLUME_DIR, "history.db")
INTERVAL_SECONDS = 20
RETENTION_DAYS = 7

# --- Database Management ---
def init_db():
    """Initializes the SQLite database for historical tracking."""
    # Ensure volume directory exists
    if not os.path.exists(VOLUME_DIR):
        os.makedirs(VOLUME_DIR, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 1. Equity History
    c.execute('''CREATE TABLE IF NOT EXISTS equity_log (
                    timestamp DATETIME,
                    equity REAL
                )''')
    
    # 2. Positions History
    c.execute('''CREATE TABLE IF NOT EXISTS position_log (
                    timestamp DATETIME,
                    symbol TEXT,
                    size REAL,
                    side TEXT
                )''')

    # 3. Signals History
    c.execute('''CREATE TABLE IF NOT EXISTS signal_log (
                    timestamp DATETIME,
                    asset TEXT,
                    tf TEXT,
                    signal_val INTEGER
                )''')
    
    # Indexes for faster plotting queries
    c.execute('CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity_log (timestamp)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_pos_ts ON position_log (timestamp)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_sig_ts ON signal_log (timestamp)')
    
    conn.commit()
    conn.close()

def prune_old_data():
    """Deletes data older than RETENTION_DAYS."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=RETENTION_DAYS)
        
        c.execute("DELETE FROM equity_log WHERE timestamp < ?", (cutoff,))
        c.execute("DELETE FROM position_log WHERE timestamp < ?", (cutoff,))
        c.execute("DELETE FROM signal_log WHERE timestamp < ?", (cutoff,))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Prune Error] {e}")

def save_history_snapshot(portfolio, positions, signals):
    """Parses raw API data and inserts into SQLite."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.datetime.utcnow()

    # 1. Log Equity (Corrected Path)
    # Path: portfolio -> accounts -> flex -> marginEquity
    try:
        total_equity = 0.0
        
        # Navigate safely to ['accounts']['flex']
        accounts = portfolio.get("accounts", {})
        if isinstance(accounts, dict):
            flex_wallet = accounts.get("flex", {})
            # Get marginEquity, default to 0 if missing
            total_equity = float(flex_wallet.get("marginEquity", 0))
        
        c.execute("INSERT INTO equity_log VALUES (?, ?)", (now, total_equity))
    except Exception as e:
        print(f"[Data Error] Could not parse equity: {e}")

    # 2. Log Positions
    try:
        open_positions = positions.get("openPositions", [])
        for pos in open_positions:
            c.execute("INSERT INTO position_log VALUES (?, ?, ?, ?)", 
                      (now, pos.get("symbol"), float(pos.get("size", 0)), pos.get("side")))
    except Exception as e:
        print(f"[Data Error] Could not parse positions: {e}")

    # 3. Log Signals
    try:
        for sig in signals:
            c.execute("INSERT INTO signal_log VALUES (?, ?, ?, ?)", 
                      (now, sig.get("asset"), sig.get("tf"), int(sig.get("signal_val", 0))))
    except Exception as e:
        print(f"[Data Error] Could not parse signals: {e}")

    conn.commit()
    conn.close()

# --- Helper: JSON Encoder ---
class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

def save_to_volume(filename: str, data: Any):
    """Saves current snapshot JSON for the live dashboard view."""
    filepath = os.path.join(VOLUME_DIR, filename)
    wrapper = { "last_updated": datetime.datetime.utcnow().isoformat(), "data": data }
    try:
        with open(filepath, "w") as f:
            json.dump(wrapper, f, cls=CustomEncoder, indent=2)
    except Exception as e:
        print(f"[Error] Failed to write {filename}: {e}")

def fetch_signals_from_db() -> List[Dict]:
    if not DATABASE_URL: return []
    query = "SELECT asset, tf, signal_val, updated_at FROM live_matrix;"
    results = []
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        for row in rows:
            results.append({ "asset": row[0], "tf": row[1], "signal_val": row[2], "updated_at": row[3] })
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[DB Error] Could not fetch signals: {e}")
        return []
    return results

def main():
    print("--- Starting Kraken Futures Monitor (with History) ---")
    
    # Initialize SQLite
    init_db()

    kraken = KrakenFuturesApi(API_KEY, API_SECRET) if (API_KEY and API_SECRET) else None

    while True:
        loop_start = time.time()
        
        portfolio_data = {}
        positions_data = {}
        signals_data = []

        try:
            # 1. Fetch Data
            if kraken:
                portfolio_data = kraken.get_accounts()
                positions_data = kraken.get_open_positions()
            
            signals_data = fetch_signals_from_db()

            # 2. Save Snapshots (for current table view)
            save_to_volume("portfolio_snapshot.json", portfolio_data)
            save_to_volume("positions_snapshot.json", positions_data)
            save_to_volume("signals_snapshot.json", signals_data)

            # 3. Save History (for plots)
            save_history_snapshot(portfolio_data, positions_data, signals_data)
            
            # 4. Prune old data
            prune_old_data()

        except Exception as e:
            print(f"[Loop Error] {e}")

        elapsed = time.time() - loop_start
        time.sleep(max(0, INTERVAL_SECONDS - elapsed))

if __name__ == "__main__":
    main()
