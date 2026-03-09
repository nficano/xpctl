import ctypes
import os
import struct

payload = globals()["payload"]

path = payload["path"]
parent = os.path.dirname(path)
if parent and not os.path.isdir(parent):
    os.makedirs(parent)

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

SM_CXSCREEN = 0
SM_CYSCREEN = 1
SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0

width = user32.GetSystemMetrics(SM_CXSCREEN)
height = user32.GetSystemMetrics(SM_CYSCREEN)

hdc_screen = user32.GetDC(0)
hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
hbitmap = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
gdi32.SelectObject(hdc_mem, hbitmap)
gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, 0, 0, SRCCOPY)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


row_stride = ((width * 24 + 31) // 32) * 4
img_size = row_stride * height
buf = ctypes.create_string_buffer(img_size)
bi = BITMAPINFO()
bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
bi.bmiHeader.biWidth = width
bi.bmiHeader.biHeight = height
bi.bmiHeader.biPlanes = 1
bi.bmiHeader.biBitCount = 24
bi.bmiHeader.biCompression = BI_RGB
bi.bmiHeader.biSizeImage = img_size

ok = gdi32.GetDIBits(hdc_mem, hbitmap, 0, height, buf, ctypes.byref(bi), DIB_RGB_COLORS)
if not ok:
    raise RuntimeError("GetDIBits failed")

bfType = b"BM"
bfOffBits = 14 + 40
bfSize = bfOffBits + img_size
file_header = struct.pack("<2sIHHI", bfType, bfSize, 0, 0, bfOffBits)
info_header = struct.pack(
    "<IIIHHIIIIII",
    40,
    width,
    height,
    1,
    24,
    0,
    img_size,
    0,
    0,
    0,
    0,
)
with open(path, "wb") as fh:
    fh.write(file_header)
    fh.write(info_header)
    fh.write(buf.raw)

gdi32.DeleteObject(hbitmap)
gdi32.DeleteDC(hdc_mem)
user32.ReleaseDC(0, hdc_screen)

result = {"path": path, "width": width, "height": height, "size": os.path.getsize(path)}
