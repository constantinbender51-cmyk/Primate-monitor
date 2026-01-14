import http.server
import json
import os
import datetime
from http import HTTPStatus

# Configuration
PORT = int(os.environ.get("PORT", 8080))  # Railway usually listens on 8080 or provides PORT env
DATA_DIR = os.environ.get("VOLUME_DIR", "/mnt/data/")

class RequestHandler(http.server.BaseHTTPRequestHandler):
    def _read_json(self, filename):
        """Helper to safely read JSON from the volume."""
        filepath = os.path.join(DATA_DIR, filename)
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception as e:
            return {"error": str(e)}

    def _html_template(self, body_content):
        """Basic HTML wrapper with auto-refresh and styling."""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Kraken Monitor</title>
            <meta http-equiv="refresh" content="20"> <style>
                body {{ font-family: monospace; background: #1e1e1e; color: #d4d4d4; padding: 20px; }}
                h1, h2 {{ color: #569cd6; border-bottom: 1px solid #333; padding-bottom: 5px; }}
                .card {{ background: #252526; padding: 15px; margin-bottom: 20px; border-radius: 5px; border: 1px solid #333; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
                th {{ text-align: left; border-bottom: 1px solid #444; color: #ce9178; padding: 5px; }}
                td {{ border-bottom: 1px solid #333; padding: 5px; }}
                .timestamp {{ color: #6a9955; font-size: 0.9em; }}
                .empty {{ color: #888; font-style: italic; }}
                .positive {{ color: #6a9955; }}
                .negative {{ color: #f44747; }}
            </style>
        </head>
        <body>
            <h1>Live Monitor Dashboard</h1>
            {body_content}
        </body>
        </html>
        """

    def _render_dict_table(self, title, json_obj):
        """Renders a generic dictionary or list into an HTML table."""
        if not json_obj:
            return f"<div class='card'><h2>{title}</h2><p class='empty'>No data file found.</p></div>"
        
        last_updated = json_obj.get("last_updated", "Unknown")
        data = json_obj.get("data", {})

        html = f"<div class='card'><h2>{title} <span class='timestamp'>({last_updated})</span></h2>"

        if isinstance(data, list):
            if not data:
                html += "<p class='empty'>List is empty.</p>"
            else:
                # Create table headers from first item keys
                keys = data[0].keys()
                html += "<table><thead><tr>"
                for k in keys:
                    html += f"<th>{k}</th>"
                html += "</tr></thead><tbody>"
                for item in data:
                    html += "<tr>"
                    for k in keys:
                        val = item.get(k, "")
                        html += f"<td>{val}</td>"
                    html += "</tr>"
                html += "</tbody></table>"
        
        elif isinstance(data, dict):
            if not data:
                html += "<p class='empty'>Object is empty.</p>"
            else:
                html += "<table><thead><tr><th>Key</th><th>Value</th></tr></thead><tbody>"
                for k, v in data.items():
                    # If value is a complex list/dict, just stringify it to keep it simple
                    display_val = json.dumps(v) if isinstance(v, (dict, list)) else v
                    html += f"<tr><td>{k}</td><td>{display_val}</td></tr>"
                html += "</tbody></table>"
        
        html += "</div>"
        return html

    def do_GET(self):
        if self.path == "/":
            # 1. Read Data
            portfolio = self._read_json("portfolio_snapshot.json")
            positions = self._read_json("positions_snapshot.json")
            signals = self._read_json("signals_snapshot.json")

            # 2. Build HTML Body
            body = ""
            
            # Portfolio Section
            # Flatten slightly for better display if 'accounts' exists
            if portfolio and "accounts" in portfolio.get("data", {}):
                # Just show the accounts list directly
                # You might want to filter this in the monitor script if it's too large
                body += self._render_dict_table("Portfolio Balances", {"last_updated": portfolio["last_updated"], "data": portfolio["data"]["accounts"]})
            else:
                body += self._render_dict_table("Portfolio Raw", portfolio)

            # Positions Section
            if positions and "openPositions" in positions.get("data", {}):
                 body += self._render_dict_table("Open Positions", {"last_updated": positions["last_updated"], "data": positions["data"]["openPositions"]})
            else:
                body += self._render_dict_table("Open Positions", positions)

            # Signals Section
            body += self._render_dict_table("Signals (DB)", signals)

            # 3. Send Response
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(self._html_template(body).encode("utf-8"))
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

def run(server_class=http.server.ThreadingHTTPServer, handler_class=RequestHandler):
    server_address = ("", PORT)
    print(f"Starting Threaded HTTP Server on port {PORT}...")
    print(f"Reading data from: {DATA_DIR}")
    httpd = server_class(server_address, handler_class)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    print("Server stopped.")

if __name__ == "__main__":
    run()
