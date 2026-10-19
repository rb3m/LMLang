"""ADR-051 clocks, seed validation, and SplitMix64 reference/parity checks."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from lm.build import build, find_go
from lm.check import Checker
from lm.interp import Interp
from lm.loader import load
from lm.prelude import EFFECTS
from lm.rand_prims import SplitMix64, parse_seed

ROOT = Path(__file__).resolve().parents[2]
BAD_SEEDS = ('', '1.0', '0x10', '1_000', ' 1', '1 ', '١', '--1',
             '9223372036854775808', '-9223372036854775809')


class Random(unittest.TestCase):
    def test_reference_words(self):
        rng = SplitMix64(0)
        self.assertEqual([rng.next() for _ in range(5)], [
            0xE220A8397B1DCDAF, 0x6E789E6AA1B965F4, 0x06C45D188009454F,
            0xF88BB8A8724C81EC, 0x1B39896A51A8749B])

    def test_seed_grammar(self):
        for text in BAD_SEEDS:
            with self.subTest(seed=text), self.assertRaises(ValueError):
                parse_seed(text)
        for n in (0, -1, -(1 << 63), (1 << 63)-1):
            self.assertEqual(parse_seed(str(n)), n)
        self.assertEqual(parse_seed('+01'), 1)

    def test_cli_seed(self):
        for seed in BAD_SEEDS:
            p = subprocess.run([sys.executable, '-m', 'lm', 'run', 'rand.float',
                                '--allow', 'rand', '--seed', seed], cwd=ROOT, capture_output=True)
            self.assertEqual(p.returncode, 3, (seed, p.stderr))
        p = subprocess.run([sys.executable, '-m', 'lm', 'run', 'rand.float',
                            '--allow', 'rand', '--seed', '0'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual((p.returncode, p.stdout), (0, '0.8833108082136426\n'), p.stderr)

    def test_rng_is_per_execution(self):
        a, b = Interp(None, seed=0), Interp(None, seed=0)
        self.assertEqual(a.rng.next(), b.rng.next())
        a.rng.next()
        self.assertEqual(b.rng.next(), 0x6E789E6AA1B965F4)

    def test_binary_seed_and_parity(self):
        if find_go() is None:
            self.skipTest('go not found: seeded binary tests not run')
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'seeded.lm'
            src.write_text('''(module seeded
  (purpose "Print a mixed random stream.")
  (use io rand str)
  (fn main
    (purpose "Print draws from one shared stream.")
    (sig -> Unit)
    (eff io.out rand)
    (body (do
      (io.print (str.from-int (rand.int -9223372036854775808 9223372036854775807)))
      (io.print (str.from-float (rand.float)))
      (io.print (str.from-int (rand.int -9223372036854775808 0)))
      (io.print (str.from-int (rand.int 42 42)))
      (io.print (str.from-float (rand.float)))))))''')
            prog = load([str(src)])
            Checker(prog).run()
            self.assertEqual([d.to_json() for d in prog.diags if d.severity == 'error'], [])
            exe = Path(tmp) / 'seeded'
            build(prog, prog.modules['seeded'].fns['main'], exe)
            import io
            for seed in (0, 1, -1, -(1 << 63), (1 << 63)-1):
                out = io.StringIO()
                it = Interp(prog, allowed=EFFECTS, out=out, seed=seed)
                it.call_fn(prog.modules['seeded'].fns['main'], [])
                p = subprocess.run([str(exe)], env={**os.environ, 'LM_SEED': str(seed)},
                                   capture_output=True, text=True)
                self.assertEqual((p.returncode, p.stdout, p.stderr), (0, out.getvalue(), ''))
            for seed in BAD_SEEDS:
                p = subprocess.run([str(exe)], env={**os.environ, 'LM_SEED': seed}, capture_output=True)
                self.assertEqual((p.returncode, p.stdout), (3, b''), (seed, p.stderr))
            env = dict(os.environ)
            env.pop('LM_SEED', None)
            self.assertEqual(subprocess.run([str(exe)], env=env, capture_output=True).returncode, 0)
