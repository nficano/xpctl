import ctypes

user32 = ctypes.windll.user32
windows = []

EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)


def _cb(hwnd, lparam):
    if not user32.IsWindowVisible(hwnd):
        return True
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return True
    title_buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title_buf, length + 1)
    class_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_buf, 256)
    windows.append(
        {
            "hwnd": int(hwnd),
            "title": title_buf.value,
            "class": class_buf.value,
        }
    )
    return True


user32.EnumWindows(EnumWindowsProc(_cb), 0)
result = {"windows": windows}
