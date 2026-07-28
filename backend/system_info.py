import asyncio
import socket


def _read_proc_uptime() -> float:
    with open("/proc/uptime") as f:
        return float(f.read().split()[0])


def _read_loadavg() -> tuple[float, float, float]:
    with open("/proc/loadavg") as f:
        parts = f.read().split()
    return float(parts[0]), float(parts[1]), float(parts[2])


def _read_meminfo() -> dict:
    values = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, _, rest = line.partition(":")
            values[key] = int(rest.strip().split()[0])  # kB
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    used = total - available
    return {
        "total_mb": total // 1024,
        "used_mb": used // 1024,
        "percent": round(used / total * 100, 1) if total else 0,
    }


def get_ip_addresses() -> list[str]:
    ips = set()
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ips.add(info[4][0])
    except socket.gaierror:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    ips = {ip for ip in ips if not ip.startswith("127.")}
    return sorted(ips)


async def _vcgencmd(*args: str) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            "vcgencmd", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip()
    except FileNotFoundError:
        return ""


def _decode_throttled(raw: str) -> dict:
    try:
        value = int(raw.split("=")[1], 16)
    except (IndexError, ValueError):
        return {}
    return {
        "undervoltage_now": bool(value & 0x1),
        "freq_capped_now": bool(value & 0x2),
        "throttled_now": bool(value & 0x4),
        "temp_limit_now": bool(value & 0x8),
        "undervoltage_since_boot": bool(value & 0x10000),
        "throttled_since_boot": bool(value & 0x40000),
    }


async def get_stats() -> dict:
    temp_raw, throttled_raw, volts_raw = await asyncio.gather(
        _vcgencmd("measure_temp"), _vcgencmd("get_throttled"), _vcgencmd("measure_volts", "core")
    )
    temp_c = None
    if "=" in temp_raw:
        try:
            temp_c = float(temp_raw.split("=")[1].replace("'C", ""))
        except ValueError:
            pass
    core_voltage_v = None
    if "=" in volts_raw:
        try:
            core_voltage_v = float(volts_raw.split("=")[1].replace("V", ""))
        except ValueError:
            pass
    load1, load5, load15 = _read_loadavg()
    return {
        "ip_addresses": get_ip_addresses(),
        "hostname": socket.gethostname(),
        "cpu_temp_c": temp_c,
        "core_voltage_v": core_voltage_v,
        "throttled": _decode_throttled(throttled_raw),
        "load_avg": {"1m": load1, "5m": load5, "15m": load15},
        "memory": _read_meminfo(),
        "uptime_seconds": int(_read_proc_uptime()),
    }
