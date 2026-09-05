#!/usr/bin/env python3
"""Replace old CRT files in a private, unpublished SDK artifact and record provenance."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile
import zipfile

from windows_runtime import CRT_DLLS, MINIMUM_CRT, audit, version_bytes

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sdk_verifier', ROOT / 'scripts/verify-sdk.py')
sdk_verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sdk_verifier)
LICENSE_URL = 'https://visualstudio.microsoft.com/license-terms/vs2022-ga-proenterprise/'
REDIST_URL = 'https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution'


def find_redist():
    vswhere = Path(os.environ['ProgramFiles(x86)']) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    installation = Path(subprocess.check_output([
        str(vswhere), '-latest', '-products', '*', '-version', '[17.0,18.0)',
        '-property', 'installationPath'], text=True).strip())
    candidates = []
    for path in (installation / 'VC/Redist/MSVC').glob('*/x64/Microsoft.VC*.CRT'):
        if all((path / name).is_file() for name in CRT_DLLS):
            versions = [version_bytes((path / name).read_bytes()) for name in CRT_DLLS]
            if min(version[:2] for version in versions) >= MINIMUM_CRT:
                candidates.append((min(versions), path))
    if not candidates:
        raise ValueError('Visual Studio 2022 has no complete x64 redistributable >= 14.34')
    return min(candidates)[1]


def signatures(directory):
    command = r'''
$ErrorActionPreference = 'Stop'
$names = $env:HUB_CRT_NAMES | ConvertFrom-Json
$records = foreach ($name in $names) {
    $path = Join-Path $env:HUB_CRT_DIRECTORY $name
    $signature = Get-AuthenticodeSignature -LiteralPath $path
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
        throw "Invalid Microsoft Authenticode signature: $name"
    }
    @{ name = $name; status = [string] $signature.Status;
       signer = $signature.SignerCertificate.Subject; thumbprint = $signature.SignerCertificate.Thumbprint }
}
ConvertTo-Json -InputObject @($records) -Depth 4
'''
    return json.loads(subprocess.check_output(
        ['pwsh', '-NoProfile', '-NonInteractive', '-Command', command], text=True,
        env=os.environ | {'HUB_CRT_DIRECTORY': str(directory), 'HUB_CRT_NAMES': json.dumps(CRT_DLLS)}))


def repackage(args):
    if platform.system() != 'Windows' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise ValueError('Runtime packaging requires a native Windows x64 host')
    if not re.fullmatch(r'[a-f0-9]{40}', args.packaging_commit):
        raise ValueError('packaging_commit must be a full recipe commit SHA')
    dist = args.dist.resolve()
    archives = [path for path in dist.glob('sdk-repo-windows-emulator-*.zip')
                if '-symbols-' not in path.name and '-debug-' not in path.name]
    if len(archives) != 1:
        raise ValueError('Expected one unpublished Windows SDK archive')
    archive = archives[0]
    provenance_path = dist / 'provenance-windows-x86_64.json'
    manifest = dist / 'manifest-windows-x86_64.xml'
    checksums_path = dist / 'SHA256SUMS-windows-x86_64'
    checksums = sdk_verifier.read_checksums(checksums_path)
    for path in (archive, provenance_path, manifest):
        if checksums.get(path.name) != sdk_verifier.digest(path):
            raise ValueError(f'Input artifact checksum mismatch: {path.name}')
    provenance = json.loads(provenance_path.read_text(encoding='utf-8'))
    if provenance['recipe_commit'] != args.expected_recipe_commit or provenance['upstream_tests'] != 'passed':
        raise ValueError('Input artifact does not match the tested producing build')
    if 'packaging_commit' in provenance:
        raise ValueError('Artifact already has packaging provenance; use the original producing artifact')
    redist = (args.redist or find_redist()).resolve()
    if (redist.parent.name.lower() != 'x64'
            or not redist.name.startswith('Microsoft.VC') or not redist.name.endswith('.CRT')
            or 'redist' not in [part.lower() for part in redist.parts]):
        raise ValueError('Select the x64 CRT directory under Visual Studio VC/Redist')
    signed = signatures(redist)
    replacements = {name: (redist / name).read_bytes() for name in CRT_DLLS}
    for name, data in replacements.items():
        if version_bytes(data)[:2] < MINIMUM_CRT:
            raise ValueError(f'Redistribution file is older than MSVC 14.34: {name}')
    changes = []
    notice = ('Microsoft Visual C++ Runtime, Copyright Microsoft Corporation.\n'
              'The runtime DLLs in this SDK are unmodified files from the licensed '
              'Visual Studio 2022 VC/Redist directory. They retain Microsoft licensing.\n'
              f'License terms: {LICENSE_URL}\nDistributable code list: {REDIST_URL}\n'
              'Exact versions, hashes, and Microsoft signatures are recorded in hub-provenance.json.\n')
    with tempfile.TemporaryDirectory(prefix='hub-crt-package-', dir=dist.parent) as temporary:
        temp = Path(temporary)
        sdk_verifier.extract_sdk(archive, temp / 'sdk')
        sdk = temp / 'sdk/emulator'
        embedded = json.loads((sdk / 'hub-provenance.json').read_text(encoding='utf-8'))
        if embedded != provenance or (sdk / 'hub-source-manifest.xml').read_bytes() != manifest.read_bytes():
            raise ValueError('Input SDK metadata differs from its external provenance')
        for name, data in replacements.items():
            targets = [path for path in sdk.rglob('*') if path.name.lower() == name]
            if not targets:
                targets = [sdk / name]
            for target in targets:
                old = target.read_bytes() if target.exists() else None
                changes.append({'file': target.relative_to(sdk).as_posix(),
                                'old_sha256': hashlib.sha256(old).hexdigest() if old else None,
                                'old_version': '.'.join(map(str, version_bytes(old))) if old else None,
                                'sha256': hashlib.sha256(data).hexdigest(),
                                'version': '.'.join(map(str, version_bytes(data)))})
                target.write_bytes(data)
        dependency_report = audit(sdk)
        provenance.update(packaging_commit=args.packaging_commit, windows_runtime={
            'minimum_toolset': '14.34', 'source_directory': str(redist),
            'license_url': LICENSE_URL, 'redistribution_url': REDIST_URL,
            'original_upstream_tested_archive_sha256': sdk_verifier.digest(archive),
            'files': changes, 'authenticode': signed,
            'validation': 'PE import/export closure checked; native version result is a separate verification artifact',
            'upstream_tests_rerun_after_runtime_replacement': False,
        })
        provenance_data = (json.dumps(provenance, indent=2) + '\n').encode()
        (sdk / 'hub-provenance.json').write_bytes(provenance_data)
        (sdk / 'NOTICE.MSVC-RUNTIME.txt').write_text(notice, encoding='utf-8')
        packaged = temp / archive.name
        with zipfile.ZipFile(packaged, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
            for path in sorted((temp / 'sdk').rglob('*')):
                if path.is_file():
                    zipped.write(path, path.relative_to(temp / 'sdk').as_posix())
        packaged.replace(archive)
        provenance_path.write_bytes(provenance_data)
        (dist / 'NOTICE.MSVC-RUNTIME.txt').write_text(notice, encoding='utf-8')
        (dist / 'windows-dependencies.json').write_text(json.dumps(dependency_report, indent=2) + '\n', encoding='utf-8')
        with checksums_path.open('w', encoding='utf-8') as output:
            for path in sorted(dist.iterdir()):
                if path.is_file() and not path.name.startswith('SHA256SUMS'):
                    output.write(f'{sdk_verifier.digest(path)}  {path.name}\n')
    return {'archive': archive.name, 'sha256': sdk_verifier.digest(archive),
            'recipe_commit': provenance['recipe_commit'], 'packaging_commit': args.packaging_commit,
            'crt_directory': str(redist), 'crt_files': len(changes)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, required=True, help='Private downloaded artifact directory; updated in place')
    parser.add_argument('--redist', type=Path)
    parser.add_argument('--packaging-commit', required=True)
    parser.add_argument('--expected-recipe-commit', required=True)
    args = parser.parse_args()
    print(json.dumps(repackage(args), indent=2))


if __name__ == '__main__':
    main()
