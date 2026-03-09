import os

payload = globals()["payload"]

path = payload.get("path", ".")
recursive = bool(payload.get("recursive", False))

if not os.path.isdir(path):
    raise ValueError("Directory not found: {0}".format(path))


def stat_entry(p):
    try:
        st = os.stat(p)
        return {
            "name": os.path.basename(p),
            "path": p,
            "exists": True,
            "type": "dir" if os.path.isdir(p) else "file",
            "size": st.st_size,
            "mtime": st.st_mtime,
        }
    except OSError:
        return {"name": os.path.basename(p), "path": p, "exists": False}


entries = []
if recursive:
    for root, dirs, files in os.walk(path):
        for d in dirs:
            entries.append(stat_entry(os.path.join(root, d)))
        for f in files:
            entries.append(stat_entry(os.path.join(root, f)))
else:
    for name in os.listdir(path):
        entries.append(stat_entry(os.path.join(path, name)))

result = {"entries": entries}
