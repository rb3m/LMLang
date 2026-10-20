"""Named handler wrapper embedded only in standalone Python HTTP programs."""


def run_serve(entry, site):
    seed_from_env()
    try:
        listener, options, _, _ = parse_serve_args(sys.argv[1:], built=True)
    except ValueError as ex:
        sys.stderr.write(f"HTTP server: {ex}\n")
        sys.exit(2)

    def diagnostic(ex):
        if isinstance(ex, Fault):
            return diag_json(ex.diag)
        code = "E-RECURSION-LIMIT" if isinstance(ex, RecursionError) else "E-SERVE"
        return diag_json({"code": code, "severity": "error", "file": "",
                          "line": 1, "col": 1, "path": "",
                          "msg": "HTTP handler fault", "fix": []})

    def call(request):
        global depth
        depth = 0
        fields = dict(request)
        fields["headers"] = tuple(Pair(a, b) for a, b in request["headers"])
        record = Rec("http.Request", tuple(fields.items()))
        box = {}

        def target():
            try:
                box["result"] = entry(record)
            except BaseException as ex:
                box["error"] = ex

        try:
            threading.stack_size(THREAD_STACK)
            sys.setrecursionlimit(550000)
        except (ValueError, RuntimeError):
            pass
        thread = threading.Thread(target=target)
        thread.start()
        thread.join()
        if "error" in box:
            raise box["error"]
        result = dict(box["result"].items)
        result["headers"] = tuple((p.a, p.b) for p in result["headers"])
        return result

    try:
        if listener:
            server_mod.serve_listener(call, diagnostic=diagnostic, **options)
        else:
            server_mod.serve_cgi(call, diagnostic=diagnostic)
    except (ValueError, OSError) as ex:
        sys.stderr.write(f"HTTP server: {ex}\n")
        sys.exit(2)
    except KeyboardInterrupt:
        pass
