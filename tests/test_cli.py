from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from click.testing import CliRunner

import xpctl.cli as cli
import xpctl.cli.admin as cli_admin
import xpctl.cli.exec as cli_exec
import xpctl.cli.support as cli_support
import xpctl.cli.system as cli_system
from xpctl.transport.tcp import TCPTransport


def test_net_portfwd_omits_empty_user(monkeypatch):
    captured = {}

    class DummyProc:
        pid = 123

    def fake_popen(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        return DummyProc()

    monkeypatch.setattr(cli_system.subprocess, "Popen", fake_popen)

    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        [
            "--host",
            "xp.example",
            "--user",
            "",
            "net",
            "portfwd",
            "8080",
            "127.0.0.1",
            "80",
        ],
    )

    assert result.exit_code == 0
    assert captured["cmd"][-1] == "xp.example"


def test_net_portfwd_rejects_password():
    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        [
            "--host",
            "xp.example",
            "--password",
            "secret",
            "net",
            "portfwd",
            "8080",
            "127.0.0.1",
            "80",
        ],
    )

    assert result.exit_code != 0
    assert "does not support --password" in result.output


def test_env_set_no_persist_is_rejected():
    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        ["--host", "xp.example", "env", "set", "FOO", "BAR", "--no-persist"],
    )

    assert result.exit_code != 0
    assert "--no-persist" in result.output


def test_agent_stop_passes_selected_port(monkeypatch):
    captured = {}

    class FakeDeployer:
        def __init__(self, ssh):
            captured["ssh"] = ssh

        def stop(self, port):
            captured["port"] = port

    monkeypatch.setattr(cli_admin, "AgentDeployer", FakeDeployer)
    monkeypatch.setattr(cli_admin, "SSHTransport", lambda *args, **kwargs: object())

    runner = CliRunner()
    result = runner.invoke(
        cli.main, ["--host", "xp.example", "--port", "4321", "agent", "stop"]
    )

    assert result.exit_code == 0
    assert captured["port"] == 4321


def test_shell_requires_tcp_agent(monkeypatch):
    class DummyClient:
        def __init__(self):
            self._transport = object()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(cli_support, "_client", lambda ctx: DummyClient())

    runner = CliRunner()
    result = runner.invoke(cli.main, ["--host", "xp.example", "shell"])

    assert result.exit_code != 0
    assert "requires the TCP agent transport" in result.output


def test_require_tcp_agent_accepts_tcp_transport():
    client = type("DummyClient", (), {"_transport": TCPTransport("127.0.0.1")})()
    cli_support._require_tcp_agent(client, "feature")


def test_setup_installers_include_x64dbg():
    assert "x64dbg" in cli_admin.INSTALLERS


def test_setup_installers_dir_points_to_repo_bundles():
    assert cli_admin.INSTALLERS_DIR == Path(__file__).resolve().parents[1] / "installs"


def test_setup_list_reports_available_bundles():
    runner = CliRunner()
    result = runner.invoke(cli.main, ["--host", "xp.example", "setup", "list"])

    assert result.exit_code == 0
    assert "available" in result.output
    assert "missing" not in result.output


def test_run_host_command_verifies_host_key_by_default(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cli_support.subprocess, "run", fake_run)

    cli_support._run_host_command(
        ["qm", "snapshot", "100", "clean"],
        ssh_host="proxmox.example",
        ssh_user="root",
    )

    assert captured["cmd"] == [
        "ssh",
        "root@proxmox.example",
        "qm snapshot 100 clean",
    ]
    assert captured["timeout"] == 30


def test_run_host_command_disables_host_key_checks_only_when_requested(monkeypatch):
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cli_support.subprocess, "run", fake_run)

    cli_support._run_host_command(
        ["qm", "snapshot", "100", "clean"],
        ssh_host="proxmox.example",
        ssh_user="root",
        verify_host_key=False,
    )

    assert captured["cmd"] == [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "root@proxmox.example",
        "qm snapshot 100 clean",
    ]
    assert captured["timeout"] == 30


def test_run_host_command_normalizes_local_oserror(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        raise OSError("missing binary")

    monkeypatch.setattr(cli_support.subprocess, "run", fake_run)

    result = cli_support._run_host_command(["qm", "status", "100"])

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "missing binary"


def test_run_host_command_normalizes_ssh_timeout(monkeypatch):
    def fake_run(cmd, capture_output, text, timeout):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(cli_support.subprocess, "run", fake_run)

    result = cli_support._run_host_command(
        ["qm", "status", "100"],
        ssh_host="proxmox.example",
    )

    assert result.returncode == 124
    assert result.stdout == ""
    assert "timed out" in result.stderr


def test_snapshot_commands_forward_verify_host_key_flag(monkeypatch):
    captured: list[bool] = []

    def fake_run_host_command(
        cmd,
        ssh_host="",
        ssh_user="root",
        verify_host_key=True,
        timeout=30,
    ):
        captured.append(verify_host_key)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cli_admin.support, "_run_host_command", fake_run_host_command)

    runner = CliRunner()
    save_result = runner.invoke(
        cli.main,
        [
            "--host",
            "xp.example",
            "--insecure-host-key",
            "snapshot",
            "save",
            "100",
            "clean",
            "--proxmox-host",
            "proxmox.example",
        ],
    )
    restore_result = runner.invoke(
        cli.main,
        [
            "--host",
            "xp.example",
            "snapshot",
            "restore",
            "100",
            "clean",
            "--proxmox-host",
            "proxmox.example",
        ],
    )

    assert save_result.exit_code == 0
    assert restore_result.exit_code == 0
    assert captured == [False, True]


def test_exec_command_preserves_argument_boundaries(monkeypatch):
    captured = {}

    class DummyClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def exec(self, cmd, timeout):
            captured["cmd"] = cmd
            captured["timeout"] = timeout
            return {"stdout": "", "stderr": "", "returncode": 0}

    monkeypatch.setattr(cli_exec.support, "_client", lambda ctx: DummyClient())

    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        ["--host", "xp.example", "exec", "echo", "hello world", 'quote"here'],
    )

    expected = (
        subprocess.list2cmdline(["echo", "hello world", 'quote"here'])
        if os.name == "nt"
        else shlex.join(["echo", "hello world", 'quote"here'])
    )
    assert result.exit_code == 0
    assert captured["cmd"] == expected
    assert captured["timeout"] == 30


def test_watch_command_preserves_argument_boundaries(monkeypatch):
    captured = {}

    class DummyClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def exec(self, cmd, timeout):
            captured["cmd"] = cmd
            captured["timeout"] = timeout
            return {"stdout": "", "stderr": "", "returncode": 0}

    monkeypatch.setattr(cli_exec.support, "_client", lambda ctx: DummyClient())

    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        [
            "--host",
            "xp.example",
            "watch",
            "--count",
            "1",
            "--interval",
            "0",
            "echo",
            "hello world",
            'quote"here',
        ],
    )

    expected = (
        subprocess.list2cmdline(["echo", "hello world", 'quote"here'])
        if os.name == "nt"
        else shlex.join(["echo", "hello world", 'quote"here'])
    )
    assert result.exit_code == 0
    assert captured["cmd"] == expected
    assert captured["timeout"] == 30


def test_agent_reboot_nowait_reports_request_failures(monkeypatch):
    class DummyClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def _request(self, action, params):
            assert action == "reboot"
            assert params == {"delay": 0, "force": True}
            return {"rebooting": False, "returncode": 1, "stderr": "access denied"}

    monkeypatch.setattr(cli_admin.support, "_client", lambda ctx: DummyClient())

    runner = CliRunner()
    result = runner.invoke(
        cli.main,
        ["--host", "xp.example", "agent", "reboot", "--no-wait"],
    )

    assert result.exit_code == 1
    assert "access denied" in result.output
    assert "Reboot initiated (not waiting)." not in result.output
