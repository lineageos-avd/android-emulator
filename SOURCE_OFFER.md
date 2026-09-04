# Source and licenses

This repository contains build recipes for Google Android Emulator. The engine is
licensed under its component licenses, including GPL-2.0-or-later for QEMU.
The upstream distribution's NOTICE and license files are retained in each binary.
Hub build recipes are Apache-2.0. Google SDK binary packages are not mirrored here.

Every published binary release includes `manifest-<target>.xml`, provenance,
SHA256SUMS, and an `engine-corresponding-source.tar.gz` archive (split into numbered
parts if larger than GitHub's per-asset limit). Concatenate `.part*` in lexical order
before extraction. The archive contains all checked-out source projects at their
exact revisions and these build scripts. The upstream source-and-patch archives in
`prebuilts/android-emulator-build/archive` are also included, covering bundled
libraries such as Qt and FFmpeg. Prebuilt compilers and binary libraries are
restored from the recorded AOSP manifest. Their upstream license files remain in their
repositories and resulting distribution notices.

To build from source, follow README.md. Source archives and manifest remain publicly
available alongside their corresponding binaries; release publication fails unless
all four binary targets and the corresponding-source job succeed. This is an
independent project, not a Google or LineageOS official release.
