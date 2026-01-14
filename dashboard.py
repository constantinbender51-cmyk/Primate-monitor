import http.server
import json
import os
import io
import matplotlib
# Set backend to Agg to avoid needing a GUI
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

    def _generate_plots(self, history):
        if not history:
            return None

        # --- Prepare Data Containers ---
        timestamps = []
        equity = []
        
        # Asset map: symbol -> { 'times': [], 'sizes': [], 'signals': [] }
        # We need to align signals to the same timestamps as positions
        assets_data = {} 

        for entry in history:
            try:
                ts = datetime.fromisoformat(entry["timestamp"])
                timestamps.append(ts)
                equity.append(entry.get("margin_equity", 0))

                # Process Positions
                # Group current positions by symbol
                current_positions = {p['symbol']: p for p in entry.get("positions", [])}
                
                # Process Signals
                current_signals = entry.get("signals", {})

                # We need a list of all assets seen in this history to ensure continuity
                # For this simple version, we iterate what we found
                
                # Check mapping
                # We iterate over the positions found in this entry to populate data
                for symbol, pos in current_positions.items():
                    # Initialize if new
                    if symbol not in assets_data:
                        assets_data[symbol] = {'times': [], 'sizes': [], 'signals': []}
                    
                    # Store data
                    assets_data[symbol]['times'].append(ts)
                    assets_data[symbol]['sizes'].append(float(pos.get('size', 0)))
                    
                    # Find matching signal
                    # Mapping Logic:
                    # pf_xrpusd -> Look for XRPUSDT
                    # ff_xbtusd -> Look for BTCUSDT
                    sig_val = 0
                    
                    if "xbt" in symbol.lower():
                        sig_data = current_signals.get("BTCUSDT", {})
                        sig_val = sig_data.get("signal_val", 0)
                    elif "xrp" in symbol.lower():
                        sig_data = current_signals.get("XRPUSDT", {})
                        sig_val = sig_data.get("signal_val", 0)
                    # Add more mappings here if needed
                    
                    assets_data[symbol]['signals'].append(float(sig_val))
            
            except Exception as e:
                print(f"Error parsing entry: {e}")
                continue

        # --- Plotting ---
        plot_files = []

        # 1. Equity Plot
        plt.figure(figsize=(10, 5))
        plt.plot(timestamps, equity, label='Margin Equity', color='#569cd6')
        plt.title("Portfolio Margin Equity (Last 3 Days)")
        plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
        plt.grid(True, which='both', linestyle='--', linewidth=0.5, color='#444')
        plt.legend()
        plt.tight_layout()
        
        eq_filename = "plot_equity.png"
        plt.savefig(os.path.join(DATA_DIR, eq_filename), facecolor='#1e1e1e', edgecolor='none')
        plt.close()
        plot_files.append(("Total Portfolio Value", eq_filename))

        # 2. Asset Plots
        for symbol, data in assets_data.items():
            if not data['times']: continue
            
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True, gridspec_kw={'height_ratios': [2, 1]})
            
            # Top: Position Size
            ax1.plot(data['times'], data['sizes'], color='#4ec9b0', label=f'Position: {symbol}')
            ax1.set_title(f"{symbol} - Position & Signal")
            ax1.set_ylabel("Size")
            ax1.grid(True, linestyle='--', alpha=0.3)
            ax1.legend(loc='upper left')

            # Bottom: Signal
            ax2.step(data['times'], data['signals'], where='post', color='#ce9178', label='Signal (DB)')
            ax2.set_ylabel("Signal Value")
            ax2.set_yticks([-1, 0, 1]) # Assuming signals are -1, 0, 1
            ax2.grid(True, linestyle='--', alpha=0.3)
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
            
            # Styling for Dark Mode
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
        # Serve Images
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
                <title>Kraken Historical Monitor</title>
                <meta http-equiv="refresh" content="60">
                <style>
                    body { font-family: sans-serif; background: #1e1e1e; color: #ccc; padding: 20px; }
                    h1 { color: #569cd6; }
                    .plot-container { margin-bottom: 40px; border: 1px solid #333; padding: 10px; background: #252526; }
                    img { max-width: 100%; height: auto; }
                    .warning { color: #ce9178; }
                </style>
            </head>
            <body>
                <h1>Historical Dashboard (3 Days)</h1>
            """
            
            if not plots:
                html += "<p class='warning'>No history data found yet. Wait for the monitor to run.</p>"
            else:
                for title, filename in plots:
                    html += f"""
                    <div class='plot-container'>
                        <h3>{title}</h3>
                        <img src='/{filename}' />
                    </div>
                    """

            html += "</body></html>"
            
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_error(404)

def run():
    server_address = ("", PORT)
    print(f"Starting Dashboard on port {PORT}")
    httpd = http.server.ThreadingHTTPServer(server_address, RequestHandler)
    httpd.serve_forever()

if __name__ == "__main__":
    run()
