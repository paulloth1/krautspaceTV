from backend.app import ssrf_check


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
