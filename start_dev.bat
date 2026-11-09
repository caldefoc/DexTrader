@echo off
echo Starting DexTrader Development Environment...

start "DexTrader Backend" powershell -NoExit -Command "cd backend; python -m uvicorn app.main:app --reload"
start "DexTrader Frontend" powershell -NoExit -Command "cd frontend; npm run dev"

echo Services started in new windows.
