import asyncio
import io
import socket

from backend import system_info


def _fake_open(mapping):
    def _open(path, *args, **kwargs):
        return io.StringIO(mapping[str(path)])

    return _open


# ---------------------------------------------------------------------------
# /proc parsers
# ---------------------------------------------------------------------------


def test_read_proc_uptime_parses_first_field(monkeypatch):
    monkeypatch.setattr("builtins.open", _fake_open({"/proc/uptime": "12345.67 6789.01\n"}))
    assert system_info._read_proc_uptime() == 12345.67


def test_read_loadavg_parses_first_three_fields(monkeypatch):
    monkeypatch.setattr(
        "builtins.open", _fake_open({"/proc/loadavg": "0.10 0.20 0.30 1/200 12345\n"})
    )
    assert system_info._read_loadavg() == (0.10, 0.20, 0.30)


def test_read_meminfo_computes_used_and_percent(monkeypatch):
    content = (
        "MemTotal:        1000000 kB\n"
        "MemFree:          200000 kB\n"
        "MemAvailable:     400000 kB\n"
    )
    monkeypatch.setattr("builtins.open", _fake_open({"/proc/meminfo": content}))
    assert system_info._read_meminfo() == {"total_mb": 976, "used_mb": 585, "percent": 60.0}


def test_read_meminfo_percent_is_zero_when_total_missing(monkeypatch):
    monkeypatch.setattr("builtins.open", _fake_open({"/proc/meminfo": "MemFree: 100 kB\n"}))
    result = system_info._read_meminfo()
    assert result["total_mb"] == 0
    assert result["percent"] == 0


# ---------------------------------------------------------------------------
# get_ip_addresses
# ---------------------------------------------------------------------------


class _FakeSocket:
    def __init__(self, connect_error=None, sockname=("0.0.0.0", 0)):
        self._connect_error = connect_error
        self._sockname = sockname

    def connect(self, addr):
        if self._connect_error:
            raise self._connect_error

    def getsockname(self):
        return self._sockname

    def close(self):
        pass


def test_get_ip_addresses_combines_hostname_and_outbound_lookups(monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "krautspacetv")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, family: [(family, None, None, "", ("192.168.1.5", 0))],
    )
    monkeypatch.setattr(
        socket, "socket", lambda *a, **k: _FakeSocket(sockname=("192.168.1.5", 12345))
    )
    assert system_info.get_ip_addresses() == ["192.168.1.5"]


def test_get_ip_addresses_dedupes_and_sorts(monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "krautspacetv")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, family: [(family, None, None, "", ("192.168.1.9", 0))],
    )
    # The outbound-socket lookup returns a different address than the
    # hostname lookup, so both should show up, deduped and sorted.
    monkeypatch.setattr(
        socket, "socket", lambda *a, **k: _FakeSocket(sockname=("192.168.1.2", 0))
    )
    assert system_info.get_ip_addresses() == ["192.168.1.2", "192.168.1.9"]


def test_get_ip_addresses_handles_dns_lookup_failure(monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "krautspacetv")

    def _raise(*a, **k):
        raise socket.gaierror("no dns")

    monkeypatch.setattr(socket, "getaddrinfo", _raise)
    monkeypatch.setattr(socket, "socket", lambda *a, **k: _FakeSocket(sockname=("10.0.0.5", 0)))
    assert system_info.get_ip_addresses() == ["10.0.0.5"]


def test_get_ip_addresses_handles_outbound_connect_failure(monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "host")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, None, None, "", ("10.0.0.9", 0))],
    )
    monkeypatch.setattr(
        socket, "socket", lambda *a, **k: _FakeSocket(connect_error=OSError("unreachable"))
    )
    assert system_info.get_ip_addresses() == ["10.0.0.9"]


def test_get_ip_addresses_filters_out_loopback(monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "host")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, None, None, "", ("127.0.1.1", 0))],
    )
    monkeypatch.setattr(
        socket, "socket", lambda *a, **k: _FakeSocket(sockname=("127.0.0.1", 0))
    )
    assert system_info.get_ip_addresses() == []


# ---------------------------------------------------------------------------
# _decode_throttled
# ---------------------------------------------------------------------------


def test_decode_throttled_decodes_all_bit_flags():
    result = system_info._decode_throttled("throttled=0x50005")
    assert result == {
        "undervoltage_now": True,
        "freq_capped_now": False,
        "throttled_now": True,
        "temp_limit_now": False,
        "undervoltage_since_boot": True,
        "throttled_since_boot": True,
    }


def test_decode_throttled_no_flags_set():
    result = system_info._decode_throttled("throttled=0x0")
    assert result == {
        "undervoltage_now": False,
        "freq_capped_now": False,
        "throttled_now": False,
        "temp_limit_now": False,
        "undervoltage_since_boot": False,
        "throttled_since_boot": False,
    }


def test_decode_throttled_freq_capped_and_temp_limit_bits():
    result = system_info._decode_throttled("throttled=0xa")  # 0x2 | 0x8
    assert result["freq_capped_now"] is True
    assert result["temp_limit_now"] is True
    assert result["undervoltage_now"] is False


def test_decode_throttled_malformed_input_returns_empty_dict():
    assert system_info._decode_throttled("") == {}
    assert system_info._decode_throttled("nonsense") == {}
    assert system_info._decode_throttled("throttled=notahex") == {}


# ---------------------------------------------------------------------------
# _vcgencmd
# ---------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, stdout: bytes):
        self._stdout = stdout

    async def communicate(self):
        return self._stdout, b""


async def test_vcgencmd_returns_stripped_decoded_stdout(monkeypatch):
    async def _fake_exec(*args, **kwargs):
        return _FakeProc(b"temp=42.8'C\n")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    assert await system_info._vcgencmd("measure_temp") == "temp=42.8'C"


async def test_vcgencmd_returns_empty_string_when_binary_missing(monkeypatch):
    async def _fake_exec(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    assert await system_info._vcgencmd("measure_temp") == ""


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------


async def test_get_stats_assembles_full_payload(monkeypatch):
    async def _fake_vcgencmd(*args):
        return {
            "measure_temp": "temp=42.8'C",
            "get_throttled": "throttled=0x50005",
            "measure_volts": "volt=1.2000V",
        }.get(args[0], "")

    monkeypatch.setattr(system_info, "_vcgencmd", _fake_vcgencmd)
    monkeypatch.setattr(system_info, "_read_loadavg", lambda: (0.1, 0.2, 0.3))
    monkeypatch.setattr(
        system_info, "_read_meminfo", lambda: {"total_mb": 900, "used_mb": 500, "percent": 55.6}
    )
    monkeypatch.setattr(system_info, "_read_proc_uptime", lambda: 12345.6)
    monkeypatch.setattr(system_info, "get_ip_addresses", lambda: ["192.168.1.5"])
    monkeypatch.setattr(socket, "gethostname", lambda: "krautspacetv")

    stats = await system_info.get_stats()

    assert stats["hostname"] == "krautspacetv"
    assert stats["ip_addresses"] == ["192.168.1.5"]
    assert stats["cpu_temp_c"] == 42.8
    assert stats["core_voltage_v"] == 1.2
    assert stats["throttled"]["undervoltage_now"] is True
    assert stats["throttled"]["throttled_since_boot"] is True
    assert stats["load_avg"] == {"1m": 0.1, "5m": 0.2, "15m": 0.3}
    assert stats["memory"] == {"total_mb": 900, "used_mb": 500, "percent": 55.6}
    assert stats["uptime_seconds"] == 12345


async def test_get_stats_handles_missing_vcgencmd_gracefully(monkeypatch):
    async def _fake_vcgencmd(*args):
        return ""

    monkeypatch.setattr(system_info, "_vcgencmd", _fake_vcgencmd)
    monkeypatch.setattr(system_info, "_read_loadavg", lambda: (0.0, 0.0, 0.0))
    monkeypatch.setattr(
        system_info, "_read_meminfo", lambda: {"total_mb": 0, "used_mb": 0, "percent": 0}
    )
    monkeypatch.setattr(system_info, "_read_proc_uptime", lambda: 0.0)
    monkeypatch.setattr(system_info, "get_ip_addresses", lambda: [])
    monkeypatch.setattr(socket, "gethostname", lambda: "host")

    stats = await system_info.get_stats()
    assert stats["cpu_temp_c"] is None
    assert stats["core_voltage_v"] is None
    assert stats["throttled"] == {}


async def test_get_stats_ignores_unparseable_temp_and_voltage(monkeypatch):
    async def _fake_vcgencmd(*args):
        return {
            "measure_temp": "temp=notanumber'C",
            "get_throttled": "throttled=0x0",
            "measure_volts": "volt=notanumberV",
        }.get(args[0], "")

    monkeypatch.setattr(system_info, "_vcgencmd", _fake_vcgencmd)
    monkeypatch.setattr(system_info, "_read_loadavg", lambda: (0.0, 0.0, 0.0))
    monkeypatch.setattr(
        system_info, "_read_meminfo", lambda: {"total_mb": 0, "used_mb": 0, "percent": 0}
    )
    monkeypatch.setattr(system_info, "_read_proc_uptime", lambda: 0.0)
    monkeypatch.setattr(system_info, "get_ip_addresses", lambda: [])
    monkeypatch.setattr(socket, "gethostname", lambda: "host")

    stats = await system_info.get_stats()
    assert stats["cpu_temp_c"] is None
    assert stats["core_voltage_v"] is None
