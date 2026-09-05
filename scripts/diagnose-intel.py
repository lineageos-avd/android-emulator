#!/usr/bin/env python3
"""Run only six requested Crashpad diagnostics on a native Intel Mac."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile

CASES = (
    ('crashpad_snapshot_test', 'ProcessReaderMac.SelfModules'),
    ('crashpad_snapshot_test', 'ProcessReaderMac.ChildModules'),
    ('crashpad_snapshot_test', 'MachOImageAnnotationsReader.CrashAbort'),
    ('crashpad_util_test', 'ExcServerVariants.ExceptionRaise'),
    ('crashpad_client_test', 'SimulateCrash.SimulateCrash'),
    ('crashpad_test_test', 'ScopedGuardedPage.BasicFunctionality'),
)


def run_case(root, output, case):
    executable, name = case
    xml = output / (name + '.xml')
    log = output / (name + '.log')
    temporary = output / (name + '-tmp')
    temporary.mkdir()
    started = time.monotonic()
    timed_out = False
    with log.open('wb') as stream:
        process = subprocess.Popen([str(root / executable), '--gtest_filter=' + name,
                                    '--gtest_output=xml:' + str(xml)], cwd=root,
                                   env=os.environ | {'TMPDIR': str(temporary) + '/'},
                                   stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            code = process.wait(timeout=180)
        except subprocess.TimeoutExpired:
            timed_out = True
            code = None
            os.killpg(process.pid, signal.SIGKILL)
        finally:
            # Each test owns a fresh session/group. Never use global pkill.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
    result = {'case': name, 'binary': executable, 'timeout_seconds': 180,
              'timed_out': timed_out, 'exit_code': code,
              'elapsed_seconds': round(time.monotonic() - started, 3),
              'log': log.name, 'xml': xml.name if xml.is_file() else None}
    if xml.is_file():
        report = ET.parse(xml).getroot()
        result['gtest'] = {field: report.attrib.get(field) for field in ('tests', 'failures', 'disabled', 'errors')}
        result['skipped'] = len(report.findall('.//skipped'))
    result['passed'] = (not timed_out and code == 0 and result.get('gtest', {}).get('tests') == '1'
                        and result['gtest']['failures'] == '0' and result['gtest']['errors'] == '0'
                        and result.get('skipped') == 0)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'x86_64':
        raise SystemExit('Requires native macOS x86_64, not Rosetta or cross-execution')
    translated = subprocess.run(['sysctl', '-in', 'sysctl.proc_translated'], capture_output=True, text=True)
    if translated.stdout.strip() == '1':
        raise SystemExit('Rosetta is not a native Intel diagnostic host')
    with args.archive.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != args.sha256:
        raise SystemExit('Diagnostic archive SHA256 mismatch')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    root = output / 'binaries'
    root.mkdir()
    allowed = {item[0] for item in CASES} | {'diagnostic-provenance.json'}
    with zipfile.ZipFile(args.archive) as archive:
        if set(archive.namelist()) != allowed or len(archive.infolist()) != len(allowed):
            raise SystemExit('Unexpected diagnostic archive members')
        for entry in archive.infolist():
            if entry.file_size > 32 * 1024**2:
                raise SystemExit('Diagnostic archive member exceeds limit')
            (root / entry.filename).write_bytes(archive.read(entry))
            (root / entry.filename).chmod(0o755)
    provenance = json.loads((root / 'diagnostic-provenance.json').read_text())
    for binary in provenance['binaries']:
        path = root / binary['name']
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != binary['sha256']:
                raise SystemExit('Individual binary checksum mismatch')
        dependencies = subprocess.check_output(['otool', '-L', str(path)], text=True)
        (output / (binary['name'] + '-otool.txt')).write_text(dependencies)
    # Independent process groups, capped at two CPU-heavy OpenCL probes in flight.
    with ThreadPoolExecutor(max_workers=6) as workers:
        results = list(workers.map(lambda case: run_case(root, output, case), CASES))
    report = {'scope': 'six selected diagnostics only, not the complete upstream suite',
              'platform': platform.platform(), 'machine': platform.machine(),
              'archive_sha256': actual, 'provenance': provenance, 'results': results}
    (output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(results, indent=2))
    raise SystemExit(0 if all(result['passed'] for result in results) else 1)


if __name__ == '__main__':
    main()
