#!/usr/bin/env python3
"""Sync immutable AOSP project commits using Google's own repo tool."""
import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REPO_VERSION = 'v2.66.1'
REPO_LAUNCHER = 'https://gerrit.googlesource.com/git-repo/+/b85886fa9f5b4e2189cc5b2f40bd0a80459d4c77/repo?format=TEXT'
REPO_SHA256 = '1211b57b57e4122a9c546295a59b37d24068f1164d0e87bef096d5323c413e4f'
REPO_URL = 'https://github.com/GerritCodeReview/git-repo.git'


def run(*command, **kwargs):
    subprocess.run([str(value) for value in command], check=True, **kwargs)


def recover_interrupted_fetches(source, manifest, mirror, jobs, integration_images):
    """Repo drops depth after an interrupted first fetch without a shallow file.

    Restore the pinned shallow snapshot only for incomplete managed repositories,
    without changing work trees, removing objects, or pruning any user's commits.
    """
    repairs = []
    host_group = 'platform-' + platform.system().lower()
    for project in ET.parse(manifest).getroot().findall('project'):
        groups = set(project.attrib.get('groups', '').split(','))
        if 'notdefault' in groups and host_group not in groups and not (integration_images and 'integration-images' in groups):
            continue
        path = project.attrib.get('path', project.attrib['name'])
        gitdir = source / '.repo/projects' / (path + '.git')
        if not gitdir.is_dir():
            continue
        revision = project.attrib['revision']
        check = subprocess.run(['git', '--git-dir=' + str(gitdir), 'rev-list', '--objects', '--missing=print', '--no-walk', revision], capture_output=True, text=True)
        if check.returncode != 0 or any(line.startswith('?') for line in check.stdout.splitlines()):
            repairs.append((gitdir, project.attrib['name'], revision))

    def repair(item):
        gitdir, project, revision = item
        print(f'Restoring interrupted shallow snapshot: {project}', flush=True)
        command = ['git', '--git-dir=' + str(gitdir), 'fetch', '--refetch', '--depth=1', '--no-tags']
        if mirror:
            try:
                run(*command, mirror.rstrip('/') + '/' + project, revision)
                return
            except subprocess.CalledProcessError:
                print(f'Mirror repair unavailable for {project}; using Google', flush=True)
        run(*command, 'https://android.googlesource.com/' + project, revision)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(jobs, 4)) as pool:
        for result in pool.map(repair, repairs):
            pass


def sync_projects(command, source, manifest, env, direct_env, mirror, jobs, integration_images):
    """Resume transient transport failures without changing any commit pin."""
    transport, transport_env = mirror, env
    for attempt in range(3):
        try:
            recover_interrupted_fetches(source, manifest, transport, jobs, integration_images)
            run(*command, cwd=source, env=transport_env)
            return
        except subprocess.CalledProcessError:
            if attempt == 2:
                raise
            print(f'Source sync attempt {attempt + 1} failed; repairing incomplete snapshots and retrying Google ({attempt + 2}/3)', flush=True)
            transport, transport_env = None, direct_env
            time.sleep(5 * (attempt + 1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=8)
    parser.add_argument('--revision', default='main', help='Recipe manifest commit/tag to synchronize')
    parser.add_argument('--manifest-url', default='https://github.com/lineageos-avd/android-emulator.git')
    parser.add_argument('--aosp-mirror', default=os.environ.get('EMULATOR_AOSP_MIRROR'), help='Optional HTTPS AOSP Git mirror; immutable commits are unchanged and failures retry Google')
    parser.add_argument('--integration-images', action='store_true', help='Also fetch the optional Google end-to-end integration image fixtures')
    args = parser.parse_args()
    if args.aosp_mirror and not args.aosp_mirror.startswith('https://'):
        parser.error('--aosp-mirror must be an HTTPS URL')
    if not shutil.which('gpg'):
        raise SystemExit('GnuPG is required to verify the signed repo release; enter nix develop first')
    source = args.source.resolve()
    source.mkdir(parents=True, exist_ok=True)
    # Prevent accidentally mixing this build with a user's existing Android tree.
    marker = source / '.emulator-hub-engine'
    if (source / '.repo').exists() and not marker.exists():
        raise SystemExit('Refusing unmanaged repo checkout: choose a new source directory')
    marker.write_text('lineageos-avd/android-emulator\n')
    tools = source / '.hub-tools'
    tools.mkdir(exist_ok=True)
    launcher = tools / 'repo'
    if not launcher.exists() or hashlib.sha256(launcher.read_bytes()).hexdigest() != REPO_SHA256:
        with urllib.request.urlopen(REPO_LAUNCHER, timeout=120) as response:
            data = base64.b64decode(response.read())
        if hashlib.sha256(data).hexdigest() != REPO_SHA256:
            raise SystemExit('Repo launcher checksum mismatch')
        launcher.write_bytes(data)
    # The bootstrap loader verifies the explicitly selected, signed repo release.
    repo = [sys.executable, str(launcher)]
    env = os.environ.copy()
    env.setdefault('GIT_AUTHOR_NAME', 'Emulator Hub builder')
    env.setdefault('GIT_AUTHOR_EMAIL', 'build@users.noreply.github.com')
    env.setdefault('GIT_COMMITTER_NAME', env['GIT_AUTHOR_NAME'])
    env.setdefault('GIT_COMMITTER_EMAIL', env['GIT_AUTHOR_EMAIL'])
    extra_groups = ['--groups=default,integration-images'] if args.integration_images else ['--groups=default']
    run(*repo, 'init', *extra_groups, '-u', args.manifest_url, '-b', args.revision,
        '--depth=1', '--repo-rev=' + REPO_VERSION, '--repo-url=' + REPO_URL, '--no-clone-bundle',
        '--platform=' + platform.system().lower(), cwd=source, env=env)
    repo_revision = subprocess.check_output(['git', '-C', str(source / '.repo/repo'), 'rev-parse', 'HEAD'], text=True).strip()
    if repo_revision != 'b85886fa9f5b4e2189cc5b2f40bd0a80459d4c77':
        raise SystemExit(f'Repo tool revision mismatch: {repo_revision}')
    direct_env = env.copy()
    if args.aosp_mirror:
        index = int(env.get('GIT_CONFIG_COUNT', '0'))
        env[f'GIT_CONFIG_KEY_{index}'] = f'url.{args.aosp_mirror.rstrip("/")}/.insteadOf'
        env[f'GIT_CONFIG_VALUE_{index}'] = 'https://android.googlesource.com/'
        env['GIT_CONFIG_COUNT'] = str(index + 1)
        print(f'Fetching exact AOSP commits through {args.aosp_mirror}', flush=True)
    # Let active independent fetches finish before retrying a transport error.
    # Failing early can leave a large snapshot half fetched on ephemeral runners.
    sync_command = [*repo, 'sync', '-c', '--no-clone-bundle', '--no-tags',
                    '-j', str(min(args.jobs, 4) if args.aosp_mirror else args.jobs)]
    sync_projects(sync_command, source, source / '.repo/manifests/default.xml', env,
                  direct_env, args.aosp_mirror, args.jobs, args.integration_images)
    run(*repo, 'manifest', '-r', '-o', source / 'resolved-manifest.xml', cwd=source, env=env)
    lock = json.loads((ROOT / 'upstream.json').read_text())
    actual = subprocess.check_output(['git', '-C', str(source / 'external/qemu'), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != lock['qemu_revision']:
        raise SystemExit(f'QEMU revision mismatch: expected {lock["qemu_revision"]}, found {actual}')
    print(f'Synchronized verified QEMU {actual} in {source}')


if __name__ == '__main__':
    main()
