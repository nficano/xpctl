import fnmatch
import os
import re

payload = globals()["payload"]

root = payload["root"]
glob_pattern = payload.get("glob", "*")
regex_pattern = payload.get("regex", "")
rx = re.compile(regex_pattern) if regex_pattern else None

matches = []
for r, _, files in os.walk(root):
    for name in files:
        if not fnmatch.fnmatch(name, glob_pattern):
            continue
        full = os.path.join(r, name)
        if rx and not rx.search(full):
            continue
        matches.append(full)

result = {"matches": matches}
