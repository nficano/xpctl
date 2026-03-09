"""Deploy and manage the packaged agent on a Windows XP host."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from xpctl.resources import write_agent_source
from xpctl.transport.ssh import SSHTransport
from xpctl.transport.tcp import DEFAULT_PORT, TCPTransport

REMOTE_AGENT_DIR = r"C:\xpctl"
REMOTE_AGENT_PATH = rf"{REMOTE_AGENT_DIR}\agent.py"
PYTHON_EXE = r"C:\Python34\python.exe"
SMB_MOUNT = Path("/mnt/xpctl-share")
XP_EXPORT_DIR = "C:/xpctl/share"


def _copy_packaged_agent(destination: Path) -> Path:
    return write_agent_source(destination)


class AgentDeployer:
    """Handle deployment and lifecycle management for the Windows XP agent."""

    def __init__(
        self,
        ssh: SSHTransport | None = None,
        smb_mount: Path = SMB_MOUNT,
    ) -> None:
        self.ssh = ssh or SSHTransport()
        self.smb_mount = smb_mount

    def deploy(self) -> None:
        """Copy the agent over SMB, then install it into ``C:\\xpctl`` via SSH."""
        if not self.smb_mount.is_dir():
            raise FileNotFoundError(
                f"SMB share not mounted at {self.smb_mount}. "
                "Configure and mount the XP share before deploying the agent."
            )

        _copy_packaged_agent(self.smb_mount / "agent.py")
        bootstrap = self._write_bootstrap_script()
        self._ensure_ssh()
        result = self.ssh._run_ssh(
            f"C:/Python34/python.exe {XP_EXPORT_DIR}/{bootstrap.name}",
        )
        if "Installed agent" not in result.stdout:
            raise RuntimeError(
                f"SSH bootstrap failed (rc={result.returncode}): {result.stderr}\n"
                f"Agent is on the SMB share. Run {bootstrap.name} manually on XP."
            )

    def deploy_smb_only(self) -> None:
        """Copy the agent and helper batch files to the SMB share only."""
        if not self.smb_mount.is_dir():
            raise FileNotFoundError(f"SMB share not mounted at {self.smb_mount}")

        _copy_packaged_agent(self.smb_mount / "agent.py")

        start_bat = self.smb_mount / "start_agent.bat"
        start_bat.write_text(
            "@echo off\r\n"
            "if not exist C:\\xpctl mkdir C:\\xpctl\r\n"
            'copy /Y "{export}\\agent.py" "C:\\xpctl\\agent.py"\r\n'
            'start "" C:\\Python34\\python.exe C:\\xpctl\\agent.py --port 9578\r\n'
            "echo Agent started on port 9578\r\n"
            "timeout /t 3\r\n".format(export="C:\\xpctl\\share"),
            encoding="utf-8",
        )

        stop_bat = self.smb_mount / "stop_agent.bat"
        stop_bat.write_text(
            "@echo off\r\n"
            "taskkill /f /im python.exe\r\n"
            "echo Agent stopped.\r\n"
            "timeout /t 2\r\n",
            encoding="utf-8",
        )

    def start(self, port: int = DEFAULT_PORT) -> None:
        """Start the agent on the remote host via SSH."""
        self._ensure_ssh()
        agent = REMOTE_AGENT_PATH.replace("\\", "/")
        python = PYTHON_EXE.replace("\\", "/")
        log = (REMOTE_AGENT_DIR + "\\agent.log").replace("\\", "/")
        command = f"nohup {python} {agent} --port {port} > {log} 2>&1 & echo started"
        result = self.ssh._run_ssh(command, timeout=15)
        if result.returncode == 5:
            raise ConnectionError(
                "SSH rate-limited. Run start_agent.bat on XP manually, or wait and retry."
            )
        if "started" not in result.stdout:
            raise RuntimeError(f"Agent start failed: {result.stdout} {result.stderr}")
        time.sleep(2)
        self._wait_for_agent(port)

    def stop(self) -> None:
        """Stop the agent, preferring a graceful TCP shutdown first."""
        try:
            tcp = TCPTransport(self.ssh.host)
            tcp.connect()
            tcp.send_request("agent_shutdown")
            tcp.disconnect()
            time.sleep(1)
            return
        except Exception:
            pass

        if not self.ssh.is_connected():
            try:
                self.ssh.connect()
            except Exception:
                return
        self.ssh._run_ssh("taskkill /f /im python.exe")

    def status(self, port: int = DEFAULT_PORT) -> dict[str, Any]:
        try:
            tcp = TCPTransport(self.ssh.host, port=port, timeout=3.0)
            tcp.connect()
            info = tcp.send_request("agent_info")
            tcp.disconnect()
            return {"running": True, **info}
        except Exception:
            return {"running": False}

    def redeploy(self, port: int = DEFAULT_PORT) -> None:
        self.stop()
        time.sleep(1)
        self.deploy()
        self.start(port)

    def install(self, port: int = DEFAULT_PORT) -> None:
        """Deploy, start, and register the agent to boot automatically."""
        self.deploy()
        self.start(port)
        tcp = TCPTransport(self.ssh.host, port=port, timeout=5.0)
        tcp.connect()
        try:
            tcp.send_request("install_startup", {"port": port})
        finally:
            tcp.disconnect()

    def uninstall(self, port: int = DEFAULT_PORT) -> None:
        """Remove startup registration, stop the agent, and delete its files."""
        try:
            tcp = TCPTransport(self.ssh.host, port=port, timeout=5.0)
            tcp.connect()
            tcp.send_request("remove_startup")
            tcp.disconnect()
        except Exception:
            pass

        self.stop()
        self._ensure_ssh()
        self.ssh._run_ssh("cmd.exe /c rmdir /s /q C:\\xpctl")

    def _ensure_ssh(self) -> None:
        if not self.ssh.is_connected():
            self.ssh.connect()

    def _write_bootstrap_script(self) -> Path:
        bootstrap = self.smb_mount / "bootstrap_agent.py"
        export_source = XP_EXPORT_DIR.replace("/", "\\") + "\\agent.py"
        bootstrap.write_text(
            "import os, shutil\n"
            f"src = r'{export_source}'\n"
            f"dst_dir = r'{REMOTE_AGENT_DIR}'\n"
            f"dst = r'{REMOTE_AGENT_PATH}'\n"
            "if not os.path.isdir(dst_dir):\n"
            "    os.makedirs(dst_dir)\n"
            "shutil.copy2(src, dst)\n"
            "print('Installed agent to ' + dst)\n",
            encoding="utf-8",
        )
        return bootstrap

    def _wait_for_agent(self, port: int, timeout: float = 10.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                tcp = TCPTransport(self.ssh.host, port=port, timeout=2.0)
                tcp.connect()
                tcp.send_request("ping")
                tcp.disconnect()
                return
            except Exception:
                time.sleep(0.5)
        raise TimeoutError(f"Agent did not start within {timeout}s")
