#!/bin/bash
# ============================================================
# ospal-ctl.sh - OSPAL Control Script
# Usage: ospal-ctl.sh [command] [options]
# ============================================================

SERVICE="ospal"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OSPAL="python3 -u ${SCRIPT_DIR}/ospal.py"
CONFIG="${SCRIPT_DIR}/ospal.ini"
SERVICE_FILE="/etc/systemd/system/${SERVICE}.service"
TODAY=$(date +%Y-%m-%d)

# Read log_dir from ospal.ini
LOG_DIR=$(grep -i "^log_dir" "$CONFIG" 2>/dev/null | head -1 | cut -d'=' -f2 | tr -d ' ;')
LOG_DIR="${LOG_DIR:-.}"
[ "$LOG_DIR" = "." ] && LOG_DIR="$SCRIPT_DIR"

print_usage() {
    echo ""
    echo "OSPAL Control Script"
    echo "--------------------"
    echo "Usage: ospal-ctl.sh [command]"
    echo ""
    echo "Commands:"
    echo "  start              Start OSPAL service"
    echo "  stop               Stop OSPAL service"
    echo "  restart            Restart OSPAL service (e.g. after editing ospal.ini)"
    echo "  status             Show service status and last log entries"
    echo "  status-live        Show live output from OSPAL via systemd journal"
    echo "  calibrate [min]    Stop service, run PPM/gain calibration, restart service"
    echo "                     Default: 15 minutes"
    echo "  testmail           Stop service, send test mail, restart service"
    echo "  testntfy           Stop service, send test ntfy notification, restart service"
    echo "  install-service    Install OSPAL as a systemd service (requires sudo)"
    echo ""
}

cmd_start() {
    echo "[ospal-ctl] Starting OSPAL service..."
    sudo systemctl start "$SERVICE"
    sleep 1
    systemctl is-active --quiet "$SERVICE" && echo "[ospal-ctl] Service started." || echo "[ospal-ctl] ERROR: Service failed to start."
}

cmd_stop() {
    echo "[ospal-ctl] Stopping OSPAL service..."
    sudo systemctl stop "$SERVICE"
    sleep 1
    systemctl is-active --quiet "$SERVICE" && echo "[ospal-ctl] ERROR: Service still running." || echo "[ospal-ctl] Service stopped."
}

cmd_restart() {
    echo "[ospal-ctl] Restarting OSPAL service..."
    sudo systemctl restart "$SERVICE"
    sleep 1
    systemctl is-active --quiet "$SERVICE" && echo "[ospal-ctl] Service restarted." || echo "[ospal-ctl] ERROR: Service failed to restart."
}

cmd_status() {
    echo "[ospal-ctl] Service status:"
    echo "-----------------------------"
    systemctl status "$SERVICE" --no-pager -l
    echo ""
    echo "[ospal-ctl] Last 20 lines of today's filtered log (${TODAY}):"
    echo "-----------------------------"
    FILTERED_LOG="${LOG_DIR}/${TODAY}-filtered.log"
    if [ -f "$FILTERED_LOG" ]; then
        tail -20 "$FILTERED_LOG"
    else
        echo "(No filtered log found for today)"
    fi
}

cmd_status_live() {
    echo "[ospal-ctl] Showing live output from OSPAL via systemd journal."
    echo "[ospal-ctl] Press Ctrl+C to stop viewing — OSPAL will keep running."
    echo "-----------------------------"
    journalctl -u "$SERVICE" -f
}

cmd_calibrate() {
    MINUTES="${1:-15}"
    echo "[ospal-ctl] Stopping service before calibration..."
    sudo systemctl stop "$SERVICE"
    sleep 1
    echo "[ospal-ctl] Running calibration for ${MINUTES} minutes..."
    $OSPAL -t "$MINUTES" -c "$CONFIG"
    echo "[ospal-ctl] Restarting service..."
    sudo systemctl start "$SERVICE"
    sleep 1
    systemctl is-active --quiet "$SERVICE" && echo "[ospal-ctl] Service restarted after calibration." || echo "[ospal-ctl] ERROR: Service failed to restart."
}

cmd_testmail() {
    echo "[ospal-ctl] Stopping service before sending test mail..."
    sudo systemctl stop "$SERVICE"
    sleep 1
    echo "[ospal-ctl] Sending test mail..."
    $OSPAL -m -c "$CONFIG"
    echo "[ospal-ctl] Restarting service..."
    sudo systemctl start "$SERVICE"
    sleep 1
    systemctl is-active --quiet "$SERVICE" && echo "[ospal-ctl] Service restarted after test mail." || echo "[ospal-ctl] ERROR: Service failed to restart."
}

cmd_testntfy() {
    echo "[ospal-ctl] Stopping service before sending test ntfy notification..."
    sudo systemctl stop "$SERVICE"
    sleep 1
    echo "[ospal-ctl] Sending test ntfy notification..."
    $OSPAL -n -c "$CONFIG"
    echo "[ospal-ctl] Restarting service..."
    sudo systemctl start "$SERVICE"
    sleep 1
    systemctl is-active --quiet "$SERVICE" && echo "[ospal-ctl] Service restarted after test ntfy." || echo "[ospal-ctl] ERROR: Service failed to restart."
}

cmd_install_service() {
    # Must be run with sudo
    if [ "$EUID" -ne 0 ]; then
        echo "[ospal-ctl] ERROR: install-service must be run with sudo."
        echo "[ospal-ctl] Run: sudo ./ospal-ctl.sh install-service"
        exit 1
    fi

    # Get the user who ran sudo (not root)
    RUN_AS="${SUDO_USER:-$(logname)}"
    PYTHON=$(which python3)

    echo "[ospal-ctl] Installing OSPAL service..."
    echo "[ospal-ctl] Script directory : $SCRIPT_DIR"
    echo "[ospal-ctl] Running as user  : $RUN_AS"
    echo "[ospal-ctl] Python binary    : $PYTHON"
    echo "[ospal-ctl] Service file     : $SERVICE_FILE"
    echo ""

    # Write service file
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=OSPAL - Open Source POCSAG Alert Logger
After=network.target

[Service]
ExecStart=${PYTHON} -u ${SCRIPT_DIR}/ospal.py -c ${CONFIG}
WorkingDirectory=${SCRIPT_DIR}
Restart=always
RestartSec=10
User=${RUN_AS}

[Install]
WantedBy=multi-user.target
EOF

    echo "[ospal-ctl] Service file written to $SERVICE_FILE"

    # Reload systemd and enable service
    systemctl daemon-reload
    systemctl enable "$SERVICE"

    echo "[ospal-ctl] Service enabled — OSPAL will now start automatically on boot."
    echo "[ospal-ctl] To start now: ./ospal-ctl.sh start"
    echo "[ospal-ctl] To check status: ./ospal-ctl.sh status"
}

# ── Main ──────────────────────────────────────────────────────────────────────

case "$1" in
    start)           cmd_start ;;
    stop)            cmd_stop ;;
    restart)         cmd_restart ;;
    status)          cmd_status ;;
    status-live)     cmd_status_live ;;
    calibrate)       cmd_calibrate "$2" ;;
    testmail)        cmd_testmail ;;
    testntfy)        cmd_testntfy ;;
    install-service) cmd_install_service ;;
    *)               print_usage ;;
esac
