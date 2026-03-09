import os

payload = globals()["payload"]

path = payload.get("path", "")
if not os.path.exists(path):
    result = {"exists": False, "path": path}
else:
    st = os.stat(path)
    result = {
        "name": os.path.basename(path),
        "path": path,
        "exists": True,
        "type": "dir" if os.path.isdir(path) else "file",
        "size": st.st_size,
        "mtime": st.st_mtime,
    }
