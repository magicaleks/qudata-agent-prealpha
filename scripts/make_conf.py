#!/usr/bin/env python3
import json
import re
import subprocess
from typing import Optional

try:
    import requests  # type: ignore
except Exception:
    requests = None  # type: ignore


def sh(cmd: str) -> str:
    try:
        out = subprocess.check_output(
            cmd,
            shell=True,
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return ""


# ---------------- CPU / Memory / Disk ---------------- #
def get_cpu_info() -> dict:
    data = sh("lscpu")
    info = {}
    for line in data.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            info[k.strip()] = v.strip()
    return info


def get_mem_info() -> dict:
    try:
        total_kb = int(sh("grep MemTotal /proc/meminfo | awk '{print $2}'"))
        return {"amount": round(total_kb / 1024 / 1024, 2), "unit": "gb"}
    except Exception:
        return {"amount": 0, "unit": "gb"}


def get_disk_info() -> dict:
    try:
        size_gb = float(
            sh("lsblk -b -d -n -o SIZE | awk '{s+=$1} END {print " "s/1024/1024/1024}'")
        )
        return {"amount": round(size_gb, 2), "unit": "gb"}
    except Exception:
        return {"amount": 0, "unit": "gb"}


def get_network_speed() -> tuple[Optional[float], Optional[float]]:
    iface = sh("ip route | grep default | awk '{print $5}'")
    if not iface:
        return None, None
    out = sh(f"ethtool {iface} 2>/dev/null | grep Speed | awk '{{print $2}}'")
    try:
        speed_gbps = float(out.replace("Mb/s", "")) / 1000.0
        return speed_gbps, speed_gbps
    except Exception:
        return None, None


# ---------------- GPU ---------------- #
def get_gpu_info():
    gpu_name = sh("nvidia-smi --query-gpu=name --format=csv,noheader | head -n1")
    if not gpu_name:
        return None, 0, 0.0, None
    gpus = sh("nvidia-smi --query-gpu=name --format=csv,noheader | wc -l")
    gpu_amount = int(gpus.strip() or 1)
    vram = sh(
        "nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits "
        "| head -n1"
    )
    vram_gb = round(float(vram) / 1024.0, 2) if vram else 0.0
    max_cuda = sh("nvidia-smi | grep -m1 CUDA | awk '{print $NF}'")
    try:
        max_cuda_v = float(re.findall(r"[\d.]+", max_cuda)[0])
    except Exception:
        max_cuda_v = None
    return gpu_name, gpu_amount, vram_gb, max_cuda_v


# ---------------- Location ---------------- #
def get_location() -> dict:
    try:
        if requests:
            resp = requests.get("https://ipinfo.io/json", timeout=2)
            resp.raise_for_status()
            data = resp.json()
        else:
            import json as _json
            import urllib.request

            with urllib.request.urlopen("https://ipinfo.io/json", timeout=2) as r:
                data = _json.load(r)
        return {
            "city": data.get("city"),
            "country": data.get("country"),
            "region": data.get("region"),
        }
    except Exception:
        return {"city": None, "country": None, "region": None}


# ---------------- CoCo Hardware Detection ---------------- #
def detect_coco_capabilities() -> dict:
    flags = sh("grep flags /proc/cpuinfo | head -n1 | tr '[:upper:]' '[:lower:]'")
    has_sev = "sev" in flags
    has_snp = "sev_snp" in flags or "sev-snp" in flags
    has_tdx = bool(sh("grep -w tdx_guest /proc/cpuinfo"))
    iommu_on = bool(re.search(r"intel_iommu=on|amd_iommu=on", sh("cat /proc/cmdline")))
    return {
        "sev": has_sev,
        "sev_snp": has_snp,
        "tdx": has_tdx,
        "iommu": iommu_on,
        "coco_capable": has_sev or has_snp or has_tdx,
    }


# ---------------- Main detection ---------------- #
def detect_configuration() -> dict:
    cpu = get_cpu_info()
    mem = get_mem_info()
    disk = get_disk_info()
    net_in, net_out = get_network_speed()
    gpu_name, gpu_amount, vram, cuda = get_gpu_info()
    loc = get_location()
    coco = detect_coco_capabilities()

    try:
        vcpu = int(cpu.get("CPU(s)", "0"))
    except Exception:
        vcpu = 0
    try:
        cpu_cores = int(cpu.get("Core(s) per socket", "0") or 0)
    except Exception:
        cpu_cores = 0
    mhz_match = re.findall(r"[\d.]+", cpu.get("CPU MHz", "") or "")
    cpu_freq = float(mhz_match[0]) if mhz_match else 0.0

    conf = {
        "ram": mem,
        "disk": disk,
        "cpu_name": cpu.get("Model name") or cpu.get("Model") or "",
        "vcpu": vcpu,
        "cpu_cores": cpu_cores,
        "cpu_freq": cpu_freq,
        "ethernet_in": net_in,
        "ethernet_out": net_out,
        "max_cuda_version": cuda,
    }

    host = {
        "gpu_name": gpu_name or "No GPU",
        "gpu_amount": gpu_amount,
        "vram": vram,
        "location": loc,
        "configuration": conf,
    }

    result = host
    result["coco_status"] = coco
    result["kernel"] = sh("uname -r")
    result["os"] = sh("lsb_release -ds || cat /etc/os-release | head -n1")
    return result


def main():
    result = detect_configuration()
    out_path = "/var/log/kataguard/host_report.json"
    # os.makedirs(os.path.dirname(out_path), exist_ok=True)
    # with open(out_path, "w", encoding="utf-8") as f:
    #     json.dump(result, f, indent=2, ensure_ascii=False)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"\n[✔] JSON report saved to {out_path}")


if __name__ == "__main__":
    main()
