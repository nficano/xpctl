import base64
import json

payload = json.loads(base64.b64decode("__PAYLOAD_B64__").decode("utf-8"))
code = base64.b64decode("__SCRIPT_B64__").decode("utf-8")
ns = {"payload": payload}
exec(compile(code, "xpctl_payload", "exec"), ns)
print("__JSON_MARKER__" + json.dumps(ns.get("result", {})))
