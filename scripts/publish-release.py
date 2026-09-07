#!/usr/bin/env python3
"""Publish verified source/support first, then exactly four runtime SDK assets."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import quote
import zipfile

TARGETS = {
    'linux-x86_64': ('linux', 'x86_64', 'Linux'),
    'windows-x86_64': ('windows', 'x86_64', 'Windows'),
    'darwin-x86_64': ('macos', 'x86_64', 'Darwin'),
    'darwin-aarch64': ('macos', 'aarch64', 'Darwin'),
}
SDK_PREFIXES = {'linux-x86_64': 'linux', 'windows-x86_64': 'windows',
                'darwin-x86_64': 'darwin', 'darwin-aarch64': 'darwin_aarch64'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(dist, tag, repo, commit):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', tag) or tag.endswith('-support'):
        raise ValueError('Expected a binary release tag, without the -support suffix')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Expected owner/repository')
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Expected the full checked-out recipe commit')
    files = {p.name: p for p in dist.iterdir()}
    if any(not p.is_file() or p.is_symlink() or
           not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]*', p.name) for p in files.values()):
        raise ValueError('Release input must contain only regular files with unambiguous names')
    required = {'catalog.json', 'SOURCE_OFFER.md', 'SHA256SUMS-source',
                'SHA256SUMS-windows-helpers', 'windows-helpers-source-map.json',
                'windows-helpers-source-notice.md', 'windows-dependencies.json',
                'NOTICE.MSVC-RUNTIME.txt'}
    if not required <= files.keys():
        raise ValueError(f'Missing supporting files: {sorted(required - files.keys())}')
    if not any(name.startswith('engine-corresponding-source.tar.gz') for name in files):
        raise ValueError('Corresponding source archive missing')
    if not any(name.startswith('windows-helpers-corresponding-source-') for name in files):
        raise ValueError('Windows helper source archive missing')
    hashes = {name: digest(path) for name, path in files.items()}
    covered = set()
    for name in files:
        if not name.startswith('SHA256SUMS-'):
            continue
        seen = set()
        for line in files[name].read_text().splitlines():
            match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9_.+-]*)', line)
            if not match or match[2] in seen or hashes.get(match[2]) != match[1]:
                raise ValueError(f'Malformed, incomplete or changed checksum set: {name}')
            seen.add(match[2])
        if not seen:
            raise ValueError(f'Empty checksum set: {name}')
        covered.update(seen)
    catalog = json.loads(files['catalog.json'].read_text())
    entries = catalog['engines']
    if catalog.get('schema_version') != 1 or len(entries) != 4:
        raise ValueError('Publication requires all four catalog targets')
    binaries = set()
    for target, (host_os, host_arch, native_os) in TARGETS.items():
        matches = [e for e in entries if (e['host_os'], e['host_arch']) == (host_os, host_arch)]
        if len(matches) != 1:
            raise ValueError(f'Missing or duplicate catalog target: {target}')
        entry = matches[0]
        archive = entry['url'].rsplit('/', 1)[-1]
        expected_url = f'https://github.com/{repo}/releases/download/{tag}/{archive}'
        if (entry['url'] != expected_url or archive not in files or
                not archive.startswith(f'sdk-repo-{SDK_PREFIXES[target]}-emulator-') or not archive.endswith('.zip') or
                any(part in archive for part in ('-debug-', '-symbols-')) or
                entry.get('executable') != 'emulator/emulator' + ('.exe' if host_os == 'windows' else '') or
                entry['sha256'] != hashes[archive] or entry['size'] != files[archive].stat().st_size):
            raise ValueError(f'Catalog does not match the immutable main-release SDK: {target}')
        names = [archive, f'provenance-{target}.json', f'manifest-{target}.xml',
                 f'sdk-verification-{target}.json']
        if not set(names) <= covered or f'SHA256SUMS-{target}' not in files:
            raise ValueError(f'Native verification/source metadata are missing from checksums: {target}')
        origin = json.loads(files[names[1]].read_text())
        report = json.loads(files[names[3]].read_text())
        if (origin.get('target') != target or origin.get('upstream_tests') != 'passed' or origin.get('recipe_commit') != commit or
                report.get('status') != 'passed' or report.get('recipe_commit') != commit or
                report.get('target') != target or report.get('archive') != archive or
                report.get('host_os') != native_os or report.get('host_arch') != host_arch or
                report.get('exit_code') != 0 or report.get('sha256') != hashes[archive] or
                report.get('size') != entry['size'] or report.get('sdk_version') != entry['version']):
            raise ValueError(f'Native SDK verification/provenance mismatch: {target}')
        with zipfile.ZipFile(files[archive]) as zipped:
            properties = dict(line.split('=', 1) for line in
                              zipped.read('emulator/source.properties').decode().splitlines() if '=' in line)
            if (json.loads(zipped.read('emulator/hub-provenance.json')) != origin or
                    zipped.read('emulator/hub-source-manifest.xml') != files[names[2]].read_bytes() or
                    properties['Pkg.Revision'].strip() != entry['version']):
                raise ValueError(f'Embedded source metadata mismatch: {target}')
        binaries.add(archive)
    if len(binaries) != 4 or {name for name in files if name.startswith('sdk-repo-')} != binaries:
        raise ValueError('Expected exactly four runtime SDK archives, without build-only archives')
    if set(files) - covered - {'catalog.json', 'SHA256SUMS'} - {
            name for name in files if name.startswith('SHA256SUMS-')}:
        raise ValueError('Supporting files are missing from the producing artifacts checksums')
    checksum = dist / 'SHA256SUMS'
    checksum.write_text(''.join(f'{hashes[name]}  {name}\n' for name in sorted(files)
                               if name != checksum.name), encoding='utf-8', newline='\n')
    files[checksum.name] = checksum
    hashes[checksum.name] = digest(checksum)
    support_tag = tag + '-support'
    main_url = f'https://github.com/{repo}/releases/tag/{tag}'
    support_url = f'https://github.com/{repo}/releases/tag/{support_tag}'
    main_notes = (f'Google Android Emulator runtime SDKs for Linux x86_64, Windows x86_64, '
                  f'macOS Intel and macOS Apple Silicon.\n\n'
                  f'[Source, checksums, manifests and verification records]({support_url}) '
                  f'are published in the matching companion release. Download the SDK for your host; '
                  f'platform-tools/ADB come separately from Google.\n\n'
                  f'All four source builds and native packaged executable checks passed. '
                  f'Hardware-accelerated guest boot is a separate validation; consult the accompanying records.\n')
    support_notes = (f'Source and supporting records for the [four runtime SDK downloads]({main_url}).\n\n'
                     f'This companion release is not a latest application release. '
                     f'Its `SHA256SUMS` covers files across both releases; download the four SDKs '
                     f'from the linked main release into the same directory before checking the complete set. '
                     f'The catalog URLs continue to point to the main release.\n\n' +
                     files['SOURCE_OFFER.md'].read_text())
    assets = {name: {'path': str(files[name].resolve()), 'size': files[name].stat().st_size,
                     'sha256': hashes[name]} for name in sorted(files)}
    return {'tag': tag, 'support_tag': support_tag, 'repo': repo, 'commit': commit,
            'main_assets': sorted(binaries), 'support_assets': sorted(files.keys() - binaries),
            'main_notes': main_notes, 'support_notes': support_notes, 'assets': assets}


class GitHub:
    def __init__(self, repo):
        self.repo = repo

    def api(self, endpoint, method='GET', payload=None):
        command = ['gh', 'api', '--method', method, f'repos/{self.repo}/{endpoint}']
        if payload is not None:
            command += ['--input', '-']
        return json.loads(subprocess.check_output(command, input=json.dumps(payload) if payload is not None else None,
                                                 text=True))

    def verify_tag(self, tag, commit, required):
        # Matching-refs distinguishes an absent optional support tag from transport errors.
        refs = self.api('git/matching-refs/tags/' + quote(tag, safe=''))
        refs = [ref for ref in refs if ref['ref'] == 'refs/tags/' + tag]
        if not refs:
            if required:
                raise ValueError(f'Binary tag must already exist: {tag}')
            return
        obj = refs[0]['object']
        for _ in range(8):
            if obj['type'] != 'tag':
                break
            obj = self.api('git/tags/' + obj['sha'])['object']
        if obj['type'] != 'commit' or obj['sha'] != commit:
            raise ValueError(f'Release tag points to a different recipe: {tag}')

    def find(self, tag):
        pages = json.loads(subprocess.check_output(
            ['gh', 'api', f'repos/{self.repo}/releases?per_page=100', '--paginate', '--slurp'], text=True))
        return next((release for page in pages for release in page if release['tag_name'] == tag), None)

    def upload(self, tag, paths):
        subprocess.run(['gh', 'release', 'upload', tag, '--repo', self.repo, *paths], check=True)


def verify_assets(release, names, expected, allow_missing=False):
    assets = {asset['name']: asset for asset in release['assets']}
    if len(assets) != len(release['assets']) or assets.keys() - set(names):
        raise ValueError(f'Unexpected release assets in {release["tag_name"]}; nothing will be overwritten')
    for name, asset in assets.items():
        wanted = expected[name]
        if (asset['state'] != 'uploaded' or asset['size'] != wanted['size'] or
                asset.get('digest') != 'sha256:' + wanted['sha256']):
            raise ValueError(f'Existing release asset differs from verified bytes: {name}')
    missing = set(names) - assets.keys()
    if missing and not allow_missing:
        raise ValueError(f'Incomplete published release: {release["tag_name"]}')
    return sorted(missing)


def publish(plan, github):
    github.verify_tag(plan['tag'], plan['commit'], required=True)
    github.verify_tag(plan['support_tag'], plan['commit'], required=False)
    for kind in ('support', 'main'):
        tag = plan['support_tag'] if kind == 'support' else plan['tag']
        names = plan[kind + '_assets']
        release = github.find(tag)
        if release is None:
            release = github.api('releases', 'POST', {
                'tag_name': tag, 'target_commitish': plan['commit'], 'draft': True, 'prerelease': True,
                'make_latest': 'false', 'name': ('Source and verification — ' if kind == 'support'
                                               else 'Android Emulator — ') + plan['tag'],
                'body': plan[kind + '_notes'],
            })
        if release['draft'] and release.get('target_commitish') != plan['commit']:
            raise ValueError(f'Existing draft uses a different recipe target: {tag}')
        missing = verify_assets(release, names, plan['assets'], allow_missing=release['draft'])
        if missing:
            github.upload(tag, [plan['assets'][name]['path'] for name in missing])
        release = github.api(f'releases/{release["id"]}')
        verify_assets(release, names, plan['assets'])
        if release['draft']:
            release = github.api(f'releases/{release["id"]}', 'PATCH', {
                'draft': False, 'prerelease': True, 'make_latest': 'false', 'body': plan[kind + '_notes'],
            })
        release = github.api(f'releases/{release["id"]}')
        verify_assets(release, names, plan['assets'])
        if release['draft']:
            raise ValueError(f'Release was not made public: {tag}')
        github.verify_tag(tag, plan['commit'], required=True)
        print(f'Published and verified {tag}: {len(names)} assets', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--publish', action='store_true', help='Upload and publish; otherwise validate locally only')
    args = parser.parse_args()
    plan = prepare(args.dist, args.tag, args.repo, args.commit)
    print(json.dumps({key: plan[key] for key in ('tag', 'support_tag', 'main_assets', 'support_assets')}, indent=2))
    if args.publish:
        publish(plan, GitHub(args.repo))


if __name__ == '__main__':
    main()
