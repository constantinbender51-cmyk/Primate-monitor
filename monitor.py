import os
import time
import json
import datetime
import psycopg2
from decimal import Decimal
from typing import List, Dict, Any

# Import the provided library (must be in root dir)
from kraken_futures import KrakenFuturesApi

# --- Configuration ---
# API Credentials
API_KEY = os.getenv("KRAKEN_FUTURES_KEY")
API_SECRET = os.getenv("KRAKEN_FUTURES_SECRET")

# Database URL (Railway provides this automatically)
DATABASE_URL = os.getenv("DATABASE_URL")

# Volume Directory (Where to save files)
# Ensure this matches your Railway Volume mount path. Defaulting to 'data' folder.
VOLUME_DIR = os.getenv("VOLUME_DIR", "/app/data")

# Loop Interval
INTERVAL_SECONDS = 20

# --- Helper: JSON Encoder for Dates and Decimals ---
class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

def save_to_volume(filename: str, data: Any):
    """Saves data as JSON to the configured volume directory."""
    if not os.path.exists(VOLUME_DIR):
        os.makedirs(VOLUME_DIR, exist_ok=True)
    
    filepath = os.path.join(VOLUME_DIR, filename)
    
    # Add a timestamp to the data structure
    wrapper = {
        "last_updated": datetime.datetime.utcnow().isoformat(),
        "data": data
    }
    
    try:
        with open(filepath, "w") as f:
            json.dump(wrapper, f, cls=CustomEncoder, indent=2)
        print(f"[Saved] {filename}")
    except Exception as e:
        print(f"[Error] Failed to write {filename}: {e}")

def fetch_signals_from_db() -> List[Dict]:
    """Fetches signals from the live_matrix table in Postgres."""
    query = "SELECT asset, tf, signal_val, updated_at FROM live_matrix;"
    results = []
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        
        for row in rows:
            results.append({
                "asset": row[0],
                "tf": row[1],
                "signal_val": row[2],
                "updated_at": row[3]
            })
            
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[DB Error] Could not fetch signals: {e}")
        return [] # Return empty list on failure to keep loop alive
        
    return results

def main():
    print("--- Starting Kraken Futures Monitor ---")
    print(f"Volume Path: {VOLUME_DIR}")
    
    if not API_KEY or not API_SECRET:
        print("WARNING: API Credentials not found in environment variables.")
        return

    kraken = KrakenFuturesApi(API_KEY, API_SECRET)

    while True:
        loop_start = time.time()
        
        try:
            # 1. Fetch Portfolio Value (Accounts)
            # This returns balances, auxiliary info, and total equity
            accounts_data = kraken.get_accounts()
            
            # Extract useful summary if possible, or save raw
            # 'accounts' key usually contains the list of wallet balances
            save_to_volume("portfolio_snapshot.json", accounts_data)

            # 2. Fetch Open Positions
            positions_data = kraken.get_open_positions()
            save_to_volume("positions_snapshot.json", positions_data)

            # 3. Fetch Signals from DB
            signals_data = fetch_signals_from_db()
            save_to_volume("signals_snapshot.json", signals_data)

        except Exception as e:
            print(f"[Loop Error] An unexpected error occurred: {e}")

        # Sleep logic to maintain roughly 20s interval
        elapsed = time.time() - loop_start
        sleep_time = max(0, INTERVAL_SECONDS - elapsed)
        
        print(f"Sleeping for {sleep_time:.2f}s...")
        time.sleep(sleep_time)

if __name__ == "__main__":
    main()
