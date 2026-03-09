import ctypes

payload = globals()["payload"]

pid = int(payload["pid"])
address = int(payload["address"], 0)
size = int(payload["size"])

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400

kernel32 = ctypes.windll.kernel32
h_process = kernel32.OpenProcess(
    PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid
)
if not h_process:
    raise RuntimeError("OpenProcess failed")

buf = ctypes.create_string_buffer(size)
read = ctypes.c_size_t(0)
ok = kernel32.ReadProcessMemory(
    h_process, ctypes.c_void_p(address), buf, size, ctypes.byref(read)
)
kernel32.CloseHandle(h_process)
if not ok:
    raise RuntimeError("ReadProcessMemory failed")

raw = buf.raw[: int(read.value)]
result = {
    "pid": pid,
    "address": hex(address),
    "size": int(read.value),
    "hex": raw.hex(),
}
