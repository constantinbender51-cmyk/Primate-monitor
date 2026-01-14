import os
import time
import json
import datetime
import psycopg2
from decimal import Decimal
from typing import List, Dict, Any

# Import the provided library
from kraken_futures import KrakenFuturesApi

# --- Configuration ---
API_KEY = os.getenv("KRAKEN_FUTURES_KEY")
API_SECRET = os.getenv("KRAKEN_FUTURES_SECRET")
DATABASE_URL = os.getenv("DATABASE_URL")
VOLUME_DIR = os.getenv("VOLUME_DIR", "/mnt/data")

# Settings
INTERVAL_SECONDS = 20
HISTORY_FILE = "history.json"
MAX_HISTORY_DAYS = 3
MAX_HISTORY_POINTS = (MAX_HISTORY_DAYS * 24 * 60 * 60) // INTERVAL_SECONDS

class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

def load_history():
    filepath = os.path.join(VOLUME_DIR, HISTORY_FILE)
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def save_history(history_data):
    if not os.path.exists(VOLUME_DIR):
        os.makedirs(VOLUME_DIR, exist_ok=True)
    
    filepath = os.path.join(VOLUME_DIR, HISTORY_FILE)
    
    # Prune old data (keep last N points)
    if len(history_data) > MAX_HISTORY_POINTS:
        history_data = history_data[-MAX_HISTORY_POINTS:]
        
    try:
        with open(filepath, "w") as f:
            json.dump(history_data, f, cls=CustomEncoder)
        print(f"[Saved] History updated. Total points: {len(history_data)}")
    except Exception as e:
        print(f"[Error] Failed to write history: {e}")

def fetch_signals_from_db() -> Dict[str, Any]:
    """Fetches signals and returns a dict keyed by asset for easier mapping."""
    if not DATABASE_URL:
        return {}

    query = "SELECT asset, tf, signal_val, updated_at FROM live_matrix;"
    signals = {}
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        
        for row in rows:
            # Store by asset name (e.g., 'BTCUSDT': { ... })
            signals[row[0]] = {
                "tf": row[1],
                "signal_val": row[2],
                "updated_at": row[3]
            }
            
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[DB Error] {e}")
        
    return signals

def extract_margin_equity(accounts_response):
    """Finds the marginEquity in the flex account."""
    # Response structure usually: {'accounts': [{'type': 'flex', 'balances': {...}, 'auxiliary': {'marginEquity': 123...}}]}
    try:
        if "accounts" in accounts_response:
            for acc in accounts_response["accounts"]:
                if acc.get("type") == "flex":
                    return float(acc.get("auxiliary", {}).get("marginEquity", 0.0))
        return 0.0
    except:
        return 0.0

def main():
    print("--- Starting Historical Monitor ---")
    
    kraken = None
    if API_KEY and API_SECRET:
        kraken = KrakenFuturesApi(API_KEY, API_SECRET)

    # Load existing history so we don't lose data on restart
    history = load_history()

    while True:
        loop_start = time.time()
        timestamp = datetime.datetime.utcnow().isoformat()
        
        entry = {
            "timestamp": timestamp,
            "margin_equity": 0.0,
            "positions": [],
            "signals": {}
        }
        
        try:
            # 1. Fetch Equity
            if kraken:
                accounts = kraken.get_accounts()
                entry["margin_equity"] = extract_margin_equity(accounts)

            # 2. Fetch Positions
            if kraken:
                # get_open_positions returns {'openPositions': [...]}
                pos_data = kraken.get_open_positions()
                entry["positions"] = pos_data.get("openPositions", [])

            # 3. Fetch Signals
            entry["signals"] = fetch_signals_from_db()
            
            # Append and Save
            history.append(entry)
            save_history(history)

        except Exception as e:
            print(f"[Loop Error] {e}")

        elapsed = time.time() - loop_start
        sleep_time = max(0, INTERVAL_SECONDS - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)

if __name__ == "__main__":
    main()
