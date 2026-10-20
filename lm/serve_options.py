"""Argument parsing shared by interpreted and standalone Python HTTP entries."""


def parse_serve_args(args, built=False):
    options = {"host": "127.0.0.1", "port": 8080, "public": False}
    positionals, allowed = [], []
    listener = not built
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--port", "--host", "--allow"):
            if i + 1 >= len(args):
                raise ValueError(f"{arg} needs a value")
            value = args[i + 1]
            if arg == "--allow":
                if built:
                    raise ValueError("unknown flag --allow")
                allowed.append(value)
            elif arg == "--host":
                options["host"] = value
            else:
                if not value or value.strip("0123456789"):
                    raise ValueError("--port must be an integer from 0 to 65535")
                options["port"] = int(value)
                if not 0 <= options["port"] <= 65535:
                    raise ValueError("--port must be an integer from 0 to 65535")
            i += 2
            continue
        if arg == "--public":
            options["public"] = True
        elif arg == "--listen" and built:
            listener = True
        elif arg == "--cgi" and not built:
            listener = False
        elif arg.startswith("-"):
            raise ValueError(f"unknown flag {arg}")
        else:
            positionals.append(arg)
        i += 1
    if built and positionals:
        raise ValueError("unexpected positional argument")
    if not built and (not positionals or "." not in positionals[0]):
        raise ValueError("expected MOD.FN")
    if not listener and any(a in args for a in ("--host", "--port", "--public")):
        raise ValueError("--host/--port/--public require listener mode")
    return listener, options, positionals, allowed
