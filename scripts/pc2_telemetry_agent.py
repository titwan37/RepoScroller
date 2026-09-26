"""Lightweight PC2 Hardware Telemetry Agent for RepoScroller.
Exposes OS CPU %, Host RAM Used/Total, and NVIDIA GeForce RTX 3060 GPU Compute % and VRAM over HTTP on port 11435.
"""

import sys
import json
import time
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 11435


def get_hardware_metrics():
    # 1. CPU & RAM via Windows CIM or psutil
    cpu_pct = 0
    total_ram_mb = 16384
    used_ram_mb = 8192
    ram_pct = 50.0

    try:
        import psutil
        cpu_pct = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        total_ram_mb = round(mem.total / (1024 * 1024))
        used_ram_mb = round(mem.used / (1024 * 1024))
        ram_pct = mem.percent
    except ImportError:
        # Fallback to PowerShell CIM
        try:
            cmd = "powershell -NoProfile -Command \"(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average; $os = Get-CimInstance Win32_OperatingSystem; $os.TotalVisibleMemorySize; $os.FreePhysicalMemory\""
            out = subprocess.check_output(cmd, shell=True, timeout=2).decode().split()
            if len(out) >= 3:
                cpu_pct = round(float(out[0]))
                tot_kb = float(out[1])
                free_kb = float(out[2])
                total_ram_mb = round(tot_kb / 1024)
                used_ram_mb = round((tot_kb - free_kb) / 1024)
                ram_pct = round((used_ram_mb / max(1, total_ram_mb)) * 100, 1)
        except Exception:
            pass

    # 2. NVIDIA GPU metrics via nvidia-smi
    gpu_util = 0
    vram_used_mb = 0
    vram_total_mb = 6144
    gpu_temp = 0
    gpu_name = "NVIDIA GeForce RTX 3060 Laptop GPU"

    try:
        smi_cmd = "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,name --format=csv,noheader,nounits"
        out = subprocess.check_output(smi_cmd, shell=True, timeout=2).decode().strip()
        parts = [p.strip() for p in out.split(',')]
        if len(parts) >= 4:
            gpu_util = int(parts[0])
            vram_used_mb = int(parts[1])
            vram_total_mb = int(parts[2])
            gpu_temp = int(parts[3])
            if len(parts) >= 5:
                gpu_name = parts[4]
    except Exception:
        pass

    return {
        "node": "PC2-NITRO-AN51755",
        "status": "online",
        "timestamp": time.strftime("%H:%M:%S"),
        "cpu_percent": cpu_pct,
        "ram": {
            "used_mb": used_ram_mb,
            "total_mb": total_ram_mb,
            "used_gb": round(used_ram_mb / 1024, 1),
            "total_gb": round(total_ram_mb / 1024, 1),
            "percent": ram_pct
        },
        "gpu": {
            "model": gpu_name,
            "load_percent": gpu_util,
            "vram_used_mb": vram_used_mb,
            "vram_total_mb": vram_total_mb,
            "vram_percent": round((vram_used_mb / max(1, vram_total_mb)) * 100, 1),
            "temperature_c": gpu_temp
        }
    }


class TelemetryHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        metrics = get_hardware_metrics()
        body = json.dumps(metrics, indent=2).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # Silent console logs


def main():
    server = HTTPServer(('0.0.0.0', PORT), TelemetryHandler)
    print(f"[PC2 Telemetry Agent] Listening on http://0.0.0.0:{PORT}/ (Press Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping PC2 Telemetry Agent...")
        server.server_close()


if __name__ == "__main__":
    main()
