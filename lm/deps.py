"""Project dependency declarations, byte-pinned cache and explicit fetching."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit

from .diag import make
from .sexpr import Atom, SList, read
from .prelude import EFFECTS

MANIFEST = 'lm.deps'
STEM = re.compile(r'[a-z][a-z0-9-]*\Z')
HASH = re.compile(r'[0-9a-f]{64}\Z')


@dataclass(frozen=True)
class Pin:
    stem: str
    url: str
    digest: str
    line: int = 1
    col: int = 1
    allow: tuple | None = None


def valid_url(url):
    from . import http_prims as http
    try:
        if urlsplit(url).scheme != 'https':
            return False
        http._validate('GET', url, (), '')
        return True
    except (ValueError, http._HttpProblem):
        return False


def read_pins():
    path = Path(MANIFEST)
    if not path.exists():
        return [], []
    try:
        root, diags = read(path.read_text(encoding='utf-8'), MANIFEST)
    except (OSError, UnicodeError) as ex:
        return [], [make('E-DEPS', MANIFEST, 1, 1, str(ex))]
    if diags:
        return [], [make('E-DEPS', MANIFEST, d.line, d.col, d.msg) for d in diags]

    def bad(node, msg):
        return [], [make('E-DEPS', MANIFEST, node.line, node.col, msg)]

    def atom(node, kind, value=None):
        return (isinstance(node, Atom) and node.kind == kind
                and (value is None or node.value == value))

    if not (isinstance(root, SList) and root.items
            and atom(root.items[0], 'sym', 'deps')):
        return bad(root, 'expected (deps (pin STEM "HTTPS-URL" "SHA256") ...)')
    pins, seen = [], set()
    for node in root.items[1:]:
        if not (isinstance(node, SList) and len(node.items) in (4, 5)
                and atom(node.items[0], 'sym', 'pin')
                and atom(node.items[1], 'sym')
                and STEM.fullmatch(node.items[1].value)
                and atom(node.items[2], 'str')
                and atom(node.items[3], 'str')):
            return bad(node, 'expected (pin STEM "HTTPS-URL" "SHA256" [(allow EFFECT..)])')
        _, stem, url, digest = node.items[:4]
        allow = None
        if len(node.items) == 5:
            clause = node.items[4]
            if not (isinstance(clause, SList) and clause.items
                    and atom(clause.items[0], 'sym', 'allow')
                    and all(atom(a, 'sym') and a.value in EFFECTS for a in clause.items[1:])):
                return bad(clause, 'expected (allow EFFECT..), using known effect names')
            allow = tuple(a.value for a in clause.items[1:])
            if allow != tuple(sorted(set(allow))):
                return bad(clause, 'allow effects must be unique and sorted')
        if not valid_url(url.value):
            return bad(url, 'dependency URL must be a direct HTTPS URL')
        if not HASH.fullmatch(digest.value):
            return bad(digest, 'dependency hash must be 64 lowercase hexadecimal characters')
        if stem.value in seen:
            return bad(stem, f'duplicate dependency stem `{stem.value}`')
        seen.add(stem.value)
        pins.append(Pin(stem.value, url.value, digest.value, node.line, node.col, allow))
    return pins, []


def cache_path(pin):
    base = Path(os.environ['LM_CACHE']) if 'LM_CACHE' in os.environ else Path.home() / '.cache/lm'
    return base / pin.digest / (pin.stem + '.lm')


def read_cached(pin):
    """Return the verified bytes themselves, so loading never reopens the file."""
    path = cache_path(pin)
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None, 'E-DEP-UNFETCHED'
    except OSError:
        return None, 'E-DEP-HASH'
    if hashlib.sha256(data).hexdigest() != pin.digest:
        return None, 'E-DEP-HASH'
    return data, None


def cache_problem(pin):
    return read_cached(pin)[1]


def pin_line(pin):
    allow = ""
    if pin.allow is not None:
        effects = " " + " ".join(pin.allow) if pin.allow else ""
        allow = f" (allow{effects})"
    return f'(pin {pin.stem} {json.dumps(pin.url)} "{pin.digest}"{allow})'


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temp = Path(stream.name)
            stream.write(data)
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def download(url):
    """Injectable raw-byte download, sharing the runtime's bounded HTTP policy."""
    from .deps_http import download_bytes
    return download_bytes(url)


def _download(url):
    from .http_prims import HTTP_BODY_LIMIT
    if not valid_url(url):
        raise ValueError('dependency URL must be a direct HTTPS URL')
    data = download(url)
    if len(data) > HTTP_BODY_LIMIT:
        raise ValueError('download exceeds 8 MiB')
    return data


def cmd_fetch(args):
    if args and (len(args) < 3 or args[0] != '--pin'
                 or len(args[3:]) % 2 or any(a != '--allow' for a in args[3::2])):
        sys.stderr.write('usage: lm fetch [--pin STEM URL [--allow EFF]..]\n')
        return 3
    pins, diags = read_pins()
    if diags:
        for d in diags:
            print(d.to_json())
        return 1
    if args:
        _, stem, url = args[:3]
        try:
            if not STEM.fullmatch(stem):
                raise ValueError('invalid dependency stem')
            allow = args[4::2]
            if any(e not in EFFECTS for e in allow) or len(allow) != len(set(allow)):
                print(make('E-DEPS', MANIFEST, 1, 1, 'allow effects must be known and unique').to_json())
                return 1
            data = _download(url)
            pin = Pin(stem, url, hashlib.sha256(data).hexdigest(), allow=tuple(sorted(allow)) if allow else None)
            atomic_write(cache_path(pin), data)
            pins = sorted([p for p in pins if p.stem != stem] + [pin], key=lambda p: p.stem)
            text = '(deps\n' + '\n'.join('  ' + pin_line(p) for p in pins) + ')\n'
            atomic_write(Path(MANIFEST), text.encode('utf-8'))
            print(pin_line(pin))
            return 0
        except (OSError, ValueError) as ex:
            print(json.dumps({'stem': stem, 'status': 'error', 'msg': str(ex)}))
            return 1
    failed = False
    for pin in sorted(pins, key=lambda p: p.stem):
        status, msg = 'cached', 'verified cached bytes'
        try:
            if cache_problem(pin):
                data = _download(pin.url)
                if hashlib.sha256(data).hexdigest() != pin.digest:
                    raise ValueError('SHA-256 mismatch; cache unchanged')
                atomic_write(cache_path(pin), data)
                status, msg = 'fetched', 'downloaded and verified bytes'
        except (OSError, ValueError) as ex:
            failed, status, msg = True, 'error', str(ex)
        print(json.dumps({'stem': pin.stem, 'status': status, 'msg': msg}))
    return int(failed)


def check_effects(prog):
    """Admit declared external effects; ordinary checking verifies their bodies."""
    for pin in prog.pins.values():
        def reject(msg):
            prog.diags.append(make('E-DEP-EFFECT', MANIFEST, pin.line, pin.col, msg))
        allowance = set(pin.allow or ())
        if 'proc.run' in allowance:
            reject(f'pin `{pin.stem}` may never allow effect `proc.run`')
        if 'net.http' in allowance:
            for effect in ('fs.read', 'env.read'):
                if effect in allowance:
                    reject(f'pin `{pin.stem}` may not combine `{effect}` with `net.http`')
        m = prog.modules.get(pin.stem)
        if m is None or not m.is_external:
            continue
        for f in m.fns.values():
            for effect in sorted(f.eff - allowance):
                reject(f'function `{f.qual}` declares effect `{effect}` outside its pin allowance')
