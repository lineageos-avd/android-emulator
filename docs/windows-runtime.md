# Windows runtime packaging

The pinned emulator source includes Microsoft CRT 14.28.29914.0. The compatible
Clang 17 build uses MSVC 14.34 headers and libraries. Microsoft requires a runtime
at least as recent as the build tools, so Windows SDKs include an app-local runtime
from Visual Studio 2022's redistributable directory, selected at version 14.34 or
newer. The compiler toolset remains pinned to 14.34.

`scripts/setup-windows.ps1` exports the selected `EMULATOR_VC_REDIST_DIR` for the
reviewed CMake patch. This makes future upstream unit tests and distributions use
the selected runtime. `scripts/repackage-windows-runtime.py` can also update a
private, unpublished artifact from a completed build without recompiling it.
It verifies Microsoft's Authenticode signatures and records each replaced file's
old and new version and SHA256. `recipe_commit` continues to identify the original
build, and `packaging_commit` identifies the later packaging code. Embedded and
external provenance and SHA256 manifests are updated together. Published release
assets must never be replaced through this procedure.

The independent `Verify Windows SDK artifact` workflow accepts a completed build
run ID. It downloads only that run's successful Windows artifact, packages the
compatible runtime, checks PE import/export closure, and executes the extracted
`emulator.exe -version`. Its final artifact is named
`engine-windows-x86_64-verified`. An empty run ID performs runtime inspection only.
The report distinguishes unit tests run by the original build from packaging
checks. It does not claim to boot a Windows guest or exercise hardware acceleration.

The source offer for a repackaged SDK must include both recipe commits and all
packaging scripts. Runtime binaries remain unmodified Microsoft files, with their
license and redistribution sources recorded in `NOTICE.MSVC-RUNTIME.txt` and
`hub-provenance.json`.

Primary references:

- [Supported runtime versions](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170)
- [Visual Studio 2022 distributable code](https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution)
- [Visual Studio 2022 license terms](https://visualstudio.microsoft.com/license-terms/vs2022-ga-proenterprise/)
