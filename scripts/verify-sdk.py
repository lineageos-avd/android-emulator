#!/usr/bin/env python3
"""Verify and execute an extracted SDK archive without launching a guest."""
import argparse
import hashlib
import json
import ntpath
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import platform
import re
import stat
import subprocess
import tempfile
import zipfile

PLATFORMS = {
    'linux-x86_64': ('Linux', 'x86_64', 'linux'),
    'windows-x86_64': ('Windows', 'x86_64', 'windows'),
    'darwin-x86_64': ('Darwin', 'x86_64', 'darwin'),
    'darwin-aarch64': ('Darwin', 'aarch64', 'darwin_aarch64'),
}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_checksums(path):
    checksums = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'([a-fA-F0-9]{64})  ([^/\\]+)', line)
        if not match or match[2] in checksums:
            raise ValueError(f'Malformed or duplicate checksum in {path.name}')
        checksums[match[2]] = match[1].lower()
    return checksums


def extract_sdk(archive, destination):
    seen = set()
    expanded_size = 0
    with zipfile.ZipFile(archive) as zipped:
        for entry in zipped.infolist():
            name = entry.filename
            path = PurePosixPath(name)
            windows = PureWindowsPath(name)
            if (not name or '\\' in name or path.is_absolute() or windows.drive
                    or any(part in ('', '.', '..') for part in name.rstrip('/').split('/'))
                    or any(':' in part or part.endswith((' ', '.')) or
                           (ntpath.isreserved(part) if hasattr(ntpath, 'isreserved')
                            else PureWindowsPath(part).is_reserved()) for part in path.parts)):
                raise ValueError(f'Unsafe archive path: {name!r}')
            key = name.rstrip('/').casefold()
            if key in seen:
                raise ValueError(f'Duplicate archive path: {name!r}')
            seen.add(key)
            mode = entry.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError(f'Non-regular archive entry: {name!r}')
            expanded_size += entry.file_size
            if entry.file_size > 16 * 1024**3 or expanded_size > 64 * 1024**3:
                raise ValueError('Archive exceeds the SDK extraction size limit')
            target = destination.joinpath(*path.parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(entry) as source, target.open('xb') as output:
                copied = 0
                while chunk := source.read(min(1024**2, entry.file_size - copied + 1)):
                    copied += len(chunk)
                    if copied > entry.file_size:
                        raise ValueError(f'Archive entry exceeds its declared size: {name!r}')
                    output.write(chunk)
            if copied != entry.file_size:
                raise ValueError(f'Incomplete archive entry: {name!r}')
            if os.name != 'nt':
                target.chmod((mode & 0o777) or 0o644)
    return len(seen)


def verify(args):
    expected_os, expected_arch, upstream_target = PLATFORMS[args.target]
    actual_arch = {'AMD64': 'x86_64', 'arm64': 'aarch64'}.get(
        platform.machine(), platform.machine())
    if (platform.system(), actual_arch) != (expected_os, expected_arch):
        raise ValueError(f'{args.target} requires its matching native host; '
                         f'got {platform.system()} {platform.machine()}')
    assets = [path for path in args.dist.glob(f'sdk-repo-{upstream_target}-emulator-*.zip')
              if '-symbols-' not in path.name and '-debug-' not in path.name]
    if len(assets) != 1:
        raise ValueError(f'Expected one SDK archive for {args.target}, found {assets}')
    archive = assets[0]
    provenance_path = args.dist / f'provenance-{args.target}.json'
    manifest_path = args.dist / f'manifest-{args.target}.xml'
    checksums = read_checksums(args.dist / f'SHA256SUMS-{args.target}')
    for path in (archive, provenance_path, manifest_path):
        if checksums.get(path.name) != digest(path):
            raise ValueError(f'Checksum mismatch or missing checksum: {path.name}')
    provenance = json.loads(provenance_path.read_text(encoding='utf-8'))
    if provenance['target'] != args.target or provenance['upstream_tests'] != 'passed':
        raise ValueError('Provenance does not describe a tested build of the requested target')
    if args.expected_recipe_commit and provenance['recipe_commit'] != args.expected_recipe_commit:
        raise ValueError('Provenance recipe commit differs from the producing workflow run')
    with tempfile.TemporaryDirectory(prefix='hub-sdk-verification-') as temporary:
        extracted = Path(temporary)
        entries = extract_sdk(archive, extracted)
        sdk = extracted / 'emulator'
        if json.loads((sdk / 'hub-provenance.json').read_text(encoding='utf-8')) != provenance:
            raise ValueError('Embedded and external provenance differ')
        if (sdk / 'hub-source-manifest.xml').read_bytes() != manifest_path.read_bytes():
            raise ValueError('Embedded and external source manifests differ')
        properties = dict(line.split('=', 1) for line in
                          (sdk / 'source.properties').read_text(encoding='utf-8').splitlines()
                          if '=' in line)
        version = properties['Pkg.Revision'].strip()
        if version != provenance.get('sdk_version', version):
            raise ValueError('Packaged SDK version and provenance differ')
        windows_dependencies = None
        if expected_os == 'Windows':
            from windows_runtime import audit
            dependencies = audit(sdk)
            windows_dependencies = {
                'pe_binaries': dependencies['pe_binaries'],
                'dependency_edges': len(dependencies['dependency_edges']),
                'vc_runtime': dependencies['vc_runtime'],
            }
        executable = sdk / ('emulator.exe' if expected_os == 'Windows' else 'emulator')
        environment = os.environ.copy()
        search_path = None
        if expected_os == 'Windows':
            system = Path(environment['SystemRoot'])
            search_path = [sdk, sdk / 'lib64', sdk / 'lib64/qt/lib', system / 'System32', system]
            environment['PATH'] = os.pathsep.join(map(str, search_path))
        result = subprocess.run([str(executable), '-version'], cwd=sdk, env=environment,
                                capture_output=True, text=True, errors='replace', timeout=45)
        output = result.stdout + result.stderr
        if result.returncode != 0:
            raise ValueError(f'Extracted emulator -version failed ({result.returncode}): {output}')
        found = re.search(r'Android emulator version ([0-9]+\.[0-9]+\.[0-9]+)', output)
        if not found or found[1] != version:
            raise ValueError(f'Executable version differs from packaged metadata: {output}')
        return {'status': 'passed', 'target': args.target, 'archive': archive.name,
                'size': archive.stat().st_size, 'sha256': digest(archive),
                'sdk_version': version, 'recipe_commit': provenance['recipe_commit'],
                'host_os': platform.system(), 'host_arch': actual_arch,
                'zip_entries': entries, 'command': ['emulator', '-version'],
                'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr,
                'windows_dependencies': windows_dependencies,
                'windows_search_path': list(map(str, search_path)) if search_path else None,
                'guest_boot_tested': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--target', choices=PLATFORMS, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-recipe-commit')
    args = parser.parse_args()
    try:
        result = verify(args)
    except Exception as error:
        result = {'status': 'failed', 'target': args.target, 'error': str(error)}
        raise
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
