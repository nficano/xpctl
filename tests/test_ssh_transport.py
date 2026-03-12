from __future__ import annotations

import time

import paramiko
import pytest

from xpctl.transport.ssh import SSHTransport


def test_startup_actions_are_supported_in_ssh_mode(monkeypatch):
    calls = []

    def fake_run_python_json(self, script, payload, timeout=30):
        calls.append((script, payload, timeout))
        return {"ok": True}

    monkeypatch.setattr(SSHTransport, "_run_python_json", fake_run_python_json)

    transport = SSHTransport()

    assert transport.send_request("startup_status") == {"ok": True}
    assert transport.send_request("remove_startup") == {"ok": True}
    assert transport.send_request("install_startup", {"port": 7777}) == {"ok": True}
    assert len(calls) == 3


class _FakeChannel:
    def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
        self._stdout = stdout
        self._stderr = stderr
        self._returncode = returncode
        self._stdout_read = False
        self._stderr_read = False

    def settimeout(self, timeout):
        return None

    def recv_ready(self):
        return not self._stdout_read and bool(self._stdout)

    def recv(self, size):
        del size
        self._stdout_read = True
        return self._stdout

    def recv_stderr_ready(self):
        return not self._stderr_read and bool(self._stderr)

    def recv_stderr(self, size):
        del size
        self._stderr_read = True
        return self._stderr

    def exit_status_ready(self):
        return self._stdout_read or not self._stdout

    def recv_exit_status(self):
        return self._returncode

    def close(self):
        return None


class _FakeStdout:
    def __init__(self, channel):
        self.channel = channel


def test_run_ssh_retries_via_decorator(monkeypatch):
    attempts = []
    sleeps = []

    class FakeClient:
        def exec_command(self, remote_cmd, timeout=30):
            attempts.append((remote_cmd, timeout))
            if len(attempts) == 1:
                raise RuntimeError("Connection reset by peer")
            channel = _FakeChannel(stdout=b"ok\n", returncode=0)
            return None, _FakeStdout(channel), None

    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))

    transport = SSHTransport()
    transport._client = FakeClient()

    result = transport._run_ssh("echo ok", timeout=7)

    assert result.stdout == "ok\n"
    assert attempts == [("echo ok", 7), ("echo ok", 7)]
    assert sleeps == [1]


def test_run_ssh_does_not_retry_connection_error():
    transport = SSHTransport()

    with pytest.raises(ConnectionError):
        transport._run_ssh("echo ok")


def test_connect_keeps_command_only_ssh_mode_when_sftp_is_unavailable(monkeypatch):
    captured = {}

    class FakeClient:
        def load_system_host_keys(self):
            captured["loaded_host_keys"] = True

        def set_missing_host_key_policy(self, policy):
            captured["policy"] = policy

        def connect(self, **kwargs):
            captured["connect_args"] = kwargs

        def open_sftp(self):
            raise paramiko.SSHException("sftp subsystem unavailable")

        def close(self):
            captured["closed"] = True

    monkeypatch.setattr(paramiko, "SSHClient", FakeClient)

    transport = SSHTransport(host="xp.example")
    transport.connect()

    assert transport.is_connected() is True
    assert transport._client is not None
    assert transport._sftp is None
    assert "sftp subsystem unavailable" in str(transport._sftp_error)
    assert captured["loaded_host_keys"] is True
    assert type(captured["policy"]).__name__ == "RejectPolicy"


def test_connect_allows_opt_in_insecure_host_key_policy(monkeypatch):
    captured = {}

    class FakeClient:
        def load_system_host_keys(self):
            return None

        def set_missing_host_key_policy(self, policy):
            captured["policy"] = policy

        def connect(self, **kwargs):
            del kwargs

        def open_sftp(self):
            return object()

        def close(self):
            return None

    monkeypatch.setattr(paramiko, "SSHClient", FakeClient)

    transport = SSHTransport(verify_host_key=False)
    transport.connect()

    assert type(captured["policy"]).__name__ == "AutoAddPolicy"
