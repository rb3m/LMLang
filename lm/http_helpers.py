"""Strict URL decoding shared by the interpreter and embedded Python target."""
import re
from urllib.parse import unquote_to_bytes

from .values import LmFail


def url_decode(it, s):
    if re.search(r'%(?![0-9A-Fa-f]{2})', s):
        raise LmFail('http.BadEncoding', (s,))
    try:
        return unquote_to_bytes(s).decode('utf-8')
    except UnicodeError:
        raise LmFail('http.BadEncoding', (s,)) from None


HTTP_HELPERS = {'http.url-decode': url_decode}
