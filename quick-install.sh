#!/bin/bash

# QuData Agent Quick Install Script
# Usage: curl -fsSL https://raw.githubusercontent.com/magicaleks/qudata-agent/main/quick-install.sh | bash -s <API_KEY>

set -e

if [ -z "$1" ]; then
    echo "Error: API key is required"
    echo "Usage: curl -fsSL https://raw.githubusercontent.com/magicaleks/qudata-agent/main/quick-install.sh | bash -s <API_KEY>"
    exit 1
fi

API_KEY="$1"

echo "Downloading full installation script..."
curl -fsSL https://raw.githubusercontent.com/magicaleks/qudata-agent/main/install.sh -o /tmp/qudata-install.sh

echo "Starting installation..."
bash /tmp/qudata-install.sh "$API_KEY"

rm /tmp/qudata-install.sh

