"""System information plugin."""
import platform
import psutil
import datetime

PLUGIN = {
    "name": "system",
    "description": "Local system information and status",
    "tools": [
        {
            "name": "system_info",
            "description": "Get current system information (OS, CPU, memory, time)",
            "parameters": {"type": "object", "properties": {}}
        }
    ]
}

def system_info() -> str:
    info = {
        "os": f"{platform.system()} {platform.release()}",
        "architecture": platform.machine(),
        "cpu_count": psutil.cpu_count(),
        "memory_gb": round(psutil.virtual_memory().total / (1024**3), 1),
        "memory_used_percent": psutil.virtual_memory().percent,
        "local_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return "\n".join(f"{k}: {v}" for k, v in info.items())
