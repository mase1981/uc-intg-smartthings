#!/bin/bash
set -e

cd /app

# Install dependencies if needed (for development)
if [ -f requirements.txt ]; then
    pip install --no-cache-dir -q -r requirements.txt
fi

# Run integration as module
python3 -u -m uc_intg_smartthings
