#!/bin/bash

set -e

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo -e "${BLUE}╔════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   QuData Agent - Installation Script  ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════╝${NC}"
echo ""

# Проверка прав root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Error: This script must be run as root${NC}"
    echo "Please run: sudo bash install.sh <API_KEY>"
    exit 1
fi

# Проверка API ключа
if [ -z "$1" ]; then
    echo -e "${RED}Error: API key is required${NC}"
    echo ""
    echo "Usage:"
    echo "  sudo bash install.sh <API_KEY>"
    echo ""
    echo "Quick install (one-line):"
    echo "  curl -fsSL https://raw.githubusercontent.com/magicaleks/qudata-agent-prealpha/main/install.sh | sudo bash -s <API_KEY>"
    echo ""
    exit 1
fi

API_KEY="$1"
REPO_URL="https://github.com/magicaleks/qudata-agent-prealpha.git"
INSTALL_DIR="/opt/qudata-agent"

echo -e "${BLUE}API Key: ${API_KEY:0:8}...${NC}"
echo -e "${BLUE}Install Directory: $INSTALL_DIR${NC}"
echo ""

echo -e "${YELLOW}[1/11] Updating system packages...${NC}"
apt-get update -qq || {
    echo -e "${RED}Failed to update packages${NC}"
    exit 1
}

echo -e "${YELLOW}[2/11] Installing system dependencies...${NC}"
apt-get install -y git curl wget software-properties-common \
    lsb-release ca-certificates apt-transport-https \
    ethtool dmidecode lshw pciutils 2>&1 | grep -v "^Reading\|^Building\|^After" || true
echo -e "${GREEN}✓ System dependencies installed${NC}"

echo -e "${YELLOW}[3/11] Installing Python 3.10+...${NC}"
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
if [ "$(printf '%s\n' "3.10" "$PYTHON_VERSION" | sort -V | head -n1)" != "3.10" ]; then
    echo "  Python 3.10+ not found, installing..."
    add-apt-repository -y ppa:deadsnakes/ppa > /dev/null 2>&1
    apt-get update -qq
    apt-get install -y python3.10 python3.10-venv python3.10-dev python3-pip 2>&1 | grep -v "^Reading\|^Building" || true
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1
fi
echo -e "${GREEN}✓ Python version: $(python3 --version)${NC}"

echo -e "${YELLOW}[4/11] Checking for Docker...${NC}"
if ! command -v docker &> /dev/null; then
    echo "  Docker not found, installing..."
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    sh /tmp/get-docker.sh > /dev/null 2>&1
    usermod -aG docker $SUDO_USER 2>/dev/null || true
    echo -e "${GREEN}✓ Docker installed${NC}"
else
    echo -e "${GREEN}✓ Docker already installed ($(docker --version))${NC}"
fi

# Запуск Docker если не запущен
if ! systemctl is-active --quiet docker; then
    systemctl start docker
fi

# Remove invalid Docker authz plugin if present
if grep -q "qudata-authz" /etc/docker/daemon.json 2>/dev/null; then
    echo -e "${YELLOW}Removing invalid Docker plugin configuration (qudata-authz)...${NC}"
    jq 'del(.authorization-plugins)' /etc/docker/daemon.json > /tmp/daemon-clean.json && mv /tmp/daemon-clean.json /etc/docker/daemon.json
    systemctl restart docker || true
fi

echo -e "${YELLOW}[5/11] Checking for NVIDIA GPU...${NC}"
if lspci | grep -i nvidia > /dev/null 2>&1; then
    echo "  NVIDIA GPU detected: $(lspci | grep -i nvidia | head -n1 | cut -d: -f3)"
    
    if ! command -v nvidia-smi &> /dev/null; then
        echo "  Installing NVIDIA drivers..."
        apt-get install -y linux-headers-$(uname -r) 2>&1 | grep -v "^Reading" || true
        apt-get install -y nvidia-driver-535 2>&1 | grep -v "^Reading" || true
        echo -e "${YELLOW}⚠ NVIDIA driver installed. System reboot required!${NC}"
        echo -e "${YELLOW}⚠ After reboot, run this script again with the same API key.${NC}"
        echo ""
        echo -e "${BLUE}Reboot command: sudo reboot${NC}"
        exit 0
    else
        echo -e "${GREEN}✓ NVIDIA drivers installed ($(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1))${NC}"
    fi
    
    echo -e "${YELLOW}[6/11] Installing NVIDIA Container Toolkit...${NC}"
    if ! dpkg -l | grep -q nvidia-container-toolkit 2>/dev/null; then
          echo "  Setting up NVIDIA Container Toolkit repository..."
          curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
          curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
            sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
            tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

          apt-get update -qq
          apt-get install -y nvidia-container-toolkit
          nvidia-ctk runtime configure --runtime=docker
          systemctl restart docker
        echo -e "${GREEN}✓ NVIDIA Container Toolkit installed${NC}"
    else
        echo -e "${GREEN}✓ NVIDIA Container Toolkit already installed${NC}"
    fi
else
    echo -e "${YELLOW}⚠ No NVIDIA GPU detected, skipping GPU setup${NC}"
fi

echo -e "${YELLOW}[7/11] Cloning QuData Agent repository...${NC}"
if [ -d "$INSTALL_DIR" ]; then
    echo "  Directory exists, updating to latest version..."
    cd "$INSTALL_DIR"
    git fetch origin 2>&1 | grep -v "^From" || true
    git reset --hard origin/main > /dev/null 2>&1
    git pull origin main 2>&1 | grep -v "^From" || true
else
    echo "  Cloning from GitHub..."
    git clone "$REPO_URL" "$INSTALL_DIR" 2>&1 | grep -v "^Cloning\|^remote:" || true
fi
echo -e "${GREEN}✓ Repository ready at $INSTALL_DIR${NC}"

echo -e "${YELLOW}[8/11] Installing Python dependencies...${NC}"
cd "$INSTALL_DIR"
pip3 install --upgrade pip > /dev/null 2>&1
pip3 install -r requirements.txt 2>&1 | grep -E "Successfully|Requirement already satisfied" || true
echo -e "${GREEN}✓ Python dependencies installed${NC}"

echo -e "${YELLOW}[9/11] Saving API key...${NC}"
mkdir -p "$INSTALL_DIR"
echo "{\"secret_key\": \"$API_KEY\"}" > "$INSTALL_DIR/secret_key.json"
chmod 600 "$INSTALL_DIR/secret_key.json"
echo -e "${GREEN}✓ API key saved${NC}"

echo -e "${YELLOW}[10/11] Creating systemd service...${NC}"
tee /etc/systemd/system/qudata-agent.service > /dev/null <<EOF
[Unit]
Description=QuData Agent - GPU Instance Manager
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment="PYTHONUNBUFFERED=1"
ExecStart=/usr/bin/python3 $INSTALL_DIR/main.py $API_KEY
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=qudata-agent

# Graceful shutdown
TimeoutStopSec=30
KillMode=mixed
KillSignal=SIGTERM

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable qudata-agent > /dev/null 2>&1
echo -e "${GREEN}✓ Systemd service created and enabled${NC}"

echo -e "${YELLOW}[11/11] Starting QuData Agent...${NC}"
systemctl stop qudata-agent 2>/dev/null || true
sleep 1
systemctl start qudata-agent

# Ждем запуска
echo -n "  Waiting for agent to start"
for i in {1..10}; do
    sleep 1
    echo -n "."
    if systemctl is-active --quiet qudata-agent; then
        break
    fi
done
echo ""

if systemctl is-active --quiet qudata-agent; then
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║     Installation Completed! ✓          ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BLUE}QuData Agent is running as systemd service${NC}"
    echo ""
    echo -e "${YELLOW}Useful Commands:${NC}"
    echo "  ${GREEN}View logs:${NC}      sudo journalctl -u qudata-agent -f"
    echo "  ${GREEN}Live logs:${NC}      sudo tail -f $INSTALL_DIR/logs.txt"
    echo "  ${GREEN}Status:${NC}         sudo systemctl status qudata-agent"
    echo "  ${GREEN}Stop:${NC}           sudo systemctl stop qudata-agent"
    echo "  ${GREEN}Start:${NC}          sudo systemctl start qudata-agent"
    echo "  ${GREEN}Restart:${NC}        sudo systemctl restart qudata-agent"
    echo "  ${GREEN}Update agent:${NC}   cd $INSTALL_DIR && sudo git pull && sudo systemctl restart qudata-agent"
    echo ""
    echo -e "${YELLOW}Files:${NC}"
    echo "  Config:         $INSTALL_DIR/secret_key.json"
    echo "  Logs:           $INSTALL_DIR/logs.txt"
    echo "  Service:        /etc/systemd/system/qudata-agent.service"
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}Agent Status:${NC}"
    systemctl status qudata-agent --no-pager -l | head -n 10
    echo ""
else
    echo ""
    echo -e "${RED}╔════════════════════════════════════════╗${NC}"
    echo -e "${RED}║     Failed to Start Agent ✗            ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${YELLOW}Diagnostic Information:${NC}"
    echo ""
    systemctl status qudata-agent --no-pager -l || true
    echo ""
    echo -e "${YELLOW}Last 20 log lines:${NC}"
    journalctl -u qudata-agent -n 20 --no-pager || true
    echo ""
    echo -e "${RED}Please check the logs and try again${NC}"
    exit 1
fi

