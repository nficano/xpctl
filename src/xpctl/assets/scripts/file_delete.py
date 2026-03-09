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
    raise ValueError("Path not found: {0}".format(path))

result = {"deleted": True, "path": path}
