import os
import shutil

payload = globals()["payload"]

path = payload.get("path", "")
recursive = bool(payload.get("recursive", False))

if os.path.isdir(path):
    if recursive:
        shutil.rmtree(path)
    else:
        os.rmdir(path)
elif os.path.isfile(path):
    os.remove(path)
else:
    raise ValueError(f"Path not found: {path}")

result = {"deleted": True, "path": path}
