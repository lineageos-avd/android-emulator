"""Small synthetic artifacts exercise release routing without network or builds."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('publish_release', ROOT / 'scripts/publish-release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
COMMIT = 'a' * 40
TAG = 'engine-fixture'
REPO = 'example/emulator'


def checksum(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(dist):
    entries = []
    for target, (host_os, arch, native_os) in release.TARGETS.items():
        sdk = dist / f'sdk-repo-{release.SDK_PREFIXES[target]}-emulator-1.zip'
        origin = {'target': target, 'recipe_commit': COMMIT, 'upstream_tests': 'passed', 'sdk_version': '35.3.8'}
        (dist / f'provenance-{target}.json').write_text(json.dumps(origin))
        manifest = b'<manifest />\n'
        (dist / f'manifest-{target}.xml').write_bytes(manifest)
        with zipfile.ZipFile(sdk, 'w') as archive:
            archive.writestr('emulator/source.properties', 'Pkg.Revision=35.3.8\n')
            archive.writestr('emulator/hub-provenance.json', json.dumps(origin))
            archive.writestr('emulator/hub-source-manifest.xml', manifest)
        report = {'status': 'passed', 'target': target, 'recipe_commit': COMMIT,
                  'host_os': native_os, 'host_arch': arch, 'exit_code': 0,
                  'sdk_version': '35.3.8', 'archive': sdk.name,
                  'sha256': checksum(sdk), 'size': sdk.stat().st_size}
        (dist / f'sdk-verification-{target}.json').write_text(json.dumps(report))
        offer = 'SOURCE_OFFER.md' if target == 'linux-x86_64' else f'SOURCE_OFFER-{target}.md'
        (dist / offer).write_bytes(b'Source offer\n' if target != 'windows-x86_64' else b'Source offer\r\n')
        names = [sdk.name, f'provenance-{target}.json', f'manifest-{target}.xml',
                 f'sdk-verification-{target}.json', offer]
        (dist / f'SHA256SUMS-{target}').write_text(''.join(f'{checksum(dist / name)}  {name}\n' for name in names))
        entries.append({'host_os': host_os, 'host_arch': arch, 'version': '35.3.8',
                        'url': f'https://github.com/{REPO}/releases/download/{TAG}/{sdk.name}',
                        'size': sdk.stat().st_size, 'sha256': checksum(sdk),
                        'executable': 'emulator/emulator' + ('.exe' if host_os == 'windows' else '')})
    extra = ['engine-corresponding-source.tar.gz', 'windows-helpers-corresponding-source-35.3.8.tar.gz',
             'windows-helpers-source-map.json', 'windows-helpers-source-notice.md',
             'windows-dependencies.json', 'NOTICE.MSVC-RUNTIME.txt']
    for name in extra:
        (dist / name).write_text('Synthetic fixture only\n')
    (dist / 'SHA256SUMS-source').write_text(f'{checksum(dist / extra[0])}  {extra[0]}\n')
    (dist / 'SHA256SUMS-windows-helpers').write_text(
        ''.join(f'{checksum(dist / name)}  {name}\n' for name in extra[1:]))
    (dist / 'catalog.json').write_text(json.dumps({'schema_version': 1, 'engines': entries}))


class FakeGitHub:
    def __init__(self, plan):
        self.plan = plan
        self.releases = {}
        self.events = []
        self.corrupt_support = False

    def verify_tag(self, tag, commit, required):
        self.events.append(('tag', tag, commit, required))

    def find(self, tag):
        return copy.deepcopy(next((r for r in self.releases.values() if r['tag_name'] == tag), None))

    def api(self, endpoint, method='GET', payload=None):
        if endpoint == 'releases' and method == 'POST':
            item = dict(payload, id=len(self.releases) + 1, assets=[])
            self.releases[item['id']] = item
            self.events.append(('create', item['tag_name'], item['make_latest']))
        else:
            item = self.releases[int(endpoint.split('/')[-1])]
            if method == 'PATCH':
                item.update(payload)
                self.events.append(('publish', item['tag_name'], item['make_latest']))
        result = copy.deepcopy(item)
        if self.corrupt_support and result['tag_name'].endswith('-support') and result['assets']:
            result['assets'][0]['digest'] = 'sha256:' + '0' * 64
        return result

    def upload(self, tag, paths):
        item = next(r for r in self.releases.values() if r['tag_name'] == tag)
        for path in paths:
            name = Path(path).name
            expected = self.plan['assets'][name]
            item['assets'].append({'name': name, 'state': 'uploaded', 'size': expected['size'],
                                   'digest': 'sha256:' + expected['sha256']})
        self.events.append(('upload', tag, len(paths)))


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.dist = Path(self.temporary.name)
        fixture(self.dist)

    def prepare(self):
        return release.prepare(self.dist, TAG, REPO, COMMIT)

    def test_exact_partition_and_repeatable_checksums(self):
        plan = self.prepare()
        self.assertEqual(4, len(plan['main_assets']))
        self.assertTrue(all(name.startswith('sdk-repo-') for name in plan['main_assets']))
        self.assertIn('catalog.json', plan['support_assets'])
        self.assertIn('SHA256SUMS', plan['support_assets'])
        self.assertNotIn('catalog.json', plan['main_assets'])
        self.assertIn(TAG + '-support', plan['main_notes'])
        self.assertIn('/tag/' + TAG, plan['support_notes'])
        before = (self.dist / 'SHA256SUMS').read_bytes()
        self.prepare()
        self.assertEqual(before, (self.dist / 'SHA256SUMS').read_bytes())
        self.assertNotIn(b'\r', before)

    def test_support_published_before_main_and_retry_does_not_upload_again(self):
        plan = self.prepare()
        github = FakeGitHub(plan)
        release.publish(plan, github)
        events = [(event[0], event[1]) for event in github.events]
        self.assertLess(events.index(('publish', TAG + '-support')), events.index(('create', TAG)))
        self.assertEqual('false', github.releases[1]['make_latest'])
        uploads = sum(event[0] == 'upload' for event in github.events)
        release.publish(plan, github)
        self.assertEqual(uploads, sum(event[0] == 'upload' for event in github.events))

    def test_changed_remote_support_stops_before_main_creation(self):
        plan = self.prepare()
        github = FakeGitHub(plan)
        github.corrupt_support = True
        with self.assertRaisesRegex(ValueError, 'differs'):
            release.publish(plan, github)
        self.assertEqual(1, len(github.releases))
        self.assertTrue(github.releases[1]['draft'])

    def test_changed_source_missing_native_evidence_and_wrong_catalog_are_rejected(self):
        (self.dist / 'engine-corresponding-source.tar.gz').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.prepare()
        fixture(self.dist)
        (self.dist / 'sdk-verification-darwin-x86_64.json').unlink()
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.prepare()
        fixture(self.dist)
        catalog_path = self.dist / 'catalog.json'
        catalog = json.loads(catalog_path.read_text())
        catalog['engines'][0]['url'] = catalog['engines'][0]['url'].replace(TAG + '/', TAG + '-support/')
        catalog_path.write_text(json.dumps(catalog))
        with self.assertRaisesRegex(ValueError, 'main-release SDK'):
            self.prepare()

    def test_partial_catalog_and_extra_sdk_are_rejected(self):
        catalog_path = self.dist / 'catalog.json'
        catalog = json.loads(catalog_path.read_text())
        catalog['engines'].pop()
        catalog_path.write_text(json.dumps(catalog))
        with self.assertRaisesRegex(ValueError, 'four catalog'):
            self.prepare()
        fixture(self.dist)
        (self.dist / 'sdk-repo-darwin-emulator-debug-1.zip').write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'exactly four'):
            self.prepare()

    def test_support_tag_cannot_recurse(self):
        with self.assertRaisesRegex(ValueError, 'without the -support'):
            release.prepare(self.dist, TAG + '-support', REPO, COMMIT)

    def test_staging_preserves_windows_offer_bytes_without_merge_collision(self):
        source = self.dist / 'SOURCE_OFFER.md'
        source.write_bytes(b'Source offer\r\n')
        out = self.dist / 'staged'
        subprocess.run(['python3', str(ROOT / 'scripts/stage-release.py'), '--dist', str(self.dist),
                        '--out', str(out), '--target', 'windows-x86_64'], check=True, capture_output=True)
        self.assertEqual(source.read_bytes(), (out / 'SOURCE_OFFER-windows-x86_64.md').read_bytes())
        self.assertFalse((out / 'SOURCE_OFFER.md').exists())


if __name__ == '__main__':
    unittest.main()
