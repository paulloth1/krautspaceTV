from backend.app import _canary_config, ssrf_check


def test_ssrf_check_rejects_loopback():
    assert ssrf_check("http://127.0.0.1/") is not None


def test_ssrf_check_rejects_rfc1918_10_range():
    assert ssrf_check("http://10.0.0.5/") is not None


def test_ssrf_check_rejects_rfc1918_172_range():
    assert ssrf_check("http://172.16.0.5/") is not None


def test_ssrf_check_rejects_rfc1918_192_168_range():
    assert ssrf_check("http://192.168.1.1/") is not None


def test_ssrf_check_rejects_link_local():
    assert ssrf_check("http://169.254.1.1/") is not None


def test_ssrf_check_rejects_non_http_scheme():
    assert ssrf_check("file:///etc/passwd") is not None


def test_ssrf_check_rejects_missing_hostname():
    assert ssrf_check("http:///no-host") is not None


def test_ssrf_check_accepts_public_ip_literal():
    assert ssrf_check("http://8.8.8.8/") is None


def test_ssrf_check_accepts_public_hostname():
    assert ssrf_check("http://example.com/") is None


async def test_canary_config_none_when_unconfigured(db_module, monkeypatch):
    monkeypatch.setattr("backend.app.db", db_module)
    await db_module.init_db()
    assert await _canary_config() is None


async def test_canary_config_none_when_disabled(db_module, monkeypatch):
    monkeypatch.setattr("backend.app.db", db_module)
    await db_module.init_db()
    await db_module.set_setting("canary_mqtt_host", "127.0.0.1")
    await db_module.set_setting("canary_enabled", "no")
    assert await _canary_config() is None


async def test_canary_config_present_when_enabled_and_configured(db_module, monkeypatch):
    monkeypatch.setattr("backend.app.db", db_module)
    await db_module.init_db()
    await db_module.set_setting("canary_mqtt_host", "127.0.0.1")
    await db_module.set_setting("canary_mqtt_port", "1884")
    await db_module.set_setting("canary_topic_prefix", "my/canary")
    # canary_enabled deliberately left unset - defaults to "yes"
    assert await _canary_config() == (
        "127.0.0.1", 1884, "my/canary/event", "my/canary/state", "my/canary/status"
    )
