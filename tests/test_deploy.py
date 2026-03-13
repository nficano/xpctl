from __future__ import annotations

from pathlib import Path

import pytest

import xpctl.deploy as deploy


class _Result:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def test_stop_uses_requested_port_and_targeted_kill(monkeypatch):
    tcp_calls = []
    ssh_calls = []

    class FakeTCP:
        def __init__(self, host, port=9578, timeout=10.0):
            tcp_calls.append((host, port, timeout))

        def connect(self):
            raise RuntimeError("tcp unavailable")

        def send_request(self, action):
            raise AssertionError(
                "send_request should not be called after connect failure"
            )

        def disconnect(self):
            return None

    class FakeSSH:
        host = "xp.example"

        def __init__(self):
            self.connected = False

        def is_connected(self):
            return self.connected

        def connect(self):
            self.connected = True

        def run_command(self, cmd, timeout=30):
            ssh_calls.append((cmd, timeout))
            if cmd.startswith("cmd.exe /c wmic process where"):
                return _Result(stdout="ProcessId=111\r\n\r\n")
            return _Result()

    monkeypatch.setattr(deploy, "TCPTransport", FakeTCP)

    deployer = deploy.AgentDeployer(ssh=FakeSSH())
    deployer.stop(port=4321)

    assert tcp_calls == [("xp.example", 4321, 5.0)]
    assert any("--port 4321" in cmd for cmd, _ in ssh_calls)
    assert ("taskkill /f /pid 111", 15) in ssh_calls
    assert not any("/im python.exe" in cmd for cmd, _ in ssh_calls)


def test_stop_raises_when_ssh_connection_fails(monkeypatch):
    class FakeTCP:
        def __init__(self, host, port=9578, timeout=10.0):
            pass

        def connect(self):
            raise RuntimeError("tcp unavailable")

        def disconnect(self):
            pass

    class FakeSSH:
        host = "xp.example"

        def is_connected(self):
            return False

        def connect(self):
            raise ConnectionError("ssh unavailable")

    monkeypatch.setattr(deploy, "TCPTransport", FakeTCP)

    deployer = deploy.AgentDeployer(ssh=FakeSSH())
    with pytest.raises(ConnectionError):
        deployer.stop(port=4321)


def test_stop_is_idempotent_when_agent_is_already_gone(monkeypatch):
    tcp_calls = []
    ssh_calls = []

    class FakeTCP:
        def __init__(self, host, port=9578, timeout=10.0):
            tcp_calls.append((host, port, timeout))

        def connect(self):
            raise RuntimeError("tcp unavailable")

        def disconnect(self):
            return None

    class FakeSSH:
        host = "xp.example"

        def __init__(self):
            self.connected = False

        def is_connected(self):
            return self.connected

        def connect(self):
            self.connected = True

        def run_command(self, cmd, timeout=30):
            ssh_calls.append((cmd, timeout))
            return _Result(stdout="")

    monkeypatch.setattr(deploy, "TCPTransport", FakeTCP)

    deployer = deploy.AgentDeployer(ssh=FakeSSH())
    deployer.stop(port=4321)

    assert tcp_calls == [("xp.example", 4321, 5.0)]
    assert ssh_calls == [
        (
            "cmd.exe /c wmic process where \"name='python.exe' and "
            "(CommandLine like '%C:\\xpctl\\agent.py%' or "
            "CommandLine like '%C:/xpctl/agent.py%') and "
            "(CommandLine like '%--port 4321 %' or "
            "CommandLine like '%--port 4321\"%' or "
            "CommandLine like '%--port 4321''%' or "
            "CommandLine like '%--port 4321')\" get ProcessId /value",
            30,
        )
    ]


def test_deploy_smb_only_writes_port_aware_scripts(tmp_path: Path):
    deployer = deploy.AgentDeployer(ssh=object(), smb_mount=tmp_path)
    deployer.deploy_smb_only(port=4444)

    start_text = (tmp_path / "start_agent.bat").read_text(encoding="utf-8")
    stop_text = (tmp_path / "stop_agent.bat").read_text(encoding="utf-8")

    assert "--port 4444" in start_text
    assert "taskkill /f /im python.exe" not in stop_text
    assert "wmic process where" in stop_text


def test_wmic_agent_where_clause_matches_both_windows_path_styles():
    clause = deploy._wmic_agent_where_clause(4444)

    assert r"CommandLine like '%C:\xpctl\agent.py%'" in clause
    assert "CommandLine like '%C:/xpctl/agent.py%'" in clause
    assert "CommandLine like '%--port 4444 %'" in clause
    assert "CommandLine like '%--port 4444\"%'" in clause
    assert "CommandLine like '%--port 4444''%'" in clause
    assert "CommandLine like '%--port 4444'" in clause
