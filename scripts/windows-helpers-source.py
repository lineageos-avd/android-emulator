#!/usr/bin/env python3
"""Package the pinned Windows Cygwin helper sources, recipes and provenance.

The map in docs/windows-helpers-source.json fixes every URL and digest. Source
and manifest pins must agree before any download. --offline verifies and reuses
an existing cache; it never falls back to the network. Existing differing output
files are refused, so this command cannot silently replace a published asset.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = 'windows-helpers-corresponding-source-35.3.8.tar.gz'
PREFIX = 'windows-helpers-corresponding-source'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path, algorithm='sha256'):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def filename(value):
    require(value and PurePosixPath(value).name == value and value not in ('.', '..'),
            f'Expected an archive filename: {value!r}')
    return value


def git(source, *args):
    return subprocess.check_output(['git', '-C', str(source), *args])


def verify_source(source, data):
    manifest = {p.get('path', p.get('name')): p.get('revision')
                for p in ET.parse(ROOT / 'default.xml').getroot().findall('project')}
    checkouts = {}
    for name, revision in data['google_revisions'].items():
        path = 'external/qemu' if name == 'qemu' else name
        require(manifest.get(path) == revision,
                f'Manifest pin changed for {path}; audit and update the Windows helper source map first')
        checkout = source / path
        require(git(checkout, 'rev-parse', 'HEAD').decode().strip() == revision,
                f'Checkout pin differs from the source map: {path}')
        checkouts[name] = checkout
    common = checkouts['prebuilts/android-emulator-build/common']
    archive = checkouts['prebuilts/android-emulator-build/archive']
    packages = {}
    for row in data['binary_source_map']:
        name = filename(PurePosixPath(row['binary']).name)
        require(digest(common / 'e2fsprogs/windows-x86/sbin' / name) == row['sha256'],
                f'Windows helper bytes changed: {name}')
        package = filename(row['google_binary_package'])
        if package not in packages:
            packages[package] = git(archive, 'show', f'HEAD:{package}')
        raw = packages[package]
        require(hashlib.sha256(raw).hexdigest() == row['google_package_sha256'] and
                hashlib.sha512(raw).hexdigest() == row['historical_package_sha512'],
                f'Google binary package digest changed: {package}')
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
            member = tar.getmember(row['google_package_member'])
            require(member.isfile(), f'Expected regular binary member in {package}')
            require(hashlib.sha256(tar.extractfile(member).read()).hexdigest() == row['sha256'],
                    f'Binary no longer matches its original package: {name}')
    return checkouts, packages


def cached(path, record, offline):
    def verify(candidate):
        require('size' not in record or candidate.stat().st_size == record['size'],
                f'Cached size mismatch: {path.name}')
        for algorithm in ('sha256', 'sha512'):
            if algorithm in record:
                require(digest(candidate, algorithm) == record[algorithm],
                        f'Cached {algorithm} mismatch: {path.name}')
    if path.exists():
        verify(path)
        return path
    require(not offline, f'Offline cache missing: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    # Download to a private temporary file; invalid/incomplete data never becomes
    # a cache hit. All URLs are fixed in the checked-in source map.
    with tempfile.TemporaryDirectory(prefix='helper-download-', dir=path.parent) as temp:
        partial = Path(temp) / path.name
        with urllib.request.urlopen(record['url'], timeout=60) as response, partial.open('wb') as out:
            shutil.copyfileobj(response, out)
        verify(partial)
        partial.replace(path)
    return path


def verify_index(index, data):
    text = index.read_text(encoding='latin-1')
    for row in data['binary_source_map']:
        source = data['source_packages'][row['source_package']]
        match = re.search(r'^install: (\S*/' + re.escape(row['google_binary_package']) +
                          r') (\d+) ([a-f0-9]+)\nsource: (\S+) (\d+) ([a-f0-9]+)', text, re.M)
        require(match is not None, f'Package not found in historical index: {row["binary"]}')
        require(match[3] == row['historical_package_sha512'] and
                match[4] == source['source_path'] and int(match[5]) == source['size'] and
                match[6] == source['sha512'] and row['source_sha256'] == source['sha256'],
                f'Historical binary/source association changed: {row["binary"]}')


def write_checksums(directory, output, files):
    (directory / output).write_text(''.join(
        f'{digest(path)}  {path.relative_to(directory).as_posix()}\n' for path in sorted(files)))


def populate(stage, cache, source_data, checkouts, packages, offline):
    sources = stage / 'sources'
    provenance = stage / 'provenance'
    notices = stage / 'notices'
    for path in (sources, provenance, notices):
        path.mkdir(parents=True)
    index_name = 'cygwin-20150714-setup.ini'
    index = cached(cache / 'provenance' / index_name, source_data['historical_setup'], offline)
    verify_index(index, source_data)
    shutil.copyfile(index, provenance / index_name)
    for name, record in source_data['source_packages'].items():
        path = cached(cache / 'sources' / filename(name), record, offline)
        shutil.copyfile(path, sources / name)
        with tarfile.open(path) as tar:
            members = {member.name: member for member in tar.getmembers()}
            require(len(members) == record['member_count'], f'Source member count differs: {name}')
            require(any(member.endswith('.cygport') for member in record['recipe_members']),
                    f'Cygwin recipe missing: {name}')
            for member_name in record['upstream_archive_members'] + record['recipe_members']:
                require(member_name in members and members[member_name].isfile(),
                        f'Source or recipe member missing: {member_name}')
            for member_name in record['recipe_members']:
                destination = stage / 'recipes' / name.removesuffix('-src.tar.xz') / filename(PurePosixPath(member_name).name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(tar.extractfile(members[member_name]).read())
    (provenance / 'binary-source-map.json').write_text(json.dumps(source_data, indent=2) + '\n')
    (provenance / 'source-downloads.json').write_text(json.dumps(source_data['source_packages'], indent=2) + '\n')
    (provenance / 'google-PACKAGES.TXT').write_bytes(git(
        checkouts['prebuilts/android-emulator-build/archive'], 'show', 'HEAD:PACKAGES.TXT'))
    (provenance / 'google-emu-e2fsprogs-config.cmake').write_bytes(git(
        checkouts['qemu'], 'show', 'HEAD:android/build/cmake/config/emu-e2fsprogs-config.cmake'))
    (notices / 'Google-LICENSE.E2FS').write_bytes(git(checkouts['qemu'], 'show', 'HEAD:LICENSES/LICENSE.E2FS'))
    with tarfile.open(fileobj=io.BytesIO(packages['cygwin-2.0.4-1.tar.xz'])) as tar:
        for name in ('COPYING', 'COPYING.NEWLIB'):
            (notices / ('Cygwin-' + name)).write_bytes(tar.extractfile('usr/share/doc/cygwin-2.0.4/' + name).read())
    shutil.copyfile(ROOT / 'docs/windows-helpers-source.md', stage / 'README.md')
    write_checksums(stage, 'SHA256SUMS', [p for p in stage.rglob('*') if p.is_file()])


def package(stage, output):
    with output.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, compresslevel=1, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|') as tar:
            for path in sorted(stage.rglob('*')):
                info = tar.gettarinfo(str(path), arcname=PREFIX + '/' + path.relative_to(stage).as_posix())
                info.uid = info.gid = 0
                info.uname = info.gname = ''
                info.mtime = 0
                info.mode = 0o644 if path.is_file() else 0o755
                with path.open('rb') if path.is_file() else io.BytesIO() as stream:
                    tar.addfile(info, stream if path.is_file() else None)
    expected = dict(line.split('  ', 1)[::-1] for line in (stage / 'SHA256SUMS').read_text().splitlines())
    found = {}
    with tarfile.open(output) as tar:
        for member in tar:
            if member.isfile():
                name = member.name.removeprefix(PREFIX + '/')
                if name != 'SHA256SUMS':
                    found[name] = hashlib.sha256(tar.extractfile(member).read()).hexdigest()
    require(found == expected, 'Generated source archive failed its internal SHA256 verification')
    return len(found)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'source', help='Synced Google source tree (default: ./source)')
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--cache', type=Path, default=Path.home() / '.cache/emulator-hub/windows-helper-sources')
    parser.add_argument('--offline', action='store_true', help='Require verified cached source archives and setup.ini')
    args = parser.parse_args()
    data = json.loads((ROOT / 'docs/windows-helpers-source.json').read_text())
    require(data['schema_version'] == 1, 'Unsupported Windows helper map schema')
    checkouts, packages = verify_source(args.source.resolve(), data)
    args.dist.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='windows-helper-source-', dir=args.dist) as temp:
        work = Path(temp)
        stage = work / 'tree'
        populate(stage, args.cache.resolve(), data, checkouts, packages, args.offline)
        count = package(stage, work / ARCHIVE)
        shutil.copyfile(stage / 'README.md', work / 'windows-helpers-source-notice.md')
        shutil.copyfile(stage / 'provenance/binary-source-map.json', work / 'windows-helpers-source-map.json')
        assets = [work / name for name in (ARCHIVE, 'windows-helpers-source-notice.md', 'windows-helpers-source-map.json')]
        write_checksums(work, 'SHA256SUMS-windows-helpers', assets)
        assets.append(work / 'SHA256SUMS-windows-helpers')
        # Check every destination before publishing any generated files.
        for path in assets:
            target = args.dist / path.name
            require(not target.exists() or digest(target) == digest(path),
                    f'Refusing to replace differing output {target}; use a fresh --dist directory')
        for path in assets:
            target = args.dist / path.name
            if not target.exists():
                path.replace(target)
        print(f'Verified {len(data["binary_source_map"])} helpers, {len(data["source_packages"])} source packages and {count} archive files')
        print((args.dist / 'SHA256SUMS-windows-helpers').read_text(), end='')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, tarfile.TarError) as error:
        raise SystemExit(f'Windows helper source export failed: {error}') from error
