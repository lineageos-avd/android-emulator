#!/usr/bin/env python3
"""Exercise the desktop verifier against a real MSVC-linked delay-import PE."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import urllib.request

import pefile

VERIFIER_URL = 'https://raw.githubusercontent.com/moeleak/emulator-hub/88a93c9a1a9fdea6d69e4f30bbea46dce6525a3f/scripts/verify-windows-runtime.py'
VERIFIER_SHA256 = 'ceee26ff50da604ca8f0d25b5dfce46daa1186c1b3afdd242ff06d2f906904d9'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if platform.system() != 'Windows':
        parser.error('This probe runs native Microsoft cl/link/dumpbin on Windows')
    vswhere = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    installation = Path(subprocess.check_output([str(vswhere), '-latest', '-products', '*', '-requires',
        'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'], text=True).strip())
    compiler = sorted((installation / 'VC/Tools/MSVC').glob('*/bin/Hostx64/x64/cl.exe'))[-1].parent
    with urllib.request.urlopen(VERIFIER_URL, timeout=30) as response:
        verifier_source = response.read()
    if hashlib.sha256(verifier_source).hexdigest() != VERIFIER_SHA256:
        raise RuntimeError('Pinned desktop PE verifier checksum mismatch')
    with tempfile.TemporaryDirectory(prefix='pe-delay-import-probe-') as temporary:
        directory = Path(temporary)
        verifier = directory / 'verify-windows-runtime.py'
        verifier.write_bytes(verifier_source)
        (directory / 'kernel32.def').write_text('LIBRARY KERNEL32.dll\nEXPORTS\nExitProcess\n')
        (directory / 'vcruntime.def').write_text('LIBRARY VCRUNTIME140.dll\nEXPORTS\n_CxxThrowException\n')
        # The delayed function is deliberately retained but never called. Both
        # executables can run without the redistributable installed, while the
        # second PE still contains a genuine delayed CRT import to reject.
        (directory / 'main.c').write_text('''
__declspec(dllimport) void __stdcall ExitProcess(unsigned long);
#ifdef DELAY_RUNTIME
__declspec(dllimport) void _CxxThrowException(void*, void*);
void* __stdcall __delayLoadHelper2(const void* descriptor, void** address) { return 0; }
void retained_delayed_code(void) { _CxxThrowException(0, 0); }
#endif
void mainCRTStartup(void) { ExitProcess(0); }
''')
        def run(tool, *arguments):
            subprocess.run([str(compiler / (tool + '.exe')), *arguments], cwd=directory, check=True)
        run('lib', '/nologo', '/machine:x64', '/def:kernel32.def', '/out:kernel32.lib')
        run('lib', '/nologo', '/machine:x64', '/def:vcruntime.def', '/out:vcruntime.lib')
        for name, defines in [('system-only', []), ('delay-runtime', ['/DDELAY_RUNTIME'])]:
            run('cl', '/nologo', '/c', '/GS-', '/Zl', *defines, 'main.c', '/Fo' + name + '.obj')
            options = ['/delayload:VCRUNTIME140.dll', 'vcruntime.lib'] if defines else []
            run('link', '/nologo', '/nodefaultlib', '/entry:mainCRTStartup', '/subsystem:console',
                '/opt:noref', name + '.obj', 'kernel32.lib', *options, '/out:' + name + '.exe')
            subprocess.run([str(directory / (name + '.exe'))], check=True, timeout=10)
        with pefile.PE(str(directory / 'delay-runtime.exe')) as image:
            delayed = [entry.dll.decode('ascii') for entry in image.DIRECTORY_ENTRY_DELAY_IMPORT]
        assert delayed == ['VCRUNTIME140.dll'], delayed
        results = {}
        for name, expected in [('system-only', 0), ('delay-runtime', 1)]:
            result = subprocess.run([sys.executable, str(verifier), '--binary', str(directory / (name + '.exe')),
                '--reader', str(compiler / 'dumpbin.exe'), '--output', str(directory / (name + '.json'))],
                capture_output=True, text=True)
            if result.returncode != expected:
                raise RuntimeError(f'{name}: unexpected verifier result {result.returncode}: {result.stdout} {result.stderr}')
            report = json.loads((directory / (name + '.json')).read_text())
            if expected and report['redistributable_runtime_imports'] != ['VCRUNTIME140.dll']:
                raise RuntimeError(f'Delayed runtime import was not reported: {report}')
            results[name] = {'exit_code': result.returncode, 'imports': report['imports'], 'status': report['status']}
        report = {'status': 'passed', 'compiler_version': compiler.parents[2].name,
                  'verifier_url': VERIFIER_URL, 'verifier_sha256': VERIFIER_SHA256,
                  'actual_delay_imports': delayed, 'both_fixtures_executed': True, 'results': results}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
