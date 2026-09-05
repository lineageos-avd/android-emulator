# Android Emulator for Emulator Hub

Build recipes for the open-source Google Android Emulator, pinned to the public
`emu-36-1-release` manifest `9b25cad8e44cf99246a5ffd579f1c21122865ab5` and QEMU
`9f0811e72acfc46edc39d3d0baedd796f7d03309`. The engine stays upstream-compatible;
Emulator Hub uses its existing authenticated local gRPC controller and ADB.

## Build

Use a dedicated directory on a case-sensitive filesystem with at least 100 GB free.
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
python3 scripts/windows-helpers-source.py --source ../engine-source --dist dist
```

## Automation and artifacts

`build.yml` runs four independent platform builds on pinned manifest updates, tags or manual dispatch. Linux
uses a trusted self-hosted runner labeled `emulator-linux` with Nix and 150 GB disk.
The other targets use GitHub-hosted machines; repositories are fetched shallowly.
Automatic `engine-*` tag releases require all four builds to complete.
CI on pull requests validates the manifest and scripts without executing untrusted
changes on the Lab machine. Native preview packages remain unsigned/not notarized;
hardware acceleration is a separate smoke-test requirement before a stable release.

Every published target requires its compiled archive, upstream test passes,
provenance, notices and corresponding source archive. Imported `source-*` previews
can publish completed targets incrementally, with their actual per-target recipe
commits; unavailable targets are omitted from the catalog. The schema is:

```json
{"schema_version":1,"engines":[{"host_os":"linux","host_arch":"x86_64","version":"35.3.8","url":"HTTPS_RELEASE_ASSET","size":123,"sha256":"HEX","executable":"emulator/emulator"}]}
```

The stable catalog endpoint is
`https://raw.githubusercontent.com/lineageos-avd/android-emulator/main/catalog.json`.
The version is the actual SDK version, independent of the manifest branch or release tag.
Platform tools/ADB come separately from Google and are not bundled here.

The first Linux SDK's ELF version requirements were scanned with `readelf`: the
highest required GLIBC symbol version is **2.27**, with no external GLIBCXX/CXXABI
version requirements. The release includes the per-file report. This is an ABI
requirement inspection, not hardware validation on every older distribution.
Emulator Hub's separate desktop package has its own glibc 2.35 minimum. NixOS
users can launch downloaded SDK tools through Hub's supplied FHS runtime.

See [SOURCE_OFFER.md](SOURCE_OFFER.md) for source availability and licensing and
[Google's build documentation](https://android.googlesource.com/platform/external/qemu/+/emu-36-1-release/android/docs/DEVELOPMENT.md)
for upstream design and toolchain details.

## Guarded local Mac fallback

`scripts/local-macos.py` builds both Mac targets serially with four compiler jobs.
Pass a dedicated case-sensitive APFS volume as `--workspace` and a path on its
physical backing filesystem as `--backing-store`. The process stops only its own
child builds if the physical disk falls below 20 GiB free or the build volume falls
below 3 GiB. It records progress in `build-status.json`. Intel tests run through
Rosetta on Apple Silicon; install Rosetta before starting. Packaged intermediate build directories are removed before the
next architecture to limit disk usage (`--keep-build-dirs` retains them). An interrupted source
sync is resumed when the script runs again. The existing user emulator is untouched.
Use `--target darwin-x86_64 --skip-sync` to resume only an interrupted Intel build
from an already verified source checkout. The same disk guard remains active.
Cross-target unit tests run through Rosetta, while hardware acceleration is
validated separately on matching physical hardware.

For networks where Google Git is slow, set `EMULATOR_AOSP_MIRROR` to an HTTPS AOSP
Git mirror, for example `https://mirrors.tuna.tsinghua.edu.cn/git/AOSP`. This changes
only the current sync process's Git transport: all project SHA pins stay unchanged,
mirror concurrency is capped at four, and missing objects retry the Google origin.
No global Git configuration is modified.

The pinned Google system-image fixture repository is in the optional
`integration-images` manifest group (`scripts/sync.py --integration-images`). It is
used by the separate upstream end-to-end boot suite, not the CMake build or CTest
unit suite. The auxiliary VNC end-to-end runner ZIP is not packaged; CTest and
acceleration checks remain enabled. The default still includes the unit-test data in `common/testdata`.
Hub/LineageOS boot tests use the separately published LineageOS image releases.
Including Google's full fixture set increases disk requirements to at least 150 GB.

Mac Vulkan unit fixtures use the SDK's own loader with ANGLE+SwiftShader for a
consistent headless software backend. Other tests run without loader-path changes
so dyld/Crashpad checks keep their normal environment. All test cases still run;
normal SDK users select their own runtime GPU backend.
