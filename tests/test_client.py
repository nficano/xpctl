from __future__ import annotations

from pathlib import Path

from xpctl.client import XPClient
from xpctl.transport.factory import ConnectionProfile


class _FakeTransport:
    def __init__(self):
        self.connected = False
        self.requests = []

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def send_request(self, action, params=None):
        self.requests.append((action, params))
        if action == "ping":
            return {"pong": True}
        return {"ok": True}

    def is_connected(self):
        return self.connected


class _FakeFactory:
    def __init__(self):
        self.calls = []
        self.transport = _FakeTransport()

    def create(self, mode, profile):
        self.calls.append((mode, profile))
        return self.transport

    def create_tcp(self, profile):
        self.calls.append(("tcp-probe", profile))
        return self.transport


def test_client_connect_uses_injected_transport_factory():
    factory = _FakeFactory()
    client = XPClient(
        host="xp.example",
        port=4321,
        transport="ssh",
        user="alice",
        password="secret",
        timeout=12.5,
        transport_factory=factory,
    )

    client.connect()

    assert factory.calls == [
        (
            "ssh",
            ConnectionProfile(
                host="xp.example",
                port=4321,
                user="alice",
                password="secret",
                timeout=12.5,
            ),
        )
    ]
    assert factory.transport.connected is True


def test_client_connect_is_idempotent():
    factory = _FakeFactory()
    client = XPClient(transport_factory=factory)

    client.connect()
    client.connect()

    assert len(factory.calls) == 1


def test_client_reboot_wait_requires_tcp_agent_recovery():
    class FakeSocket:
        def __init__(self, *args):
            del args

        def settimeout(self, timeout):
            del timeout

        def connect(self, address):
            del address
            raise OSError("host is down")

        def close(self):
            return None

    class FakeRebootTransport(_FakeTransport):
        def send_request(self, action, params=None):
            self.requests.append((action, params))
            if action == "reboot":
                return {"rebooting": True}
            return super().send_request(action, params)

    class FakeProbeTransport(_FakeTransport):
        def send_request(self, action, params=None):
            self.requests.append((action, params))
            if action == "ping":
                return {"pong": False}
            return super().send_request(action, params)

    class FakeFactory:
        def __init__(self):
            self.calls = []

        def create(self, mode, profile):
            self.calls.append((mode, profile))
            return FakeRebootTransport()

        def create_tcp(self, profile):
            self.calls.append(("tcp-probe", profile))
            return FakeProbeTransport()

    moments = iter([0.0, 0.0, 30.0, 30.0, 34.0, 36.0])
    factory = FakeFactory()
    client = XPClient(
        transport="auto",
        timeout=9.0,
        transport_factory=factory,
        sleep=lambda _: None,
        monotonic=lambda: next(moments),
        socket_factory=FakeSocket,
    )
    client.connect()

    assert client.reboot(wait=True, timeout=5.0, poll_interval=1.0) is False
    assert factory.calls[-1] == (
        "tcp-probe",
        ConnectionProfile(timeout=1.0, probe_timeout=1.0),
    )


def test_client_push_and_run_quotes_remote_dir(tmp_path: Path):
    script = tmp_path / "hello.py"
    script.write_text("print('hello')", encoding="utf-8")

    transport = _FakeTransport()

    class FakeFactory:
        def create(self, mode, profile):
            del mode, profile
            return transport

    client = XPClient(transport_factory=FakeFactory())
    client.connect()

    client.push_and_run(script, remote_dir=r"C:\Program Files\xpctl scripts")

    assert transport.requests[0] == (
        "exec",
        {
            "cmd": 'mkdir "C:\\Program Files\\xpctl scripts"',
            "timeout": 30,
            "shell": "cmd",
        },
    )


def test_client_bat_push_run_quotes_remote_dir(tmp_path: Path):
    script = tmp_path / "hello.bat"
    script.write_text("@echo off\r\necho hello\r\n", encoding="utf-8")

    transport = _FakeTransport()

    class FakeFactory:
        def create(self, mode, profile):
            del mode, profile
            return transport

    client = XPClient(transport_factory=FakeFactory())
    client.connect()

    client.bat_push_run(script, remote_dir=r"C:\Program Files\xpctl scripts")

    assert transport.requests[0] == (
        "exec",
        {
            "cmd": 'mkdir "C:\\Program Files\\xpctl scripts"',
            "timeout": 30,
            "shell": "cmd",
        },
    )
