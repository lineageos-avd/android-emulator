# Android Emulator for Emulator Hub

Build recipes for the open-source Google Android Emulator, pinned to the public
`emu-36-1-release` manifest `9b25cad8e44cf99246a5ffd579f1c21122865ab5` and QEMU
`9f0811e72acfc46edc39d3d0baedd796f7d03309`. The engine stays upstream-compatible;
Emulator Hub uses its existing authenticated local gRPC controller and ADB.

## Build

Use a dedicated directory on a case-sensitive filesystem with at least 150 GB free.
Linux requires x86_64 and macOS requires Xcode with its command-line SDK installed.
Windows uses VS2022 C++/ATL/MFC, a Windows SDK, Python 3.11+, Git symlink support
and a short source path such as `C:\emu-source`. Administrator/developer-mode
symlink privileges are needed during source checkout. Nix provides the Linux and
macOS environment; Windows compiles natively with MSVC (Nix development via WSL).

```sh
nix develop
python3 scripts/sync.py --source ../engine-source --revision main
# Linux/NixOS: enter an FHS shell so upstream ELF prebuilts work.
nix run . -- -c 'python3 scripts/build.py --source ../engine-source --target linux-x86_64 --out ../engine-out --dist dist'
# macOS Apple Silicon, from a nix develop shell (Intel: darwin-x86_64):
python3 scripts/build.py --source ../engine-source --target darwin-aarch64 --out ../engine-out --dist dist
```

Windows runs the same Python commands with `--target windows-x86_64`, from a VS2022
x64 developer shell. `scripts/build.py` calls Google's `android/rebuild.sh` or
`rebuild.cmd`; upstream CMake/Ninja compiles and tests the engine and emits its
standard SDK-compatible ZIP. Crash upload is disabled. `--skip-tests` is only for
local diagnostics and cannot produce a published catalog entry.

To export corresponding source after checkout:

```sh
python3 scripts/source-archive.py --source ../engine-source --dist dist
```

## Automation and artifacts

`build.yml` runs four independent platform builds on tags or manual dispatch. Linux
uses a trusted self-hosted runner labeled `emulator-linux` with Nix and 150 GB disk.
The other targets use GitHub-hosted machines; repositories are fetched shallowly.
The run fails rather than publishing partial builds or fabricated downloads.
CI on pull requests validates the manifest and scripts without executing untrusted
changes on the Lab machine. Native preview packages remain unsigned/not notarized;
hardware acceleration is a separate smoke-test requirement before a stable release.

Release publication requires the four compiled archives, upstream test passes,
provenance, notices and corresponding source archive. `catalog.json` in each
complete Release has this schema:

```json
{"schema_version":1,"engines":[{"host_os":"linux","host_arch":"x86_64","version":"TAG","url":"HTTPS_RELEASE_ASSET","size":123,"sha256":"HEX","executable":"emulator/emulator"}]}
```

The stable catalog endpoint is
`https://raw.githubusercontent.com/lineageos-avd/android-emulator/main/catalog.json`.
`main/catalog.json` starts empty intentionally until the first complete source build.
Platform tools/ADB come separately from Google and are not bundled here.

See [SOURCE_OFFER.md](SOURCE_OFFER.md) for source availability and licensing and
[Google's build documentation](https://android.googlesource.com/platform/external/qemu/+/emu-36-1-release/android/docs/DEVELOPMENT.md)
for upstream design and toolchain details.
