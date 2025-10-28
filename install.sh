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
    echo "  curl -fsSL https://raw.githubusercontent.com/magicaleks/qudata-agent-v2/main/install.sh | sudo bash -s <API_KEY>"
    echo ""
    exit 1
fi

API_KEY="$1"
REPO_URL="https://github.com/magicaleks/qudata-agent-v2.git"
INSTALL_DIR="/opt/qudata-agent"

echo -e "${BLUE}API Key: ${API_KEY:0:8}...${NC}"
export QUDATA_API_KEY=${API_KEY}
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
        echo "  Setting up NVIDIA Container Toolkit..."
        
        # Настройка репозитория вручную (обход проблем с недоступностью NVIDIA серверов)
        distribution=$(. /etc/os-release; echo $ID$VERSION_ID | sed 's/\.//g')
        
        # Добавляем GPG ключ
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey 2>/dev/null | \
            gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null || \
            echo "Warning: Could not fetch GPG key"
        
        # Создаём файл репозитория вручную
        cat > /etc/apt/sources.list.d/nvidia-container-toolkit.list <<'EOF'
deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://nvidia.github.io/libnvidia-container/stable/deb/amd64 /
EOF
        
        # Обновляем и пытаемся установить
        echo "  Updating package lists..."
        apt-get update -qq 2>&1 | grep -v "^Reading\|^Building\|^Fetched" || true
        
        echo "  Installing nvidia-container-toolkit..."
        if apt-get install -y nvidia-container-toolkit 2>&1 | tee /tmp/nvidia-install.log | grep -E "Setting up|already"; then
            # Настройка Docker runtime
            if command -v nvidia-ctk &> /dev/null; then
                nvidia-ctk runtime configure --runtime=docker > /dev/null 2>&1 || true
                systemctl restart docker 2>/dev/null || true
            fi
            echo -e "${GREEN}✓ NVIDIA Container Toolkit installed${NC}"
        else
            echo -e "${YELLOW}⚠ Installation from repository failed${NC}"
            echo "  Last error:"
            tail -n 3 /tmp/nvidia-install.log 2>/dev/null || true
            
            # Пробуем альтернативный пакет nvidia-docker2
            echo "  Trying nvidia-docker2 as alternative..."
            if apt-get install -y nvidia-docker2 2>/dev/null; then
                systemctl restart docker 2>/dev/null || true
                echo -e "${GREEN}✓ NVIDIA Docker2 installed${NC}"
            else
                # Метод 3: Скачивание и установка пакетов напрямую (если репозитории недоступны)
                echo "  Trying direct package download from GitHub..."
                TMPDIR=$(mktemp -d)
                cd "$TMPDIR"
                
                # Скачиваем основные пакеты напрямую из GitHub
                BASE_URL="https://github.com/NVIDIA/libnvidia-container/releases/download"
                VERSION="1.14.5-1"  # Стабильная версия
                
                wget -q "${BASE_URL}/v${VERSION}/libnvidia-container1_${VERSION}_amd64.deb" 2>/dev/null || true
                wget -q "${BASE_URL}/v${VERSION}/libnvidia-container-tools_${VERSION}_amd64.deb" 2>/dev/null || true
                wget -q "${BASE_URL}/v${VERSION}/nvidia-container-toolkit_${VERSION}_amd64.deb" 2>/dev/null || true
                
                if ls *.deb 1> /dev/null 2>&1; then
                    echo "  Installing downloaded packages..."
                    dpkg -i *.deb 2>/dev/null || apt-get install -f -y 2>/dev/null
                    
                    if command -v nvidia-ctk &> /dev/null; then
                        nvidia-ctk runtime configure --runtime=docker > /dev/null 2>&1 || true
                        systemctl restart docker 2>/dev/null || true
                        echo -e "${GREEN}✓ NVIDIA Container Toolkit installed from GitHub${NC}"
                    else
                        echo -e "${YELLOW}⚠ Installation incomplete${NC}"
                    fi
                else
                    echo -e "${YELLOW}⚠ Could not install NVIDIA container support${NC}"
                    echo -e "${YELLOW}⚠ GPU support in Docker may not work${NC}"
                    echo -e "${BLUE}ℹ Manual installation: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html${NC}"
                fi
                
                cd - > /dev/null
                rm -rf "$TMPDIR"
            fi
        fi
        rm -f /tmp/nvidia-install.log
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

# Проверяем наличие requirements.txt
if [ ! -f "requirements.txt" ]; then
    echo -e "${RED}Error: requirements.txt not found in $INSTALL_DIR${NC}"
    exit 1
fi

echo "  Upgrading pip..."
pip3 install --upgrade pip --break-system-packages > /dev/null 2>&1 || echo "  (pip upgrade skipped)"

echo "  Installing packages from requirements.txt..."
echo "  This may take 2-5 minutes depending on your connection..."
echo ""

# Определяем нужен ли флаг --break-system-packages (для Python 3.12+ и Debian/Ubuntu 24.04+)
PIP_FLAGS=""
if python3 -c "import sys; exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
    # Проверяем, нужен ли флаг
    if pip3 install --help 2>&1 | grep -q "break-system-packages"; then
        PIP_FLAGS="--break-system-packages"
        echo "  Note: Using --break-system-packages flag for Python 3.11+ (this is safe for system services)"
    fi
fi

# Временно отключаем set -e для этой команды
set +e

# Устанавливаем пакеты с выводом в лог
pip3 install $PIP_FLAGS -r requirements.txt > /tmp/pip-install.log 2>&1
PIP_EXIT_CODE=$?

# Показываем важные строки из лога
cat /tmp/pip-install.log | grep -E "Collecting|Successfully installed|Requirement already|ERROR|error" | sed 's/^/    /' || true

set -e

echo ""
if [ $PIP_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ Python dependencies installed${NC}"
else
    echo -e "${RED}✗ Error: pip installation failed (exit code: $PIP_EXIT_CODE)${NC}"
    echo ""
    echo "  Full installation log:"
    cat /tmp/pip-install.log | tail -n 20 | sed 's/^/    /'
    echo ""
    echo -e "${RED}Installation cannot continue without Python dependencies${NC}"
    rm -f /tmp/pip-install.log
    exit 1
fi
rm -f /tmp/pip-install.log

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
Environment="QUDATA_API_KEY=$API_KEY"
ExecStart=/usr/bin/python3 $INSTALL_DIR/main.py
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
