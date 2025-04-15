#!/bin/bash
set -e

echo "Starting FastAPI server..."
uvicorn case_download_api:app --host 0.0.0.0 --port 8000 &
API_PID=$!
echo "FastAPI server started with PID $API_PID"

echo "Starting Telegram bot..."
python -m patri_reports.main run &
BOT_PID=$!
echo "Telegram bot started with PID $BOT_PID"

# Wait for either process to exit
wait -n $API_PID $BOT_PID

# Check which process exited and capture its exit code
EXIT_CODE=$?
if ! kill -0 $API_PID 2>/dev/null; then
    echo "FastAPI server exited with status $EXIT_CODE."
elif ! kill -0 $BOT_PID 2>/dev/null; then
    echo "Telegram bot exited with status $EXIT_CODE."
else
    echo "Unknown process exited first? Status $EXIT_CODE."
fi

# Gracefully stop the other process if it's still running
echo "Shutting down remaining processes..."
kill $API_PID 2>/dev/null || true
kill $BOT_PID 2>/dev/null || true

# Wait a moment for cleanup
sleep 2

echo "Entrypoint script finished."
exit $EXIT_CODE 