import base64

exec(
    compile(
        base64.b64decode("__CODE_B64__").decode("utf-8"),
        "xpctl_inline",
        "exec",
    )
)
