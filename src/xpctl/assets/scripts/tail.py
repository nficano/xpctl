payload = globals()["payload"]

path = payload["path"]
n = int(payload["lines"])
with open(path, "r", errors="replace") as fh:
    rows = fh.read().splitlines()
result = {"text": "\n".join(rows[-n:])}
