#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec "${LM_PYTHON:-python3}" "$root/scripts/export_public.py" "$@"
