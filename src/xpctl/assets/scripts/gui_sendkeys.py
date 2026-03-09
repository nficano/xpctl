import ctypes
import time

payload = globals()["payload"]

keys = payload["keys"]
title = payload.get("title", "")
user32 = ctypes.windll.user32

if title:
    hwnd = user32.FindWindowW(None, title)
    if hwnd:
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)

for ch in keys:
    vk_combo = user32.VkKeyScanA(ord(ch))
    vk = vk_combo & 0xFF
    shift = (vk_combo >> 8) & 0xFF
    if shift & 1:
        user32.keybd_event(0x10, 0, 0, 0)
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)
    if shift & 1:
        user32.keybd_event(0x10, 0, 2, 0)
    time.sleep(0.02)

result = {"sent": len(keys), "title": title}
