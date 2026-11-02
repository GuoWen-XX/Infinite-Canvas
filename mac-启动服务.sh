#!/bin/bash
cd "$(dirname "$0")"
# The server binds loopback by default; the local browser should use it
# even when this workstation has a LAN IP address.
APP_URL="http://127.0.0.1:3000/"

echo "Starting ComfyUI-API-Modelscope..."
echo "Visit: ${APP_URL}"
echo "Local: http://127.0.0.1:3000/"
echo "Press Ctrl+C to stop."
echo ""

# Open browser after 3 seconds
sleep 3 && open "${APP_URL}" &

python3 main.py

echo ""
echo "Server stopped."
