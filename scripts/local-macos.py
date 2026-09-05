#!/usr/bin/env python3
"""Build both Mac targets in a dedicated, already-mounted case-sensitive volume.

Only child process groups started here can be stopped by the disk guard. Existing
emulators and user applications are never touched. Run on a physical Mac with
Xcode/SDK, Nix, and Rosetta for the Intel unit suite.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--backing-store', type=Path, required=True, help='Existing path on the physical volume hosting the sparse bundle')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--target', choices=['all', 'darwin-aarch64', 'darwin-x86_64'], default='all',
                        help='Resume one architecture without rebuilding a completed SDK')
    parser.add_argument('--skip-sync', action='store_true',
                        help='Reuse an existing pinned checkout; build.py still verifies revisions and patches')
    parser.add_argument('--keep-build-dirs', action='store_true', help='Retain intermediate build directories after verified SDK ZIP packaging')
    args = parser.parse_args()
    if platform.system() != 'Darwin':
        parser.error('A physical Mac is required')
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    if not workspace.is_mount():
        parser.error('--workspace must be a dedicated mounted build volume')
    source, dist = workspace / 'source', workspace / 'dist'
    revision = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    stages = [] if args.skip_sync else [('sync', [sys.executable, str(ROOT / 'scripts/sync.py'), '--source', str(source), '--revision', revision, '--jobs', '4'])]
    targets = ['darwin-aarch64', 'darwin-x86_64'] if args.target == 'all' else [args.target]
    native = 'darwin-aarch64' if platform.machine().lower() in {'aarch64', 'arm64'} else 'darwin-x86_64'
    if native == 'darwin-x86_64' and 'darwin-aarch64' in targets:
        parser.error('Building and testing both targets requires Apple Silicon; on Intel use --target darwin-x86_64')
    for target in targets:
        command = ['nix', 'develop', str(ROOT), '-c', 'python3', str(ROOT / 'scripts/build.py'),
                   '--source', str(source), '--target', target, '--out', str(workspace / ('out-' + target)),
                   '--dist', str(dist / target), '--jobs', str(args.jobs), '--build-number', '36.1-hub.1']
        if target != native:
            # Rosetta can execute the Intel unit suite, but it cannot validate
            # Intel guest virtualization on an Apple Silicon hypervisor.
            command += ['--skip-acceleration-check']
        stages.append((target, command))
    status_path = workspace / 'build-status.json'
    for name, command in stages:
        print(f'Starting {name}: {command}', flush=True)
        state = {'stage': name, 'status': 'running', 'recipe_commit': revision}
        status_path.write_text(json.dumps(state, indent=2) + '\n')
        process = subprocess.Popen(command, cwd=ROOT, start_new_session=True)
        try:
            while process.poll() is None:
                host_free = shutil.disk_usage(args.backing_store).free
                build_free = shutil.disk_usage(workspace).free
                if host_free < 20 * 1024**3 or build_free < 3 * 1024**3:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    raise RuntimeError(f'Disk guard stopped this build: physical={host_free}, build-volume={build_free} free bytes')
                time.sleep(5)
            if process.returncode:
                raise RuntimeError(f'{name} failed with exit {process.returncode}')
        except BaseException as error:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
            state.update(status='failed', reason=str(error))
            status_path.write_text(json.dumps(state, indent=2) + '\n')
            raise
        if name.startswith('darwin-') and not args.keep_build_dirs:
            # Upstream has already packaged the runtime and debug symbols.
            # Release only this pipeline's disposable intermediates before
            # compiling the second architecture on a size-limited volume.
            shutil.rmtree(workspace / ('out-' + name))
        state['status'] = 'passed'
        status_path.write_text(json.dumps(state, indent=2) + '\n')
    print(f'Selected Mac targets built and tested: {targets}: {dist}', flush=True)


if __name__ == '__main__':
    main()
