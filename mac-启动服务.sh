#!/bin/bash
cd "$(dirname "$0")"
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)"
if [ -z "$LAN_IP" ]; then
  LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi
if [ -z "$LAN_IP" ]; then
  LAN_IP="127.0.0.1"
fi
APP_URL="http://${LAN_IP}:3333/"

python3 -c "from core.providers import get_configured_access_token; exit(0 if get_configured_access_token() else 1)" 2>/dev/null
if [ $? -ne 0 ]; then
  echo "[安全提示] 未检测到 IC_ACCESS_TOKEN 配置。"
  echo "          当前服务在局域网模式运行，建议在 API/.env 中设置 IC_ACCESS_TOKEN。"
  echo ""
fi

echo "Starting MeansCanvas (开卷画布)..."
echo "Visit: ${APP_URL}"
echo "Local: http://127.0.0.1:3333/"
echo "Press Ctrl+C to stop."
echo ""

# Open browser after 3 seconds
sleep 3 && open "${APP_URL}" &

python3 main.py --host 0.0.0.0 --port 3333

echo ""
echo "Server stopped."
