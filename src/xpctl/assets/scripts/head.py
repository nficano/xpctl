payload = globals()["payload"]

path = payload["path"]
n = int(payload["lines"])
with open(path, errors="replace") as fh:
    content = []
    for idx, line in enumerate(fh):
        if idx >= n:
            break
        content.append(line.rstrip("\r\n"))
result = {"text": "\n".join(content)}
