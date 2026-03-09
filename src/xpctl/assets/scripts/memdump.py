import ctypes
import os

payload = globals()["payload"]

pid = int(payload["pid"])
dump_path = payload["dump_path"]

MiniDumpWithFullMemory = 0x00000002
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010

if not os.path.isdir(os.path.dirname(dump_path)):
    os.makedirs(os.path.dirname(dump_path))

kernel32 = ctypes.windll.kernel32
dbghelp = ctypes.windll.dbghelp

h_process = kernel32.OpenProcess(
    PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
)
if not h_process:
    raise RuntimeError("OpenProcess failed")

CreateFileA = kernel32.CreateFileA
CreateFileA.argtypes = [
    ctypes.c_char_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_void_p,
    ctypes.c_ulong,
    ctypes.c_ulong,
    ctypes.c_void_p,
]
CreateFileA.restype = ctypes.c_void_p

GENERIC_WRITE = 0x40000000
CREATE_ALWAYS = 2
FILE_ATTRIBUTE_NORMAL = 0x80

h_file = CreateFileA(
    dump_path.encode("ascii"),
    GENERIC_WRITE,
    0,
    None,
    CREATE_ALWAYS,
    FILE_ATTRIBUTE_NORMAL,
    None,
)
if h_file == ctypes.c_void_p(-1).value:
    kernel32.CloseHandle(h_process)
    raise RuntimeError("CreateFile failed")

ok = dbghelp.MiniDumpWriteDump(
    h_process,
    pid,
    h_file,
    MiniDumpWithFullMemory,
    None,
    None,
    None,
)
kernel32.CloseHandle(h_file)
kernel32.CloseHandle(h_process)
if not ok:
    raise RuntimeError("MiniDumpWriteDump failed")

result = {"path": dump_path, "size": os.path.getsize(dump_path)}
