The pinned AOSP engine uses Google `clang-r487747c` (Clang 17.0.2).
Recent Windows runners select MSVC 14.44 headers, which require Clang 19.
`scripts/setup-windows.ps1` installs MSVC 14.34 / Visual Studio 17.4 side by side.

The accompanying QEMU patch passes `EMULATOR_MSVC_TOOLSET` to the upstream
`vcvars64.bat` invocation and rejects a different effective toolset. This is
necessary because upstream recreates the environment after the Actions setup
step. It does not disable Microsoft's STL compiler checks or change ABI macros.

The patch applies to QEMU commit `9f0811e72acfc46edc39d3d0baedd796f7d03309`.
Its mixed line endings preserve the upstream Python file's CRLF source bytes.
Keep it in the corresponding-source archive and record its digest in build
provenance.

Primary references:
- [Microsoft component catalog](https://learn.microsoft.com/en-us/visualstudio/install/workload-component-id-vs-enterprise?view=visualstudio)
- [Selecting an MSVC toolset with vcvars](https://learn.microsoft.com/en-us/cpp/build/building-on-the-command-line?view=msvc-170)
- [Visual Studio installer command-line parameters](https://learn.microsoft.com/en-us/visualstudio/install/use-command-line-parameters-to-install-visual-studio?view=visualstudio)
