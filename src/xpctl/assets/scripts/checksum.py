import hashlib

payload = globals()["payload"]

path = payload["path"]
algo = payload["algo"]
h = hashlib.new(algo)
with open(path, "rb") as fh:
    while True:
        chunk = fh.read(1024 * 1024)
        if not chunk:
            break
        h.update(chunk)
result = {"algo": algo, "hexdigest": h.hexdigest()}
