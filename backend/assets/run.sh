#!/bin/bash

echo "=== RUN START ==="

echo "[1/2] Installing dependencies..."

if [ -f "package.json" ]; then
    npm install
elif [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
fi

echo "[2/2] Starting application..."

if [ -f "package.json" ]; then
    npm start
elif [ -f "main.py" ]; then
    python main.py
elif [ -f "app.py" ]; then
    python app.py
fi

echo "=== RUN END ==="
