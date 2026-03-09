import ctypes

payload = globals()["payload"]

PROCESS_CREATE_THREAD = 0x0002
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04
INFINITE = 0xFFFFFFFF

pid = int(payload["pid"])
dll_path = payload["dll_path"]
dll_bytes = dll_path.encode("ascii") + b"\x00"

kernel32 = ctypes.windll.kernel32
h_process = kernel32.OpenProcess(
    PROCESS_CREATE_THREAD
    | PROCESS_QUERY_INFORMATION
    | PROCESS_VM_OPERATION
    | PROCESS_VM_WRITE
    | PROCESS_VM_READ,
    False,
    pid,
)
if not h_process:
    raise RuntimeError("OpenProcess failed")

addr = kernel32.VirtualAllocEx(
    h_process, 0, len(dll_bytes), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
)
if not addr:
    kernel32.CloseHandle(h_process)
    raise RuntimeError("VirtualAllocEx failed")

written = ctypes.c_size_t(0)
ok = kernel32.WriteProcessMemory(
    h_process,
    addr,
    ctypes.c_char_p(dll_bytes),
    len(dll_bytes),
    ctypes.byref(written),
)
if not ok:
    kernel32.CloseHandle(h_process)
    raise RuntimeError("WriteProcessMemory failed")

h_kernel = kernel32.GetModuleHandleA(b"kernel32.dll")
load_library = kernel32.GetProcAddress(h_kernel, b"LoadLibraryA")
if not load_library:
    kernel32.CloseHandle(h_process)
    raise RuntimeError("GetProcAddress(LoadLibraryA) failed")

thread_id = ctypes.c_ulong(0)
h_thread = kernel32.CreateRemoteThread(
    h_process, 0, 0, load_library, addr, 0, ctypes.byref(thread_id)
)
if not h_thread:
    kernel32.CloseHandle(h_process)
    raise RuntimeError("CreateRemoteThread failed")

kernel32.WaitForSingleObject(h_thread, INFINITE)
exit_code = ctypes.c_ulong(0)
kernel32.GetExitCodeThread(h_thread, ctypes.byref(exit_code))
kernel32.CloseHandle(h_thread)
kernel32.CloseHandle(h_process)

result = {
    "pid": pid,
    "dll_path": dll_path,
    "thread_id": int(thread_id.value),
    "loadlibrary_result": int(exit_code.value),
}
