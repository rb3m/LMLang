"""The fake-world boundary never falls through to host effect primitives."""
import os
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from lm.check import Checker
from lm.fake_world import FakeWorld
from lm.interp import Interp
from lm.loader import load
from lm.values import LmFail, UNIT, Var


class FakeWorldBoundary(unittest.TestCase):
    def test_every_effect_uses_only_the_private_world(self):
        prog = load(['stdlib'])
        Checker(prog).run()
        given = [('args', ('a', 'b')), ('stdin', ('line\r\nrest',)),
                 ('env', ('KEY', 'fake')), ('now-ms', (42,)), ('seed', (0,))]
        host_env = dict(os.environ)
        names = ['builtins.open', 'os.stat', 'os.listdir', 'os.mkdir',
                 'os.unlink', 'os.rmdir', 'os.rename', 'os.link', 'os.urandom',
                 'time.time_ns', 'time.monotonic_ns', 'sys.stdout',
                 'sys.stderr', 'sys.stdin', 'os.environ']
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch(name)) for name in names]
            world = FakeWorld(given)
            it = Interp(prog, allowed={'io.in', 'io.out', 'env.read',
                                      'fs.read', 'fs.write', 'fs.delete',
                                      'time.now', 'rand'}, world=world)

            def call(name, *args):
                module, function = name.split('.', 1)
                return it.call_fn(prog.modules[module].fns[function], args)

            self.assertEqual(call('io.args'), ('a', 'b'))
            self.assertEqual(call('io.read-line'), Var('', 'Some', ('line',)))
            self.assertEqual(call('io.read-all'), 'rest')
            self.assertEqual(call('io.read-line'), Var('', 'None'))
            self.assertEqual(call('env.lookup', 'KEY'),
                             Var('', 'Some', ('fake',)))
            self.assertEqual(call('env.lookup', 'HOME'), Var('', 'None'))
            self.assertEqual(call('io.print', 'out'), UNIT)
            self.assertEqual(call('io.eprint', 'err'), UNIT)
            self.assertEqual(call('time.now-ms'), 42)
            self.assertEqual(call('time.mono-ms'), 42)
            self.assertEqual(call('rand.int', 0, 99), 35)
            self.assertEqual(call('fs.make-dir', 'd'), UNIT)
            self.assertEqual(call('fs.write', 'd/x.txt', 'X'), UNIT)
            self.assertEqual(call('fs.append', 'd/x.txt', 'Y'), UNIT)
            self.assertEqual(call('fs.read', 'd/x.txt'), 'XY')
            self.assertTrue(call('fs.exists', 'd/x.txt'))
            self.assertTrue(call('fs.is-dir', 'd'))
            self.assertEqual(call('fs.entries', 'd'), ('x.txt',))
            self.assertEqual(call('fs.rename', 'd', 'moved'), UNIT)
            self.assertEqual(call('fs.remove', 'moved/x.txt'), UNIT)
            self.assertEqual(call('fs.remove', 'moved'), UNIT)
            self.assertEqual(world.out.getvalue(), 'out\n')
            self.assertEqual(world.err.getvalue(), 'err\n')
            for mock in mocks:
                self.assertEqual(mock.mock_calls, [])
        self.assertEqual(dict(os.environ), host_env)

    def test_failed_tree_operations_are_atomic(self):
        world = FakeWorld([('dir', ('d',)), ('dir', ('d/sub',)),
                           ('file', ('d/sub/a', 'A')),
                           ('file', ('occupied', 'X'))])
        before = (dict(world.files), set(world.dirs))
        for op, args in [('rename', ('d', 'occupied')),
                         ('rename', ('d', 'd/sub/new')),
                         ('rename', ('d', 'missing/new')),
                         ('rename', ('d', 'bad//path')),
                         ('remove', ('d',)),
                         ('make-dir', ('missing/new',)),
                         ('write', ('d', 'text'))]:
            with self.subTest(op=op, args=args):
                with self.assertRaises(LmFail) as error:
                    world.call('fs.' + op, None, args)
                self.assertEqual(error.exception.id, 'fs.IoError')
                self.assertEqual(error.exception.args_[0], args[0])
                self.assertEqual((world.files, world.dirs), before)


if __name__ == '__main__':
    unittest.main()
