"""One real-process oracle for every subprocess backend."""
import shlex

from lm.values import show


def source(root):
    forms = []

    def check(expr):
        n = len(forms) + 1
        forms.append(f'(io.print (if {expr} "ok {n}" "BAD {n}"))')

    def run(script, stdin='""', cwd='None', env='(list)'):
        return call('(list "/bin/sh" "-c" ' + show(script) + ')',
                    stdin, cwd, env)

    def call(argv, stdin='""', cwd='None', env='(list)'):
        return f'(proc.run {argv} {stdin} {cwd} {env})'

    def bad(expr, category):
        return ('(try (let ((ignored ' + expr + ')) false) '
                '(catch proc.ProcError (msg) (= msg ' + show(category) + ')))')

    check('(= ' + run('printf héllo; printf problem >&2; exit 7') +
          ' (new proc.Result (exit (proc.Exited 7)) '
          '(stdout "héllo") (stderr "problem")))')
    check('(= (get ' + run('kill -TERM $$') +
          ' exit) (proc.Signaled 15))')
    check('(= (get ' + call('(list "/usr/bin/env")') + ' stdout) "")')
    check('(= (get ' + call('(list "/usr/bin/env")',
                            env='(list (pair "ONLY" "héllo"))') +
          ' stdout) ' + show('ONLY=héllo\n') + ')')
    # Physical pwd avoids platform-specific /tmp -> /private/tmp symlinks.
    check('(= (get ' + run('pwd -P', cwd='(Some ' + show(str(root)) + ')') +
          ' stdout) ' + show(str(root.resolve()) + '\n') + ')')
    # Fill stderr before reading stdin: sequential pipe handling deadlocks.
    check('(let ((r ' + run(
        '/usr/bin/head -c 1048577 /dev/zero | /usr/bin/tr "\\000" x >&2; '
        '/bin/cat', stdin='(str.repeat "é" 600000)') + ')) '
        '(and (= (get r stdout) (str.repeat "é" 600000)) '
        '(= (str.length (get r stderr)) 1048577)))')
    for script in ("printf '\\377'", "printf '\\377' >&2"):
        check(bad(run(script), 'invalid-utf8'))
    check(bad(call('(list "/no/lm-proc-executable")'), 'not-found'))
    check(bad(run('exit 0', cwd='(Some "/no/lm-proc-dir")'), 'not-found'))
    check(bad(run('exit 0', cwd='(Some ' + show(str(root / 'noexec')) + ')'),
              'not-found'))
    check(bad(call('(list ' + show(str(root / 'noexec')) + ')'), 'permission'))
    check(bad(call('(list ' + show(str(root / 'text-executable')) + ')'),
              'spawn'))
    for argv, stdin, cwd, env in [
            ('(list)', '""', 'None', '(list)'),
            ('(list "sh")', '""', 'None', '(list)'),
            ('(list "/bin/sh" "a\\u{0}")', '""', 'None', '(list)'),
            ('(list "/bin/sh")', '"a\\u{0}"', 'None', '(list)'),
            ('(list "/bin/sh")', '""', '(Some "a\\u{0}")', '(list)'),
            ('(list "/bin/sh")', '""', 'None', '(list (pair "a\\u{0}" "x"))'),
            ('(list "/bin/sh")', '""', 'None', '(list (pair "a" "x\\u{0}"))'),
            ('(list "/bin/sh")', '""', 'None', '(list (pair "" "x"))'),
            ('(list "/bin/sh")', '""', 'None', '(list (pair "a=b" "x"))'),
            ('(list "/bin/sh")', '""', 'None',
             '(list (pair "a" "1") (pair "a" "2"))'),
            ('(list "/bin/sh")', '(str.repeat "é" 4194305)', 'None', '(list)'),
            ('(list "/bin/sh" (str.repeat "é" 32768))',
             '""', 'None', '(list)'),
            ('(list "/bin/sh")', '""', 'None',
             '(list (pair "a" (str.repeat "é" 32768)))')]:
        check(bad(call(argv, stdin, cwd, env), 'invalid-request'))
    # Exactly 64 KiB, counting '=' but not C string terminators.
    check('(= (get ' + call('(list "/usr/bin/env")',
                            env='(list (pair "K" (str.repeat "x" 65522)))') +
          ' exit) (proc.Exited 0))')
    check('(= (get ' + run('/bin/cat >/dev/null',
                            stdin='(str.repeat "é" 4194304)') +
          ' exit) (proc.Exited 0))')
    check('(= (str.length (get ' +
          run('/usr/bin/head -c 8388608 /dev/zero') +
          ' stdout)) 8388608)')
    check(bad(run('/usr/bin/head -c 8388609 /dev/zero'), 'limit'))
    check(bad(run('/usr/bin/head -c 4194305 /dev/zero; '
                  '/usr/bin/head -c 4194304 /dev/zero >&2'), 'limit'))
    pid = shlex.quote(str(root / 'grandchild.pid'))
    check(bad(run('/bin/sleep 20 & child=$!; '
                  'printf %s "$child" > ' + pid + '; wait'), 'timeout'))
    # Deadline also covers open pipes after the direct child exits.
    pipe_pid = shlex.quote(str(root / 'pipe-grandchild.pid'))
    check(bad(run('/bin/sleep 20 & printf %s "$!" > ' + pipe_pid + '; exit 0'),
              'timeout'))
    text = ('(module proc-probe '
            '(purpose "Compare real subprocess semantics.") '
            '(use proc io str) (fn main '
            '(purpose "Print numbered assertions.") '
            '(sig -> Int) (eff proc.run io.out) (fails proc.ProcError) '
            '(body (do ' + ' '.join(forms) + ' 0))))')
    expected = ''.join(f'ok {n}\n' for n in range(1, len(forms) + 1))
    return text, expected.encode()
