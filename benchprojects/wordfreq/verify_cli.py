from pathlib import Path
from collections import Counter
import re
import subprocess

prefix=['./wordfreq']

def expected(text,n=10):
    counts=Counter(re.findall('[a-z0-9]+', text.lower()))
    return ''.join(f'{count} {word}\n' for word,count in sorted(counts.items(),key=lambda item:(-item[1],item[0]))[:n])

sample=Path('sample.txt').read_text()
cases=[(['sample.txt'],0,expected(sample)),(['sample.txt','2'],0,expected(sample,2)),([],2,'usage: wordfreq FILE [N]\n'),(['missing-wordfreq-file.txt'],1,'error: cannot read missing-wordfreq-file.txt\n')]
for value in ['0','-1','','abc','1.5',' 2','+2','000']:
    cases.append((['sample.txt',value],2,'error: N must be a positive integer\n'))
for value in ['0002','9223372036854775808','9'*100]:
    cases.append((['sample.txt',value],0,expected(sample,2 if value=='0002' else 100)))
Path('empty.txt').write_text('')
Path('edge.txt').write_text('Z9_z9 123 123 éA😀b A\tB\n')
Path('many.txt').write_text(' '.join('w'+str(i) for i in range(15)))
for name in ['empty.txt','edge.txt','many.txt']:
    cases.append(([name],0,expected(Path(name).read_text())))
for args,status,out in cases:
    p=subprocess.run(prefix+args,text=True,capture_output=True)
    assert (p.returncode,p.stdout,p.stderr)==(status,out,''), (args,p.returncode,p.stdout,p.stderr,out)
print(f'CLI verification: {len(cases)} cases passed (output and actual exit status).')
print('Sample output:')
print(subprocess.run(prefix+['sample.txt'],text=True,capture_output=True).stdout,end='')
for name in ['empty.txt','edge.txt','many.txt']:
    Path(name).unlink()
