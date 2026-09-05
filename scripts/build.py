#!/usr/bin/env python3
"""Delegate configuration, compilation, tests and packaging to upstream."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess

from source_patches import apply_patches

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
    recipe_commit = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    apply_patches(source)
    dist.mkdir(parents=True, exist_ok=True)
    host = platform.system().lower()
    if (host == 'darwin' and platform.machine().lower() not in {'arm64', 'aarch64'}
            and args.target == 'darwin-aarch64' and not args.skip_tests):
        raise SystemExit('ARM64 Mac release tests require Apple Silicon; Intel hosts can only cross-build diagnostic artifacts with --skip-tests')
    if host == 'windows':
        command = ['cmd', '/c', str(qemu / 'android/rebuild.cmd')]
    else:
        command = ['sh', str(qemu / 'android/rebuild.sh')]
    # Upstream infers the AOSP root as a Path from its script location. Its
    # --aosp parser returns str, which breaks task construction in this revision.
    command += ['--target', args.target, '--out', str(output),
                '--dist', str(dist), '--sdk_build_number', args.build_number,
                '--config', 'release', '--crash', 'none', '--task-disable', 'clean',
                # Auxiliary upstream VNC integration-runner ZIP is not an SDK artifact.
                # CTest and acceleration checks still run unchanged.
                '--task-disable', 'zipintegrationtests',
                '--test_jobs', str(min(args.jobs, 8))]
    if host == 'linux':
        command += ['--cmake_option', 'CMAKE_SKIP_BUILD_RPATH=ON',
                    '--cmake_option', 'CMAKE_SHARED_LINKER_FLAGS=-Wl,-z,noexecstack',
                    '--cmake_option', 'CMAKE_EXE_LINKER_FLAGS=-Wl,-z,noexecstack']
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
    if host == 'linux':
        # Nix's ld wrapper must not append compiler sysroot directories to
        # runtime search paths; upstream already provides $ORIGIN paths.
        env['NIX_DONT_SET_RPATH'] = '1'
    if host == 'darwin':
        sdk = env.get('EMULATOR_MACOS_SDK')
        compatible = Path('/Library/Developer/CommandLineTools/SDKs/MacOSX14.5.sdk')
        if not sdk:
            sdk = str(compatible) if compatible.is_dir() else subprocess.check_output(
                ['/usr/bin/xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
        deployment = '11.0' if args.target == 'darwin-aarch64' else '10.14'
        env.update(EMULATOR_MACOS_SDK=sdk, SDKROOT=sdk, MACOSX_DEPLOYMENT_TARGET=deployment)
        sdk_path = Path(sdk).resolve()
        xcode = next((path for path in sdk_path.parents if path.suffix == '.app'), None)
        developer = xcode / 'Contents/Developer' if xcode else Path('/Library/Developer/CommandLineTools')
        if (developer / 'usr/bin/mig').is_file():
            # Nix's DEVELOPER_DIR points at SDK headers only, not Apple tools.
            env['DEVELOPER_DIR'] = str(developer)
            env['PATH'] = str(developer / 'usr/bin') + os.pathsep + env.get('PATH', '')

        # Override Nix's SDK CMake defaults when using Google's compiler.
        # Nix's SDK strips libc++ stubs because its own toolchain supplies them.
        command += ['--cmake_option', 'CMAKE_OSX_SYSROOT=' + sdk,
                    '--cmake_option', 'CMAKE_OSX_DEPLOYMENT_TARGET=' + deployment]
    subprocess.run(command, cwd=qemu, env=env, check=True)
    subprocess.run(['python3' if host != 'windows' else 'python', str(ROOT / 'scripts/provenance.py'),
                    '--source', str(source), '--dist', str(dist), '--target', args.target,
                    '--build-number', args.build_number, '--recipe-commit', recipe_commit, *(['--tests-skipped'] if args.skip_tests else [])], check=True)


if __name__ == '__main__':
    main()
