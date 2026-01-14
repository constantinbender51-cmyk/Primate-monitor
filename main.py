import threading
import time
import os
import sys

# Import the two scripts you just created
# Ensure the files are named 'monitor.py' and 'dashboard.py'
import monitor
import dashboard

def start_monitor():
    """Runs the monitoring loop safely."""
    print("[System] Starting Background Monitor...")
    try:
        monitor.main()
    except Exception as e:
        print(f"[System] Monitor Thread Crashed: {e}", file=sys.stderr)

def start_dashboard():
    """Runs the web server safely."""
    print("[System] Starting Web Dashboard...")
    try:
        dashboard.run()
    except Exception as e:
        print(f"[System] Dashboard Crashed: {e}", file=sys.stderr)

if __name__ == "__main__":
    # 1. Start the Monitor in a separate Daemon thread
    # Daemon means it will automatically close if the main program (dashboard) exits
    monitor_thread = threading.Thread(target=start_monitor, daemon=True)
    monitor_thread.start()

    # 2. Give the monitor a brief second to initialize files/logs
    time.sleep(1)

    # 3. Start the Dashboard in the main thread (Blocking)
    # This keeps the container alive and listening on the PORT
    start_dashboard()
