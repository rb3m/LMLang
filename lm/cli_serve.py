"""Named HTTP handler interpreter entry, sharing adapters with Python builds."""
from __future__ import annotations

import sys

from .cli_common import _report, _static
from .diag import make
from .serve_entry import check_serve
from .serve_options import parse_serve_args


def cmd_serve(args):
    from .http_server import serve_cgi, serve_listener
    from .interp import Interp
    from .runner import in_big_stack, runtime_diag
    from .values import Denied, Named, Pair, Rec

    try:
        listener, options, pos, allowed = parse_serve_args(args)
    except ValueError as ex:
        sys.stderr.write(f"lm serve: {ex}\n")
        return 2
    name = pos[0]
    prog, _ = _static(pos[1:], extra=[name.split(".", 1)[0]])
    handler = check_serve(prog, name)
    if _report(prog.diags, lambda e, w: "", stream=sys.stderr):
        return 1
    for effect in sorted(handler.eff - set(allowed)):
        print(runtime_diag(Denied(effect, handler)).to_json(), file=sys.stderr)
        return 1
    interp = Interp(prog, allowed=allowed, out=sys.stderr)

    def diagnostic(ex):
        diag = runtime_diag(ex, it=interp)
        if diag is None:
            diag = make("E-SERVE", "", 1, 1, "HTTP handler fault")
        return diag.to_json()

    def call(request):
        interp.reset()
        fields = dict(request)
        fields["headers"] = tuple(Pair(a, b) for a, b in request["headers"])
        record = Rec("http.Request", tuple(fields.items()))
        response = in_big_stack(lambda: interp.apply(Named(handler), [record]))
        result = dict(response.items)
        result["headers"] = tuple((p.a, p.b) for p in result["headers"])
        return result

    try:
        if listener:
            return serve_listener(call, diagnostic=diagnostic, **options)
        return serve_cgi(call, diagnostic=diagnostic)
    except (ValueError, OSError) as ex:
        sys.stderr.write(f"lm serve: {ex}\n")
        return 2
    except KeyboardInterrupt:
        return 0
