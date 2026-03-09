"""Debugger integration types and helpers.

The actual debugger communication goes through the agent via the wire protocol.
This module provides the typed interface classes used by ``XPClient.debug.*``
and CLI-level helpers for formatting debugger output.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DebugSession:
    session_id: str
    debugger: str
    target: str

    def __str__(self) -> str:
        return f"[{self.debugger}] session={self.session_id} target={self.target}"


DEBUGGER_DESCRIPTIONS: dict[str, str] = {
    "olly": "OllyDbg — 32-bit user-mode debugger (GUI, OllyScript support)",
    "cdb": "CDB/WinDbg — Microsoft console debugger (piped I/O, script via $$>< )",
    "windbg": "WinDbg — Microsoft Windows Debugger (GUI + remote server)",
    "x64dbg": "x32dbg — open-source x86 debugger (command line + script)",
}
