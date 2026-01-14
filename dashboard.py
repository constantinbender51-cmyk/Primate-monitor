import http.server
import json
import os
import datetime
import sqlite3
import io
import base64
import urllib.parse
from http import HTTPStatus

# Set Matplotlib to non-interactive (backend 'Agg') for server use
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Configuration
PORT = int(os.environ.get("PORT", 8080))
DATA_DIR = os.environ.get("VOLUME_DIR", "/mnt/data/")
DB_PATH = os.path.join(DATA_DIR, "history.db")

class RequestHandler(http.server.BaseHTTPRequestHandler):
    def _read_json(self, filename):
        filepath = os.path.join(DATA_DIR, filename)
        if not os.path.exists(filepath): return None
        try:
            with open(filepath, "r") as f: return json.load(f)
        except: return None

    def _get_historical_data(self, hours):
        """Query SQLite for data within the last X hours."""
        if not os.path.exists(DB_PATH): return None, None, None
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        
        # Fetch Equity
        c.execute("SELECT timestamp, equity FROM equity_log WHERE timestamp > ? ORDER BY timestamp ASC", (cutoff,))
        equity_rows = c.fetchall()
        
        # Fetch Positions
        c.execute("SELECT timestamp, symbol, size FROM position_log WHERE timestamp > ? ORDER BY timestamp ASC", (cutoff,))
        pos_rows = c.fetchall()
        
        # Fetch Signals
        c.execute("SELECT timestamp, asset, tf, signal_val FROM signal_log WHERE timestamp > ? ORDER BY timestamp ASC", (cutoff,))
        sig_rows = c.fetchall()
        
        conn.close()
        return equity_rows, pos_rows, sig_rows

    def _generate_plot_base64(self, title, x_data, y_dict, type='line', ylabel='Value'):
        """Generates a Matplotlib plot and returns a base64 HTML image string."""
        if not x_data: return ""
        
        fig, ax = plt.subplots(figsize=(10, 4))
        fig.patch.set_facecolor('#252526')
        ax.set_facecolor('#1e1e1e')
        
        # Styling
        ax.tick_params(axis='x', colors='#d4d4d4')
        ax.tick_params(axis='y', colors='#d4d4d4')
        ax.xaxis.label.set_color('#d4d4d4')
        ax.yaxis.label.set_color('#d4d4d4')
        ax.set_title(title, color='#569cd6')
        ax.grid(True, color='#333', linestyle='--')
        
        # Plotting
        for label, y_vals in y_dict.items():
            # Align lengths (basic forward fill logic might be needed for perfect sync, but this is a quick vis)
            # Ensure x and y match for this specific series
            # For simplicity in this structure: assume x_data is global time, y_vals are sparse. 
            # Better approach: Plot (x,y) pairs directly.
            
            if isinstance(y_vals, list) and isinstance(y_vals[0], tuple):
                # (timestamp, value) list
                xs = [v[0] for v in y_vals]
                ys = [v[1] for v in y_vals]
                if type == 'step':
                    ax.step(xs, ys, label=label, where='post')
                else:
                    ax.plot(xs, ys, label=label)
            
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
        plt.xticks(rotation=45)
        
        if len(y_dict) > 1:
            ax.legend(facecolor='#252526', edgecolor='#444', labelcolor='#d4d4d4')

        # Save to buffer
        buf = io.BytesIO()
        plt.tight_layout()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        img_str = base64.b64encode(buf.read()).decode('utf-8')
        return f'<img src="data:image/png;base64,{img_str}" class="chart"/>'

    def _render_charts(self, hours):
        eq_rows, pos_rows, sig_rows = self._get_historical_data(hours)
        if not eq_rows: return "<p class='empty'>No historical data yet.</p>"
        
        # Process Equity
        # Convert strings to datetime objects
        eq_times = [datetime.datetime.fromisoformat(r[0]) for r in eq_rows]
        eq_vals = [r[1] for r in eq_rows]
        # Pack into structure expected by plotter
        equity_data = {"Total Equity": list(zip(eq_times, eq_vals))}
        
        html = self._generate_plot_base64("Margin Equity", eq_times, equity_data)
        
        # Process Positions
        pos_data = {}
        for r in pos_rows:
            ts = datetime.datetime.fromisoformat(r[0])
            sym = r[1]
            size = r[2]
            if sym not in pos_data: pos_data[sym] = []
            pos_data[sym].append((ts, size))
            
        html += self._generate_plot_base64("Positions Size Over Time", eq_times, pos_data)
        
        # Process Signals (Filtered to prevent clutter, maybe combine Asset+TF)
        sig_data = {}
        for r in sig_rows:
            ts = datetime.datetime.fromisoformat(r[0])
            key = f"{r[1]} ({r[2]})" # Asset (TF)
            val = r[3]
            if key not in sig_data: sig_data[key] = []
            sig_data[key].append((ts, val))
            
        html += self._generate_plot_base64("Signals Over Time", eq_times, sig_data, type='step')
        
        return html

    def _html_template(self, body_content, current_range):
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Kraken Monitor</title>
            <meta http-equiv="refresh" content="60"> 
            <style>
                body {{ font-family: monospace; background: #1e1e1e; color: #d4d4d4; padding: 20px; }}
                h1, h2 {{ color: #569cd6; border-bottom: 1px solid #333; padding-bottom: 5px; }}
                .card {{ background: #252526; padding: 15px; margin-bottom: 20px; border-radius: 5px; border: 1px solid #333; }}
                .chart {{ max_width: 100%; height: auto; display: block; margin: 10px 0; border: 1px solid #333; }}
                .nav {{ margin-bottom: 20px; }}
                .nav a {{ margin-right: 10px; color: #d4d4d4; text-decoration: none; padding: 5px 10px; border: 1px solid #444; border-radius: 3px; }}
                .nav a.active {{ background: #0e639c; border-color: #0e639c; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
                th {{ text-align: left; border-bottom: 1px solid #444; color: #ce9178; padding: 5px; }}
                td {{ border-bottom: 1px solid #333; padding: 5px; }}
            </style>
        </head>
        <body>
            <h1>Live Monitor Dashboard</h1>
            <div class="nav">
                <span>Time Range: </span>
                <a href="/?range=24" class="{ 'active' if current_range==24 else '' }">1 Day</a>
                <a href="/?range=72" class="{ 'active' if current_range==72 else '' }">3 Days</a>
                <a href="/?range=168" class="{ 'active' if current_range==168 else '' }">7 Days</a>
            </div>
            
            <div class="card">
                <h2>Historical Charts</h2>
                {self._render_charts(current_range)}
            </div>

            {body_content}
        </body>
        </html>
        """

    def _render_dict_table(self, title, json_obj):
        # (Same as your original function, kept for brevity)
        if not json_obj: return f"<div class='card'><h2>{title}</h2><p class='empty'>No data.</p></div>"
        last = json_obj.get("last_updated", "?")
        data = json_obj.get("data", {})
        html = f"<div class='card'><h2>{title} <span style='font-size:0.8em; color:#6a9955'>({last})</span></h2>"
        
        if isinstance(data, list) and data:
            keys = data[0].keys()
            html += "<table><thead><tr>" + "".join([f"<th>{k}</th>" for k in keys]) + "</tr></thead><tbody>"
            for item in data:
                html += "<tr>" + "".join([f"<td>{item.get(k,'')}</td>" for k in keys]) + "</tr>"
            html += "</tbody></table>"
        elif isinstance(data, dict) and data:
            html += "<table><thead><tr><th>Key</th><th>Value</th></tr></thead><tbody>"
            for k,v in data.items():
                disp = json.dumps(v) if isinstance(v, (dict,list)) else v
                html += f"<tr><td>{k}</td><td>{disp}</td></tr>"
            html += "</tbody></table>"
        else:
            html += "<p>Empty.</p>"
        html += "</div>"
        return html

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        
        # Default to 24 hours (1 day)
        range_hours = int(params.get('range', [24])[0])

        portfolio = self._read_json("portfolio_snapshot.json")
        positions = self._read_json("positions_snapshot.json")
        signals = self._read_json("signals_snapshot.json")

        body = ""
        # 1. Portfolio Table
        if portfolio and "accounts" in portfolio.get("data", {}):
             body += self._render_dict_table("Portfolio Balances", {"last_updated": portfolio["last_updated"], "data": portfolio["data"]["accounts"]})
        else:
             body += self._render_dict_table("Portfolio Balances", portfolio)

        # 2. Positions Table
        if positions and "openPositions" in positions.get("data", {}):
             body += self._render_dict_table("Open Positions", {"last_updated": positions["last_updated"], "data": positions["data"]["openPositions"]})
        else:
             body += self._render_dict_table("Open Positions", positions)

        # 3. Signals Table
        body += self._render_dict_table("Signals (Live)", signals)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(self._html_template(body, range_hours).encode("utf-8"))

def run():
    print(f"Server on {PORT}")
    http.server.ThreadingHTTPServer(("", PORT), RequestHandler).serve_forever()

if __name__ == "__main__":
    run()
