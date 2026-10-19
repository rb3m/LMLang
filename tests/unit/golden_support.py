"""Run golden commands with only the fixed examples and stdlib project paths."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def golden_command(args, root=ROOT):
    # Some query commands resolve SYM without accepting paths. An isolated cwd
    # scopes those commands too, without changing normal CLI discovery behavior.
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory)
        for name in ("examples", "stdlib"):
            (project / name).symlink_to(root / name, target_is_directory=True)
        env = {**os.environ, "PYTHONPATH": str(ROOT)}
        return subprocess.run([sys.executable, "-m", "lm", *args], cwd=project,
                              env=env, capture_output=True, text=True)
