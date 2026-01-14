import http.server
import json
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

# Configuration
PORT = int(os.environ.get("PORT", 8080))
DATA_DIR = os.environ.get("VOLUME_DIR", "/mnt/data/")
HISTORY_FILE = "history.json"

class RequestHandler(http.server.BaseHTTPRequestHandler):
    def _read_history(self):
        filepath = os.path.join(DATA_DIR, HISTORY_FILE)
        if not os.path.exists(filepath):
            return []
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except:
            return []

    def _get_signal_for_symbol(self, kraken_symbol, signals_snapshot):
        """
        Maps Kraken Symbols (ff_xbtusd, pf_xrpusd) to DB Assets (BTCUSDT, ETHUSDT)
        """
        ks = kraken_symbol.lower()
        db_asset = None

        # --- Mapping Logic ---
        if "xbt" in ks or "btc" in ks:
            db_asset = "BTCUSDT"
        elif "eth" in ks:
            db_asset = "ETHUSDT"
        elif "xrp" in ks:
            db_asset = "XRPUSDT"
        elif "sol" in ks:
            db_asset = "SOLUSDT"
        elif "ltc" in ks:
            db_asset = "LTCUSDT"
        
        # If we found a map, retrieve the value
        if db_asset and db_asset in signals_snapshot:
            # The monitor saves the whole object: {'val': 0, 'tf': '15m', ...}
            return float(signals_snapshot[db_asset].get("val", 0))
        
        return 0.0

    def _generate_plots(self, history):
        if not history:
            return []

        timestamps = []
        equity = []
        assets_data = {} 

        for entry in history:
            try:
                ts = datetime.fromisoformat(entry["timestamp"])
                timestamps.append(ts)
                equity.append(entry.get("margin_equity", 0))

                current_positions = entry.get("positions", [])
                current_signals = entry.get("signals", {})

                # Track symbols found in this entry
                entry_symbols = set()

                for pos in current_positions:
                    sym = pos['symbol']
                    entry_symbols.add(sym)
                    
                    if sym not in assets_data:
                        assets_data[sym] = {'times': [], 'sizes': [], 'signals': []}
                    
                    assets_data[sym]['times'].append(ts)
                    assets_data[sym]['sizes'].append(float(pos.get('size', 0)))
                    
                    # Get mapped signal
                    sig_val = self._get_signal_for_symbol(sym, current_signals)
                    assets_data[sym]['signals'].append(sig_val)

            except Exception as e:
                continue

        # --- Plotting ---
        plot_files = []

        # 1. Equity Plot
        if timestamps:
            plt.figure(figsize=(10, 5))
            plt.plot(timestamps, equity, label='Margin Equity (USD)', color='#569cd6', linewidth=2)
            plt.title(f"Portfolio Value (Last {len(timestamps)} points)")
            plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            plt.grid(True, which='both', linestyle='--', linewidth=0.5, color='#444')
            plt.legend()
            
            # Dynamic Y-axis limits to make small moves visible
            if equity:
                min_eq = min(equity) * 0.999
                max_eq = max(equity) * 1.001
                plt.ylim(min_eq, max_eq)

            plt.tight_layout()
            eq_filename = "plot_equity.png"
            plt.savefig(os.path.join(DATA_DIR, eq_filename), facecolor='#1e1e1e', edgecolor='none')
            plt.close()
            plot_files.append(("Portfolio Equity", eq_filename))

        # 2. Asset Plots
        for symbol, data in assets_data.items():
            if not data['times']: continue
            
            # Filter out flat lines if size is 0 (optional, but keeps it clean)
            if all(s == 0 for s in data['sizes']): continue

            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True, gridspec_kw={'height_ratios': [2, 1]})
            
            # Position Size
            ax1.plot(data['times'], data['sizes'], color='#4ec9b0', linewidth=2, label=f'Size: {symbol}')
            ax1.set_title(f"{symbol} Breakdown")
            ax1.set_ylabel("Position Size")
            ax1.grid(True, linestyle='--', alpha=0.3)
            ax1.legend(loc='upper left')

            # Signal
            ax2.step(data['times'], data['signals'], where='post', color='#ce9178', linewidth=2, label='Signal (15m)')
            ax2.set_ylabel("Signal")
            ax2.set_yticks([-1, 0, 1]) 
            ax2.grid(True, linestyle='--', alpha=0.3)
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            
            # Dark Mode Styling
            for ax in [ax1, ax2]:
                ax.set_facecolor('#252526')
                ax.tick_params(colors='#d4d4d4')
                ax.yaxis.label.set_color('#d4d4d4')
                ax.xaxis.label.set_color('#d4d4d4')
                ax.title.set_color('#d4d4d4')
                for spine in ax.spines.values():
                    spine.set_color('#555')

            fig.patch.set_facecolor('#1e1e1e')
            plt.tight_layout()
            
            filename = f"plot_{symbol}.png"
            plt.savefig(os.path.join(DATA_DIR, filename), facecolor='#1e1e1e')
            plt.close()
            plot_files.append((f"Asset: {symbol}", filename))

        return plot_files

    def do_GET(self):
        if self.path.endswith(".png"):
            filepath = os.path.join(DATA_DIR, os.path.basename(self.path))
            if os.path.exists(filepath):
                self.send_response(200)
                self.send_header('Content-type', 'image/png')
                self.end_headers()
                with open(filepath, 'rb') as f:
                    self.wfile.write(f.read())
                return

        if self.path == "/":
            history = self._read_history()
            plots = self._generate_plots(history)
            
            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Kraken Monitor</title>
                <meta http-equiv="refresh" content="20">
                <style>
                    body { font-family: sans-serif; background: #1e1e1e; color: #ccc; padding: 20px; }
                    .card { background: #252526; padding: 15px; margin-bottom: 20px; border: 1px solid #333; }
                    img { max-width: 100%; height: auto; border: 1px solid #444; }
                </style>
            </head>
            <body>
            """
            
            if not plots:
                html += "<div class='card'>Waiting for data... (approx 20s)</div>"
            else:
                for title, fname in plots:
                    html += f"<div class='card'><h3>{title}</h3><img src='/{fname}'></div>"

            html += "</body></html>"
            
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_error(404)

def run():
    server_address = ("", PORT)
    httpd = http.server.ThreadingHTTPServer(server_address, RequestHandler)
    httpd.serve_forever()

if __name__ == "__main__":
    run()
