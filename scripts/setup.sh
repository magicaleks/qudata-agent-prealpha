#!/usr/bin/env bash
# setup.sh — Production версия установки Docker, Kata, CoCo, GPU и auth plugin + deps для detect_host_config

set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

REPORT="/var/log/kataguard/agent/report.json"
PLUGIN_SVC="docker-auth-plugin.service"
PLUGIN_SOCK="/run/docker/plugins/kata_guard.sock"
AGENT_SOCK="/run/kataguard/agent.sock"
PLUGIN_PATH="/usr/local/bin/docker_auth_plugin.py"

bool() { [[ "$1" == "true" || "$1" == true ]] && echo true || echo false; }
svc_active() { systemctl is-active --quiet "$1" && echo true || echo false; }
file_exists() { [[ -e "$1" ]] && echo true || echo false; }
cmd_exists() { command -v "$1" >/dev/null 2>&1 && echo true || echo false; }

echo "[1] Базовые зависимости"
apt-get update -y
apt-get install -y --no-install-recommends \
    ca-certificates curl wget gnupg lsb-release software-properties-common \
    python3 python3-pip pciutils jq dmidecode ethtool net-tools iproute2 \
    util-linux coreutils grep awk sed lscpu lsblk virt-what
pip install --no-input aiohttp requests || true

echo "[2] Docker установка"
install -d /usr/share/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" >/etc/apt/sources.list.d/docker.list
apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
mkdir -p /etc/containerd
containerd config default >/etc/containerd/config.toml || true
systemctl restart containerd

echo "[3] Kata установка и CoCo детекция"
curl -fsSL https://repo.katacontainers.io/archive.key | gpg --dearmor -o /usr/share/keyrings/kata.gpg
echo "[3] Установка Kata Containers (через kata-manager.sh)"
KATA_SCRIPT_URL="https://raw.githubusercontent.com/kata-containers/kata-containers/main/utils/kata-manager.sh"
KATA_SCRIPT="/usr/local/bin/kata-manager.sh"
sudo curl -fsSL "$KATA_SCRIPT_URL" -o "$KATA_SCRIPT"
sudo chmod +x "$KATA_SCRIPT"
sudo "$KATA_SCRIPT" -D || {
    echo "Ошибка установки Kata Containers"
    exit 1
}
if ! command -v kata-runtime &>/dev/null; then
    echo "❌ Kata runtime не найден! Установка не удалась."
    exit 1
fi
echo "✅ Kata Containers успешно установлены"
kata-runtime --version

CPUFLAGS=$(tr '[:upper:]' '[:lower:]' </proc/cpuinfo | grep -m1 'flags' || true)
HAS_SEV=false; HAS_SNP=false; HAS_TDX=false
grep -qw sev <<<"$CPUFLAGS" && HAS_SEV=true
grep -qw sev_snp <<<"$CPUFLAGS" && HAS_SNP=true
grep -qw tdx_guest /proc/cpuinfo 2>/dev/null && HAS_TDX=true

COCO_CAPABLE=false
if $HAS_SNP || $HAS_TDX || $HAS_SEV; then COCO_CAPABLE=true; fi

mkdir -p /etc/kata-containers
cat >/etc/kata-containers/configuration.toml <<EOF
[hypervisor.qemu]
enable_iommu = true
enable_virtiofs = true
$( $COCO_CAPABLE && echo "enable_confidential_guest = true" || echo "# enable_confidential_guest = false" )
EOF

if ! grep -q 'io.containerd.kata.v2' /etc/containerd/config.toml; then
cat >>/etc/containerd/config.toml <<'EOF'

[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.kata]
  runtime_type = "io.containerd.kata.v2"
  privileged_without_host_devices = true
EOF
fi
systemctl restart containerd

echo "[4] GPU и NVIDIA toolkit"
HAS_NVIDIA=false; lspci | grep -qi nvidia && HAS_NVIDIA=true
NVIDIA_READY=false
if $HAS_NVIDIA; then
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit.gpg
  curl -fsSL https://nvidia.github.io/libnvidia-container/$(. /etc/os-release; echo $ID$VERSION_ID)/libnvidia-container.list \
    | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit.gpg] https://#' >/etc/apt/sources.list.d/nvidia-container-toolkit.list
  apt-get update -y
  apt-get install -y nvidia-container-toolkit
  if command -v nvidia-ctk >/dev/null 2>&1; then
    nvidia-ctk runtime configure --runtime=docker || true
  fi
  systemctl restart docker || true
  (nvidia-smi >/dev/null 2>&1 && NVIDIA_READY=true) || true
fi

echo "[5] Docker Authorization Plugin"
cat >"$PLUGIN_PATH" <<'PY'
#!/usr/bin/env python3
import os, json, asyncio
from aiohttp import web
AGENT="/run/kataguard/agent.sock"
async def talk(req_json):
    try:
        r,w=await asyncio.open_unix_connection(AGENT)
    except Exception:
        return {"allow": False, "reason": "agent_unavailable"}
    w.write(json.dumps(req_json).encode()); await w.drain()
    data=await r.read(65535); w.close(); await w.wait_closed()
    try: return json.loads(data.decode())
    except: return {"allow": False, "reason":"bad_agent_response"}
async def handle_req(request):
    try: j=await request.json()
    except: return web.json_response({"Allow": False, "Err":"bad_json"})
    req={"RequestUri":j.get("RequestUri"),"RequestMethod":j.get("RequestMethod")}
    res=await talk(req)
    return web.json_response({"Allow": bool(res.get("allow")), "Err": res.get("reason","")})
async def handle_res(request):
    try: j=await request.json()
    except: return web.json_response({"Allow": False, "Err":"bad_json"})
    req={"RequestUri":j.get("RequestUri"),"RequestMethod":j.get("RequestMethod")}
    res=await talk(req)
    return web.json_response({"Allow": bool(res.get("allow")), "Err": res.get("reason","")})
app=web.Application(); app.router.add_post("/AuthZPlugin.AuthZReq",handle_req); app.router.add_post("/AuthZPlugin.AuthZRes",handle_res)
if __name__=="__main__":
    path="/run/docker/plugins/kata_guard.sock"
    os.makedirs(os.path.dirname(path),exist_ok=True)
    try: os.unlink(path)
    except FileNotFoundError: pass
    web.run_app(app, path=path)
PY
chmod +x "$PLUGIN_PATH"

cat >/etc/systemd/system/$PLUGIN_SVC <<EOF
[Unit]
Description=Docker Authorization Plugin (kata_guard)
After=network.target docker.service
[Service]
ExecStart=/usr/bin/env python3 $PLUGIN_PATH
Restart=always
[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "$PLUGIN_SVC"

echo "[6] Docker daemon.json"
install -d /etc/docker
if [[ -f /etc/docker/daemon.json ]]; then
  cp /etc/docker/daemon.json /etc/docker/daemon.json.bak.$(date +%s)
fi
cat >/etc/docker/daemon.json <<'JSON'
{
  "authorization-plugins": ["kata_guard"]
}
JSON
systemctl restart docker || true
# Минимальная проверка ответов плагина — ожидаем HTTP 200 на оба эндпоинта
sleep 1
curl --unix-socket "$PLUGIN_SOCK" -s -o /dev/null -w '%{http_code}\n' \
  http://localhost/AuthZPlugin.AuthZReq -X POST -d '{}' | grep -q '^200$' || true
curl --unix-socket "$PLUGIN_SOCK" -s -o /dev/null -w '%{http_code}\n' \
  http://localhost/AuthZPlugin.AuthZRes -X POST -d '{}' | grep -q '^200$' || true

echo "[7] Отчёт JSON"
mkdir -p "$(dirname "$REPORT")"
DOCKER_OK=$(svc_active docker)
CONTAINERD_OK=$(svc_active containerd)
PLUGIN_OK=$(svc_active "$PLUGIN_SVC")
AUTH_ACTIVE=false; docker info 2>/dev/null | grep -qi 'Authorization' && AUTH_ACTIVE=true
KATA_BIN=$(cmd_exists kata-runtime)
KATA_VER=$(kata-runtime --version 2>/dev/null | head -n1 | awk '{print $NF}' || echo "")
AGENT_PRESENT=$(file_exists "$AGENT_SOCK")
PLUGIN_SOCKET_PRESENT=$(file_exists "$PLUGIN_SOCK")
IOMMU_ON=false; grep -Eq 'intel_iommu=on|amd_iommu=on' /proc/cmdline && IOMMU_ON=true

cat >"$REPORT" <<JSON
{
  "docker_installed": $(bool "$DOCKER_OK"),
  "containerd_running": $(bool "$CONTAINERD_OK"),
  "kata_installed": $(bool "$KATA_BIN"),
  "kata_version": "$KATA_VER",
  "coco_capable_cpu": {"sev": $(bool "$HAS_SEV"), "sev_snp": $(bool "$HAS_SNP"), "tdx": $(bool "$HAS_TDX")},
  "coco_enabled_in_config": $(bool "$COCO_CAPABLE"),
  "gpu": {"present": $(bool "$HAS_NVIDIA"), "nvidia_toolkit_ready": $(bool "$NVIDIA_READY"), "iommu_enabled": $(bool "$IOMMU_ON")},
  "auth_plugin": {"service_active": $(bool "$PLUGIN_OK"), "docker_authorization_active": $(bool "$AUTH_ACTIVE"), "plugin_socket_present": $(bool "$PLUGIN_SOCKET_PRESENT"), "agent_socket_present": $(bool "$AGENT_PRESENT")}
}
JSON

apt-get clean && rm -rf /var/lib/apt/lists/*
echo "[✔] Установка завершена. Отчёт: $REPORT"