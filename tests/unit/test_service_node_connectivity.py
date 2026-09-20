from platform_core.service_nodes import probe_service_node_address


class _Connection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_probe_service_node_address_uses_configured_host_and_port():
    calls = []
    connection = _Connection()

    def connector(address, timeout=None):
        calls.append((address, timeout))
        return connection

    result = probe_service_node_address(
        "http://10.20.30.40:8020/agent/health",
        timeout_seconds=1.25,
        connector=connector,
    )

    assert result == {
        "tested": True,
        "reachable": True,
        "target": "10.20.30.40:8020",
        "error": "",
    }
    assert calls == [(("10.20.30.40", 8020), 1.25)]
    assert connection.closed is True


def test_probe_service_node_address_supports_bare_host_and_default_https_port():
    calls = []

    def connector(address, timeout=None):
        calls.append((address, timeout))
        return _Connection()

    bare = probe_service_node_address("10.20.30.41:9000", connector=connector)
    secure = probe_service_node_address("https://agent.example.test/path", connector=connector)

    assert bare["reachable"] is True
    assert bare["target"] == "10.20.30.41:9000"
    assert secure["reachable"] is True
    assert secure["target"] == "agent.example.test:443"
    assert calls[0][0] == ("10.20.30.41", 9000)
    assert calls[1][0] == ("agent.example.test", 443)


def test_probe_service_node_address_reports_unreachable_without_changing_heartbeat_semantics():
    def connector(address, timeout=None):
        raise OSError("connection refused")

    result = probe_service_node_address("http://10.20.30.42:8020", connector=connector)

    assert result["tested"] is True
    assert result["reachable"] is False
    assert result["target"] == "10.20.30.42:8020"
    assert "connection refused" in result["error"]


def test_probe_service_node_address_without_agent_url_is_not_fake_failure():
    result = probe_service_node_address("")

    assert result["tested"] is False
    assert result["reachable"] is None
    assert "未配置 Agent 地址" in result["error"]
