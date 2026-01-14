import os
import time
import json
import datetime
import psycopg2
from decimal import Decimal
from typing import List, Dict, Any

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

# We prioritize this timeframe for the dashboard plot
PREFERRED_TIMEFRAME = "15m"

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
    
    if len(history_data) > MAX_HISTORY_POINTS:
        history_data = history_data[-MAX_HISTORY_POINTS:]
        
    try:
        with open(filepath, "w") as f:
            json.dump(history_data, f, cls=CustomEncoder)
        # print(f"[Saved] History updated. Points: {len(history_data)}") 
    except Exception as e:
        print(f"[Error] Failed to write history: {e}")

def fetch_signals_from_db() -> Dict[str, Any]:
    """
    Fetches signals. Returns a simplified dict: {'BTCUSDT': signal_value, ...}
    Prioritizes PREFERRED_TIMEFRAME (15m) to avoid overwriting.
    """
    if not DATABASE_URL:
        return {}

    query = "SELECT asset, tf, signal_val, updated_at FROM live_matrix;"
    signals = {}
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        cursor.execute(query)
        rows = cursor.fetchall()
        
        # Temp storage to find best TF
        temp_data = []
        for row in rows:
            temp_data.append({"asset": row[0], "tf": row[1], "val": row[2]})
            
        # Filter for preferred TF, fallback to others if needed
        for item in temp_data:
            asset = item["asset"]
            tf = item["tf"]
            
            # If we haven't seen this asset yet, take it
            if asset not in signals:
                signals[asset] = item
            
            # If this is our preferred TF, strictly overwrite whatever we had
            if tf == PREFERRED_TIMEFRAME:
                signals[asset] = item

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"[DB Error] {e}")
        
    return signals

def extract_margin_equity(accounts_response):
    """
    Finds marginEquity in the multiCollateralMarginAccount.
    """
    # 1. Check if 'accounts' key exists
    if not accounts_response or "accounts" not in accounts_response:
        return 0.0

    acc_list = accounts_response["accounts"]
    
    # 2. Iterate to find the correct type
    for acc in acc_list:
        # Check for the type defined in schema
        if acc.get("type") == "multiCollateralMarginAccount":
            # 3. Extract direct field
            return float(acc.get("marginEquity", 0.0))
            
    return 0.0

def main():
    print("--- Starting Monitor (Fixed) ---")
    
    kraken = None
    if API_KEY and API_SECRET:
        kraken = KrakenFuturesApi(API_KEY, API_SECRET)

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
            if kraken:
                # 1. Fetch Equity
                accounts = kraken.get_accounts()
                entry["margin_equity"] = extract_margin_equity(accounts)

                # 2. Fetch Positions
                pos_data = kraken.get_open_positions()
                entry["positions"] = pos_data.get("openPositions", [])

            # 3. Fetch Signals
            entry["signals"] = fetch_signals_from_db()
            
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
