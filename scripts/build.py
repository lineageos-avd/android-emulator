#!/usr/bin/env python3
"""Delegate configuration, compilation, tests and packaging to upstream."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--target', choices=json.loads((ROOT / 'upstream.json').read_text())['targets'], required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--build-number', default='36.1-hub.1')
    parser.add_argument('--jobs', type=int, default=min(os.cpu_count() or 4, 32))
    parser.add_argument('--skip-tests', action='store_true', help='Build-only diagnostics; not allowed for release publication')
    parser.add_argument('--skip-acceleration-check', action='store_true', help='For hosted builders without nested virtualization; unit tests still run')
    args = parser.parse_args()
    source, output, dist = args.source.resolve(), args.out.resolve(), args.dist.resolve()
    expected = json.loads((ROOT / 'upstream.json').read_text())['qemu_revision']
    qemu = source / 'external/qemu'
    actual = subprocess.check_output(['git', '-C', str(qemu), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != expected:
        raise SystemExit(f'Unrecognized QEMU revision: {actual}')
    if subprocess.check_output(['git', '-C', str(qemu), 'status', '--porcelain'], text=True).strip():
        raise SystemExit('QEMU checkout has uncommitted modifications; commit patches before building')
    dist.mkdir(parents=True, exist_ok=True)
    host = platform.system().lower()
    if host == 'windows':
        command = ['cmd', '/c', str(qemu / 'android/rebuild.cmd')]
    else:
        command = ['sh', str(qemu / 'android/rebuild.sh')]
    # Upstream infers the AOSP root as a Path from its script location. Its
    # --aosp parser returns str, which breaks task construction in this revision.
    command += ['--target', args.target, '--out', str(output),
                '--dist', str(dist), '--sdk_build_number', args.build_number,
                '--config', 'release', '--crash', 'none', '--task-disable', 'clean',
                '--test_jobs', str(min(args.jobs, 8))]
    if host == 'darwin' and platform.machine().lower() in {'arm64', 'aarch64'} and args.target == 'darwin-x86_64':
        # A native Mac can run the Intel unit suite through Rosetta. Upstream
        # otherwise silently disables CTest for cross-architecture builds.
        subprocess.run(['arch', '-x86_64', '/usr/bin/true'], check=True)
        command += ['--task-enable', 'ctest']
    if args.skip_acceleration_check:
        command += ['--task-disable', 'accelerationcheck']
    if args.skip_tests:
        command += ['--task-disable', 'ctest', '--task-disable', 'accelerationcheck']
    env = os.environ | {'CMAKE_BUILD_PARALLEL_LEVEL': str(args.jobs)}
    subprocess.run(command, cwd=qemu, env=env, check=True)
    subprocess.run(['python3' if host != 'windows' else 'python', str(ROOT / 'scripts/provenance.py'),
                    '--source', str(source), '--dist', str(dist), '--target', args.target,
                    '--build-number', args.build_number, *(['--tests-skipped'] if args.skip_tests else [])], check=True)


if __name__ == '__main__':
    main()
