import sys

if sys.version_info < (3, 10):
    sys.stderr.write(f"lm: needs Python >= 3.10, found {sys.version.split()[0]} ({sys.executable}); set LM_PYTHON to a newer python3\n")
    sys.exit(3)

from .cli import main

sys.exit(main())
