# Windows filesystem helper source supplement

This supplement supplies the original Cygwin source packages for the twelve unchanged 32-bit PE files installed under `emulator/bin64/` in the Windows x86_64 Google Emulator SDK. It accompanies source engine 35.3.8 in the [source release](https://github.com/lineageos-avd/android-emulator/releases/tag/source-35.3.8-preview.1).

| SDK files | Actual Cygwin source package | Base source archive | Supplement |
| --- | --- | --- | --- |
| e2fsck.exe, resize2fs.exe, tune2fs.exe | e2fsprogs 1.42.12-1 | Windows binaries only | Original source + 4 patches + recipe |
| cygcom_err-2.dll, cyge2p-2.dll, cygext2fs-2.dll | e2fsprogs 1.42.12-2 | Windows binaries only | Original source + 7 patches + recipe |
| cygwin1.dll | cygwin 2.0.4-1 | Windows binary and documentation | Original source + packaging patch + recipe |
| cygblkid-1.dll | util-linux 2.25.2-1 | Windows binary only | Original source + 8 patches + recipe |
| cyguuid-1.dll | util-linux 2.25.2-2 | Windows binary only | Original source + 8 patches + recipe |
| cyggcc_s-1.dll | gcc 4.9.3-1 | Windows binary only | Original source + 26 patches + recipe |
| cygiconv-2.dll | libiconv 1.14-3 | Upstream 1.14 source; no Cygwin recipe/patches | Original source + 4 patches + recipe |
| cygintl-8.dll | gettext 0.19.4-1 | Windows binary; base source is 0.19.1 | Original source + 4 patches + recipe |

Google's Windows packaging rule uses `common/e2fsprogs/windows-x86/sbin`. Its generic license URL refers to e2fsprogs 1.42.13; the Windows executable bytes instead match 1.42.12-1. The 1.42.13 archive and its two patches remain unchanged in the base source archive.

The fixed Google commits are QEMU `9f0811e72acfc46edc39d3d0baedd796f7d03309`, common prebuilts `5b8a22a34ac998df16d7e3347fe84fbc1fc15735`, and archive `9b0bdade8b09267282fb901d21219ab6af013c60`. The original [PACKAGES.TXT](https://android.googlesource.com/platform/prebuilts/android-emulator-build/archive/+/9b0bdade8b09267282fb901d21219ab6af013c60/PACKAGES.TXT) records their package origins.

Every SDK helper was compared byte-for-byte by SHA256 with its file inside Google's fixed binary package. Every binary package also matches the SHA512 in the preserved [2015-07-14 Cygwin setup.ini](http://ctm.crouchingtigerhiddenfruitbat.org/pub/cygwin/circa/2015/07/14/011012/setup.ini); that same index explicitly links each binary revision to its source archive. All eight downloaded source archives match those indexed sizes and SHA512 values. The historical mirror uses HTTP; no detached-index signature verification is claimed. The map retains both original SHA512 values and newly computed SHA256 values.

The source archive for Cygwin includes its original `cygwin.cygport`, which selects `cygwin-2_0_4-release`. The official [Cygwin Git tag](https://cygwin.com/cgit/newlib-cygwin/tag/?h=cygwin-2_0_4-release) resolves to commit `6261fb30a9780fae87d631c1da4d77efa43fe329` (tag object `5892a323e529c755e9ffa5b9e48348782ea1a477`), independently checked with `git ls-remote`.

`windows-helpers-corresponding-source-35.3.8.tar.gz` contains the eight original `-src.tar.xz` packages under `sources/`, copies of their original recipes and patches under `recipes/`, the full historical index and fixed Google provenance under `provenance/`, and preserved notices under `notices/`. Upstream license files remain inside the original source archives, including GCC's runtime exception, Cygwin/Newlib notices, and the package-specific COPYING files. No additional license terms are introduced.

To inspect a package, verify `SHA256SUMS`, extract its original `-src.tar.xz`, and read its `.cygport` and included patches. The preserved recipes describe the original Cygwin build and installation steps. A historical Cygwin toolchain and the recipe's build dependencies are needed to rebuild. This verifies source/package correspondence; these helpers were not rebuilt, and byte-for-byte rebuild reproducibility is not claimed. Existing SDK binaries and previously published release assets are unchanged.
