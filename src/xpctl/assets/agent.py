#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
agent.py -- Remote management agent for Windows XP.

Single-file TCP server compatible with Python 3.4+.
Receives length-prefixed JSON requests, dispatches to action handlers,
and returns JSON responses.  No external dependencies required.

Usage:
    C:\\Python34\\python.exe agent.py --port 9578
"""

import argparse
import base64
import code
import ctypes
import json
import logging
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_VERSION = "0.1.0"
DEFAULT_PORT = 9578
DEFAULT_HOST = "0.0.0.0"
CHUNK_SIZE = 524288  # 512 KB
MAX_MESSAGE_SIZE = 50 * 1024 * 1024  # 50 MB safety limit
PYTHON_EXE = r"C:\Python34\python.exe"
INSTALL_DIR = r"C:\xpctl"
STARTUP_REG_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REG_NAME = "xpctl_agent"

log = logging.getLogger("xpctl_agent")

try:
    from io import StringIO as _StringIO
except ImportError:
    from StringIO import StringIO as _StringIO

# ---------------------------------------------------------------------------
# Wire protocol helpers
# ---------------------------------------------------------------------------


def _recv_exact(sock, n):
    """Read exactly *n* bytes from *sock*, handling partial reads."""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def recv_message(sock):
    """Read a length-prefixed JSON message and return it as a dict."""
    header = _recv_exact(sock, 4)
    if header is None:
        return None
    length = struct.unpack("!I", header)[0]
    if length > MAX_MESSAGE_SIZE:
        raise ValueError("Message too large: {0} bytes".format(length))
    payload = _recv_exact(sock, length)
    if payload is None:
        return None
    return json.loads(payload.decode("utf-8"))


def send_message(sock, msg):
    """Serialize *msg* (dict) to length-prefixed JSON and send."""
    payload = json.dumps(msg).encode("utf-8")
    header = struct.pack("!I", len(payload))
    sock.sendall(header + payload)


def make_response(request_id, data=None, error=None):
    """Build a response envelope."""
    resp = {
        "id": request_id,
        "type": "response",
        "status": "error" if error else "ok",
        "data": data or {},
        "error": error,
    }
    return resp


# ---------------------------------------------------------------------------
# Debugger manager
# ---------------------------------------------------------------------------


class DebuggerManager(object):
    """Locate debuggers and manage interactive sessions (Popen handles)."""

    KNOWN_PATHS = {
        "olly": [
            r"C:\Program Files\OllyDbg\ollydbg.exe",
            r"C:\OllyDbg\ollydbg.exe",
            r"C:\ollydbg\ollydbg.exe",
            r"C:\Tools\OllyDbg\ollydbg.exe",
            r"C:\odbg\ollydbg.exe",
        ],
        "windbg": [
            r"C:\Program Files\Debugging Tools for Windows\windbg.exe",
            r"C:\Program Files\Debugging Tools for Windows (x86)\windbg.exe",
            r"C:\Program Files\Windows Kits\8.0\Debuggers\x86\windbg.exe",
            r"C:\WinDbg\windbg.exe",
        ],
        "cdb": [
            r"C:\Program Files\Debugging Tools for Windows\cdb.exe",
            r"C:\Program Files\Debugging Tools for Windows (x86)\cdb.exe",
            r"C:\Program Files\Windows Kits\8.0\Debuggers\x86\cdb.exe",
            r"C:\WinDbg\cdb.exe",
        ],
        "x64dbg": [
            r"C:\x64dbg\release\x32\x32dbg.exe",
            r"C:\x64dbg\x32dbg.exe",
            r"C:\x64dbg\x64dbg.exe",
            r"C:\x32dbg\x32dbg.exe",
            r"C:\Tools\x64dbg\release\x32\x32dbg.exe",
            r"C:\Program Files\x64dbg\release\x32\x32dbg.exe",
        ],
    }

    def __init__(self):
        self.installed = {}  # name -> exe path
        self.sessions = {}  # session_id -> dict with Popen + metadata
        self.output_buffers = {}  # session_id -> list of output lines
        self._lock = threading.Lock()
        self._detect_installed()

    # -- detection ----------------------------------------------------------

    def _detect_installed(self):
        """Scan known paths for installed debuggers."""
        for name, paths in self.KNOWN_PATHS.items():
            for p in paths:
                if os.path.isfile(p):
                    self.installed[name] = p
                    log.info("Found debugger %s at %s", name, p)
                    break
        # Also try PATH
        for name in ("olly", "windbg", "cdb", "x64dbg"):
            if name not in self.installed:
                exe_name = {
                    "olly": "ollydbg.exe",
                    "windbg": "windbg.exe",
                    "cdb": "cdb.exe",
                    "x64dbg": "x32dbg.exe",
                }.get(name, "")
                found = shutil.which(exe_name) if hasattr(shutil, "which") else None
                if found:
                    self.installed[name] = found
                    log.info("Found debugger %s on PATH: %s", name, found)

    def list_installed(self):
        return dict(self.installed)

    # -- session lifecycle --------------------------------------------------

    def launch(self, debugger, exe_path, extra_args=None):
        """Launch *debugger* against *exe_path*.  Returns session_id."""
        dbg_exe = self._resolve(debugger)
        session_id = str(uuid.uuid4())[:8]

        args = self._build_launch_args(debugger, dbg_exe, exe_path, extra_args)
        use_pipe = debugger in ("cdb", "windbg_cli")

        log.info("Launching debugger session %s: %s", session_id, " ".join(args))
        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE if use_pipe else None,
            stdout=subprocess.PIPE if use_pipe else None,
            stderr=subprocess.PIPE if use_pipe else None,
        )

        with self._lock:
            self.sessions[session_id] = {
                "proc": proc,
                "debugger": debugger,
                "target": exe_path,
                "pipeable": use_pipe,
                "started": time.time(),
            }
            self.output_buffers[session_id] = []

        if use_pipe:
            t = threading.Thread(target=self._reader, args=(session_id,))
            t.daemon = True
            t.start()

        return session_id

    def attach(self, debugger, pid):
        """Attach *debugger* to a running process by PID."""
        dbg_exe = self._resolve(debugger)
        session_id = str(uuid.uuid4())[:8]

        args = self._build_attach_args(debugger, dbg_exe, pid)
        use_pipe = debugger in ("cdb", "windbg_cli")

        log.info("Attaching session %s to PID %s", session_id, pid)
        proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE if use_pipe else None,
            stdout=subprocess.PIPE if use_pipe else None,
            stderr=subprocess.PIPE if use_pipe else None,
        )

        with self._lock:
            self.sessions[session_id] = {
                "proc": proc,
                "debugger": debugger,
                "target": "pid:{0}".format(pid),
                "pipeable": use_pipe,
                "started": time.time(),
            }
            self.output_buffers[session_id] = []

        if use_pipe:
            t = threading.Thread(target=self._reader, args=(session_id,))
            t.daemon = True
            t.start()

        return session_id

    def send_command(self, session_id, command):
        """Write *command* to a pipeable debugger session's stdin."""
        sess = self._get_session(session_id)
        if not sess["pipeable"]:
            raise ValueError(
                "Session {0} ({1}) does not support piped commands".format(
                    session_id, sess["debugger"]
                )
            )
        proc = sess["proc"]
        if proc.poll() is not None:
            raise RuntimeError(
                "Debugger process has exited (rc={0})".format(proc.returncode)
            )
        proc.stdin.write((command + "\n").encode("utf-8"))
        proc.stdin.flush()
        time.sleep(0.3)  # give debugger a moment to produce output
        return self.read_output(session_id)

    def read_output(self, session_id):
        """Return and drain the accumulated output buffer."""
        with self._lock:
            buf = self.output_buffers.get(session_id, [])
            self.output_buffers[session_id] = []
        return "".join(buf)

    def run_script(self, debugger, session_id, script_path):
        """Execute a debugger-specific script file."""
        sess = self._get_session(session_id) if session_id else None
        dbg = debugger or (sess["debugger"] if sess else None)

        if dbg == "olly":
            # OllyDbg: launch with /SCRIPT flag (new process)
            dbg_exe = self._resolve("olly")
            target = sess["target"] if sess else ""
            args = [dbg_exe]
            if target and not target.startswith("pid:"):
                args.append(target)
            args.extend(["/SCRIPT", script_path])
            proc = subprocess.Popen(args)
            proc.wait()
            return "OllyScript executed (exit code {0})".format(proc.returncode)

        elif dbg in ("cdb", "windbg", "windbg_cli"):
            if sess and sess["pipeable"]:
                cmd = "$$><{0}".format(script_path)
                return self.send_command(session_id, cmd)
            else:
                raise ValueError("WinDbg script requires a pipeable CDB session")

        elif dbg == "x64dbg":
            if sess and sess["pipeable"]:
                cmd = 'scriptload "{0}"'.format(script_path)
                return self.send_command(session_id, cmd)
            else:
                raise ValueError("x64dbg script requires a pipeable session")

        raise ValueError("Unknown debugger: {0}".format(dbg))

    def close(self, session_id):
        """Terminate the debugger session."""
        sess = self._get_session(session_id)
        proc = sess["proc"]
        if proc.poll() is None:
            try:
                if sess["pipeable"] and proc.stdin:
                    proc.stdin.write(b"q\n")
                    proc.stdin.flush()
                    proc.wait(timeout=5)
            except Exception:
                proc.kill()
                proc.wait()
        with self._lock:
            self.sessions.pop(session_id, None)
            self.output_buffers.pop(session_id, None)
        return True

    # -- helpers ------------------------------------------------------------

    def _resolve(self, debugger):
        # "windbg" commands should use cdb for piped I/O
        lookup = debugger
        if debugger in ("windbg", "windbg_cli"):
            lookup = "cdb"
        exe = self.installed.get(lookup) or self.installed.get(debugger)
        if not exe:
            raise ValueError(
                "Debugger '{0}' not found.  Installed: {1}".format(
                    debugger, ", ".join(self.installed.keys()) or "none"
                )
            )
        return exe

    def _build_launch_args(self, debugger, dbg_exe, exe_path, extra_args):
        args = [dbg_exe]
        if debugger == "olly":
            args.append(exe_path)
            if extra_args:
                args.extend(extra_args)
        elif debugger in ("cdb", "windbg", "windbg_cli"):
            args.extend(["-g", "-G", exe_path])
            if extra_args:
                args.extend(extra_args)
        elif debugger == "x64dbg":
            args.append(exe_path)
            if extra_args:
                args.extend(extra_args)
        return args

    def _build_attach_args(self, debugger, dbg_exe, pid):
        args = [dbg_exe]
        if debugger == "olly":
            args.extend(["-p", str(pid)])
        elif debugger in ("cdb", "windbg", "windbg_cli"):
            args.extend(["-p", str(pid)])
        elif debugger == "x64dbg":
            args.extend(["-p", str(pid)])
        return args

    def _get_session(self, session_id):
        with self._lock:
            sess = self.sessions.get(session_id)
        if not sess:
            raise KeyError("No such session: {0}".format(session_id))
        return sess

    def _reader(self, session_id):
        """Background thread that reads stdout from a pipeable session."""
        sess = self._get_session(session_id)
        proc = sess["proc"]
        try:
            for line in iter(proc.stdout.readline, b""):
                decoded = line.decode("utf-8", errors="replace")
                with self._lock:
                    buf = self.output_buffers.get(session_id)
                    if buf is not None:
                        buf.append(decoded)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------


class ActionHandler(object):
    """Registry that maps action names to handler methods."""

    def __init__(self):
        self._start_time = time.time()
        self._transfers = {}  # transfer_id -> file handle + metadata
        self.debugger = DebuggerManager()
        self._handlers = {
            "ping": self.handle_ping,
            "exec": self.handle_exec,
            "bat_run": self.handle_bat_run,
            "bat_create": self.handle_bat_create,
            "file_upload": self.handle_file_upload,
            "file_upload_start": self.handle_file_upload_start,
            "file_upload_chunk": self.handle_file_upload_chunk,
            "file_upload_end": self.handle_file_upload_end,
            "file_download": self.handle_file_download,
            "file_list": self.handle_file_list,
            "file_delete": self.handle_file_delete,
            "file_stat": self.handle_file_stat,
            "sysinfo": self.handle_sysinfo,
            "proclist": self.handle_proclist,
            "services": self.handle_services,
            "agent_info": self.handle_agent_info,
            "agent_shutdown": self.handle_agent_shutdown,
            # debugger actions
            "debug_list": self.handle_debug_list,
            "debug_launch": self.handle_debug_launch,
            "debug_attach": self.handle_debug_attach,
            "debug_cmd": self.handle_debug_cmd,
            "debug_script": self.handle_debug_script,
            "debug_detach": self.handle_debug_detach,
            "debug_log": self.handle_debug_log,
            # install / startup / reboot
            "install_startup": self.handle_install_startup,
            "remove_startup": self.handle_remove_startup,
            "startup_status": self.handle_startup_status,
            "reboot": self.handle_reboot,
            # interactive python shell
            "pyshell_eval": self.handle_pyshell_eval,
            "pyshell_reset": self.handle_pyshell_reset,
        }
        self._shutdown_event = threading.Event()
        self._pyshell_consoles = {}  # session_id -> InteractiveConsole
        self._pyshell_lock = threading.Lock()

    def dispatch(self, action, params):
        handler = self._handlers.get(action)
        if not handler:
            raise ValueError("Unknown action: {0}".format(action))
        return handler(params)

    @property
    def should_shutdown(self):
        return self._shutdown_event.is_set()

    # -- core ---------------------------------------------------------------

    def handle_ping(self, params):
        return {"pong": True, "uptime": time.time() - self._start_time}

    def handle_exec(self, params):
        cmd = params.get("cmd", "")
        timeout = params.get("timeout", 30)
        shell_type = params.get("shell", "cmd")

        if shell_type == "python":
            args = [PYTHON_EXE, "-c", cmd]
        elif shell_type == "python_file":
            args = [PYTHON_EXE, cmd]
        else:
            args = ["cmd.exe", "/c", cmd]

        log.info("exec [%s]: %s", shell_type, cmd[:120])
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
        )
        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            timed_out = True

        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "returncode": proc.returncode,
            "timed_out": timed_out,
        }

    # -- batch files --------------------------------------------------------

    def handle_bat_run(self, params):
        path = params.get("path", "")
        args = params.get("args", [])
        timeout = params.get("timeout", 60)

        if not os.path.isfile(path):
            raise ValueError("Batch file not found: {0}".format(path))

        cmd_args = ["cmd.exe", "/c", path] + list(args)
        log.info("bat_run: %s %s", path, " ".join(args))

        proc = subprocess.Popen(
            cmd_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
        )
        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            timed_out = True

        return {
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "returncode": proc.returncode,
            "timed_out": timed_out,
        }

    def handle_bat_create(self, params):
        path = params.get("path", "")
        content = params.get("content", "")

        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)

        with open(path, "w") as f:
            f.write("@echo off\r\n")
            if isinstance(content, list):
                for line in content:
                    f.write(line + "\r\n")
            else:
                f.write(content + "\r\n")

        return {"path": path, "created": True}

    # -- file transfer ------------------------------------------------------

    def handle_file_upload(self, params):
        path = params.get("path", "")
        data_b64 = params.get("data", "")
        mode = params.get("mode", "write")

        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)

        raw = base64.b64decode(data_b64)
        file_mode = "ab" if mode == "append" else "wb"
        with open(path, file_mode) as f:
            f.write(raw)

        return {"bytes_written": len(raw), "path": path}

    def handle_file_upload_start(self, params):
        path = params.get("path", "")
        total_size = params.get("total_size", 0)
        transfer_id = str(uuid.uuid4())[:8]

        parent = os.path.dirname(path)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)

        fh = open(path, "wb")
        self._transfers[transfer_id] = {
            "fh": fh,
            "path": path,
            "total_size": total_size,
            "received": 0,
        }
        return {"transfer_id": transfer_id}

    def handle_file_upload_chunk(self, params):
        transfer_id = params.get("transfer_id", "")
        data_b64 = params.get("data", "")

        t = self._transfers.get(transfer_id)
        if not t:
            raise KeyError("Unknown transfer: {0}".format(transfer_id))

        raw = base64.b64decode(data_b64)
        t["fh"].write(raw)
        t["received"] += len(raw)
        return {"received": t["received"]}

    def handle_file_upload_end(self, params):
        transfer_id = params.get("transfer_id", "")
        t = self._transfers.pop(transfer_id, None)
        if not t:
            raise KeyError("Unknown transfer: {0}".format(transfer_id))
        t["fh"].close()
        return {"path": t["path"], "total_received": t["received"]}

    def handle_file_download(self, params):
        path = params.get("path", "")
        if not os.path.isfile(path):
            raise ValueError("File not found: {0}".format(path))

        size = os.path.getsize(path)
        with open(path, "rb") as f:
            data = f.read()

        return {
            "data": base64.b64encode(data).decode("ascii"),
            "size": size,
            "path": path,
        }

    def handle_file_list(self, params):
        path = params.get("path", ".")
        recursive = params.get("recursive", False)

        if not os.path.isdir(path):
            raise ValueError("Directory not found: {0}".format(path))

        entries = []
        if recursive:
            for root, dirs, files in os.walk(path):
                for d in dirs:
                    full = os.path.join(root, d)
                    entries.append(self._stat_entry(full))
                for f in files:
                    full = os.path.join(root, f)
                    entries.append(self._stat_entry(full))
        else:
            for name in os.listdir(path):
                full = os.path.join(path, name)
                entries.append(self._stat_entry(full))

        return {"entries": entries}

    def handle_file_delete(self, params):
        path = params.get("path", "")
        recursive = params.get("recursive", False)

        if os.path.isdir(path):
            if recursive:
                shutil.rmtree(path)
            else:
                os.rmdir(path)
        elif os.path.isfile(path):
            os.remove(path)
        else:
            raise ValueError("Path not found: {0}".format(path))

        return {"deleted": True, "path": path}

    def handle_file_stat(self, params):
        path = params.get("path", "")
        if not os.path.exists(path):
            return {"exists": False, "path": path}
        return self._stat_entry(path)

    def _stat_entry(self, path):
        try:
            st = os.stat(path)
            return {
                "name": os.path.basename(path),
                "path": path,
                "exists": True,
                "type": "dir" if os.path.isdir(path) else "file",
                "size": st.st_size,
                "mtime": st.st_mtime,
            }
        except OSError:
            return {"name": os.path.basename(path), "path": path, "exists": False}

    # -- system info --------------------------------------------------------

    def handle_sysinfo(self, params):
        info = {
            "hostname": platform.node(),
            "os": platform.platform(),
            "os_version": platform.version(),
            "architecture": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "agent_version": AGENT_VERSION,
        }

        # Memory via Windows API
        try:
            kernel32 = ctypes.windll.kernel32

            class MEMORYSTATUS(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("dwTotalPhys", ctypes.c_ulong),
                    ("dwAvailPhys", ctypes.c_ulong),
                    ("dwTotalPageFile", ctypes.c_ulong),
                    ("dwAvailPageFile", ctypes.c_ulong),
                    ("dwTotalVirtual", ctypes.c_ulong),
                    ("dwAvailVirtual", ctypes.c_ulong),
                ]

            ms = MEMORYSTATUS()
            ms.dwLength = ctypes.sizeof(ms)
            kernel32.GlobalMemoryStatus(ctypes.byref(ms))
            info["memory_total_mb"] = ms.dwTotalPhys // (1024 * 1024)
            info["memory_avail_mb"] = ms.dwAvailPhys // (1024 * 1024)
            info["memory_load_pct"] = ms.dwMemoryLoad
        except Exception:
            info["memory"] = "unavailable"

        # Disk space
        try:
            if hasattr(shutil, "disk_usage"):
                du = shutil.disk_usage("C:\\")
                info["disk_total_mb"] = du.total // (1024 * 1024)
                info["disk_free_mb"] = du.free // (1024 * 1024)
        except Exception:
            pass

        return info

    def handle_proclist(self, params):
        filter_str = params.get("filter", "")
        proc = subprocess.Popen(
            ["tasklist", "/fo", "csv", "/nh"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, _ = proc.communicate(timeout=15)
        lines = stdout.decode("utf-8", errors="replace").strip().splitlines()

        processes = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # CSV: "name","pid","session","session#","mem"
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 2:
                name = parts[0].strip('"')
                try:
                    pid = int(parts[1])
                except (ValueError, IndexError):
                    continue
                mem = parts[4].strip('"') if len(parts) > 4 else ""
                if filter_str and filter_str.lower() not in name.lower():
                    continue
                processes.append({"name": name, "pid": pid, "memory": mem})

        return {"processes": processes}

    def handle_services(self, params):
        action = params.get("action", "list")
        service_name = params.get("name", "")

        if action == "list":
            proc = subprocess.Popen(
                ["net", "start"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, _ = proc.communicate(timeout=15)
            lines = stdout.decode("utf-8", errors="replace").strip().splitlines()
            services = [
                l.strip()
                for l in lines
                if l.strip() and not l.startswith("The following")
            ]
            return {"services": services}

        elif action in ("start", "stop"):
            if not service_name:
                raise ValueError("Service name required for {0}".format(action))
            proc = subprocess.Popen(
                ["net", action, service_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout, stderr = proc.communicate(timeout=30)
            return {
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
                "returncode": proc.returncode,
            }

        raise ValueError("Unknown service action: {0}".format(action))

    # -- agent lifecycle ----------------------------------------------------

    def handle_agent_info(self, params):
        return {
            "version": AGENT_VERSION,
            "pid": os.getpid(),
            "uptime": time.time() - self._start_time,
            "python": platform.python_version(),
            "debuggers": self.debugger.list_installed(),
        }

    def handle_agent_shutdown(self, params):
        log.info("Shutdown requested")
        self._shutdown_event.set()
        return {"shutting_down": True}

    # -- install / startup / reboot -----------------------------------------

    def handle_install_startup(self, params):
        """Register the agent in Windows startup via registry Run key."""
        import winreg

        port = params.get("port", DEFAULT_PORT)
        agent_path = os.path.join(INSTALL_DIR, "agent.py")

        if not os.path.isfile(agent_path):
            raise ValueError("Agent not found at {0}. Deploy first.".format(agent_path))

        command = '"{python}" "{agent}" --port {port}'.format(
            python=PYTHON_EXE,
            agent=agent_path,
            port=port,
        )

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            STARTUP_REG_KEY,
            0,
            winreg.KEY_SET_VALUE,
        )
        try:
            winreg.SetValueEx(key, STARTUP_REG_NAME, 0, winreg.REG_SZ, command)
        finally:
            winreg.CloseKey(key)

        log.info("Registered startup: %s", command)
        return {
            "installed": True,
            "reg_key": "HKLM\\{0}".format(STARTUP_REG_KEY),
            "value_name": STARTUP_REG_NAME,
            "command": command,
        }

    def handle_remove_startup(self, params):
        """Remove the agent from Windows startup."""
        import winreg

        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                STARTUP_REG_KEY,
                0,
                winreg.KEY_SET_VALUE,
            )
            try:
                winreg.DeleteValue(key, STARTUP_REG_NAME)
            finally:
                winreg.CloseKey(key)
            log.info("Removed startup entry")
            return {"removed": True}
        except OSError:
            return {"removed": False, "message": "Startup entry not found"}

    def handle_startup_status(self, params):
        """Check whether the agent is registered in Windows startup."""
        import winreg

        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                STARTUP_REG_KEY,
                0,
                winreg.KEY_READ,
            )
            try:
                value, _reg_type = winreg.QueryValueEx(key, STARTUP_REG_NAME)
                return {"installed": True, "command": value}
            except OSError:
                return {"installed": False}
            finally:
                winreg.CloseKey(key)
        except OSError:
            return {"installed": False}

    def handle_reboot(self, params):
        """Reboot the Windows machine."""
        delay = params.get("delay", 0)
        force = params.get("force", True)

        if force:
            cmd = "shutdown /r /f /t {0}".format(delay)
        else:
            cmd = "shutdown /r /t {0}".format(delay)

        log.info("Reboot requested: %s", cmd)

        def _do_reboot():
            time.sleep(1)  # let the TCP response go out first
            subprocess.Popen(
                ["cmd.exe", "/c", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        t = threading.Thread(target=_do_reboot)
        t.daemon = True
        t.start()

        return {"rebooting": True, "command": cmd}

    # -- interactive python shell -------------------------------------------

    def _get_pyshell(self, session_id):
        """Get or create a persistent InteractiveConsole for a session."""
        with self._pyshell_lock:
            console = self._pyshell_consoles.get(session_id)
            if console is None:
                ns = {"__name__": "__console__", "__doc__": None}
                console = code.InteractiveConsole(locals=ns)
                self._pyshell_consoles[session_id] = console
            return console

    def handle_pyshell_eval(self, params):
        session_id = params.get("session_id", "default")
        source = params.get("code", "")

        console = self._get_pyshell(session_id)

        # Capture stdout/stderr during execution
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = _out = _StringIO()
        sys.stderr = _err = _StringIO()
        try:
            more = console.push(source)
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        return {
            "stdout": _out.getvalue(),
            "stderr": _err.getvalue(),
            "more": more,
        }

    def handle_pyshell_reset(self, params):
        session_id = params.get("session_id", "default")
        with self._pyshell_lock:
            self._pyshell_consoles.pop(session_id, None)
        return {"reset": True, "session_id": session_id}

    # -- debugger actions ---------------------------------------------------

    def handle_debug_list(self, params):
        return {"debuggers": self.debugger.list_installed()}

    def handle_debug_launch(self, params):
        debugger = params.get("debugger", "")
        exe = params.get("exe", "")
        extra_args = params.get("args", [])
        if not debugger or not exe:
            raise ValueError("debugger and exe are required")
        session_id = self.debugger.launch(debugger, exe, extra_args or None)
        return {"session_id": session_id, "debugger": debugger, "target": exe}

    def handle_debug_attach(self, params):
        debugger = params.get("debugger", "")
        pid = params.get("pid", 0)
        if not debugger or not pid:
            raise ValueError("debugger and pid are required")
        session_id = self.debugger.attach(debugger, int(pid))
        return {"session_id": session_id, "debugger": debugger, "pid": pid}

    def handle_debug_cmd(self, params):
        session_id = params.get("session_id", "")
        command = params.get("command", "")
        if not session_id or not command:
            raise ValueError("session_id and command are required")
        output = self.debugger.send_command(session_id, command)
        return {"output": output, "session_id": session_id}

    def handle_debug_script(self, params):
        debugger = params.get("debugger", "")
        session_id = params.get("session_id", "")
        script_path = params.get("script_path", "")
        if not script_path:
            raise ValueError("script_path is required")
        result = self.debugger.run_script(debugger, session_id or None, script_path)
        return {"result": result}

    def handle_debug_detach(self, params):
        session_id = params.get("session_id", "")
        if not session_id:
            raise ValueError("session_id is required")
        self.debugger.close(session_id)
        return {"closed": True, "session_id": session_id}

    def handle_debug_log(self, params):
        session_id = params.get("session_id", "")
        if not session_id:
            raise ValueError("session_id is required")
        output = self.debugger.read_output(session_id)
        return {"output": output, "session_id": session_id}


# ---------------------------------------------------------------------------
# Connection handler (one thread per client)
# ---------------------------------------------------------------------------


class ClientHandler(threading.Thread):
    def __init__(self, sock, addr, handler):
        threading.Thread.__init__(self)
        self.daemon = True
        self.sock = sock
        self.addr = addr
        self.handler = handler

    def run(self):
        log.info("Client connected: %s:%s", self.addr[0], self.addr[1])
        try:
            while not self.handler.should_shutdown:
                msg = recv_message(self.sock)
                if msg is None:
                    break

                req_id = msg.get("id", "")
                action = msg.get("action", "")
                params = msg.get("params", {})

                log.debug("Request %s action=%s", req_id, action)
                try:
                    data = self.handler.dispatch(action, params)
                    resp = make_response(req_id, data=data)
                except Exception as exc:
                    log.exception("Handler error for action=%s", action)
                    resp = make_response(req_id, error=str(exc))

                send_message(self.sock, resp)
        except Exception:
            log.exception("Client handler error (%s)", self.addr)
        finally:
            try:
                self.sock.close()
            except Exception:
                pass
            log.info("Client disconnected: %s:%s", self.addr[0], self.addr[1])


# ---------------------------------------------------------------------------
# TCP server
# ---------------------------------------------------------------------------


class XPSSHAgent(object):
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT):
        self.host = host
        self.port = port
        self.handler = ActionHandler()
        self._server_sock = None

    def start(self):
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.settimeout(1.0)  # allow periodic shutdown checks
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(5)
        log.info(
            "xpctl agent v%s listening on %s:%s  (pid %s)",
            AGENT_VERSION,
            self.host,
            self.port,
            os.getpid(),
        )

        try:
            while not self.handler.should_shutdown:
                try:
                    client_sock, addr = self._server_sock.accept()
                except socket.timeout:
                    continue
                t = ClientHandler(client_sock, addr, self.handler)
                t.start()
        except KeyboardInterrupt:
            log.info("Interrupted")
        finally:
            self.stop()

    def stop(self):
        log.info("Shutting down")
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="xpctl agent v{0}".format(AGENT_VERSION)
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="TCP port (default {0})".format(DEFAULT_PORT),
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="Bind address (default {0})".format(DEFAULT_HOST),
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    agent = XPSSHAgent(host=args.host, port=args.port)
    agent.start()


if __name__ == "__main__":
    main()
