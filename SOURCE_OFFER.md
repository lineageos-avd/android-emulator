# Source and licenses

This repository contains build recipes for Google Android Emulator. The engine is
licensed under its component licenses, including GPL-2.0-or-later for QEMU.
The upstream distribution's NOTICE and license files are retained in each binary.
Hub build recipes are Apache-2.0. Google SDK binary packages are not mirrored here.

Every main release `<tag>` contains exactly four runtime SDK ZIPs and links to a
public `<tag>-support` release. The support release links back to the main SDK
release and is published with `latest=false`. For the current preview, download
SDKs from [source-35.3.8-preview.1](https://github.com/lineageos-avd/android-emulator/releases/tag/source-35.3.8-preview.1)
and the corresponding source and records from
[source-35.3.8-preview.1-support](https://github.com/lineageos-avd/android-emulator/releases/tag/source-35.3.8-preview.1-support).

The support release contains `manifest-<target>.xml`, provenance, notices,
SHA256SUMS, native verification reports, the release catalog, and an
`engine-corresponding-source.tar.gz` archive (split into numbered parts if larger
than GitHub's per-asset limit). Concatenate `.part*` in lexical order before
extraction. The archive contains all checked-out source projects at their exact
revisions and these build scripts. `hub-build/recipes.bundle` preserves the recipe Git
history, so each target can be rebuilt at its recorded `recipe_commit` without
relying on the current default branch. The upstream source-and-patch archives in
`prebuilts/android-emulator-build/archive` are also included, covering bundled
libraries such as Qt and FFmpeg. Prebuilt compilers and binary libraries are
restored from the recorded AOSP manifest. Their upstream license files remain in their
repositories and resulting distribution notices.

Windows SDKs also include legacy Cygwin helpers. Their matching original source
packages, Cygport build recipes and patches are distributed in the separate
`windows-helpers-corresponding-source-35.3.8.tar.gz` supplement, with the source map,
notice and checksums in the paired support release. See
[the exact helper/source mapping](docs/windows-helpers-source.md).
`scripts/windows-helpers-source.py` verifies the source pins and original package
hashes before reproducing that supplement. Compatible Microsoft runtime packaging
is described in [Windows runtime provenance](docs/windows-runtime.md).

To build from source, follow README.md. The linked source archives and manifests
remain publicly available for their corresponding binaries. Automatic `engine-*`
tag releases require all four binary targets and the corresponding-source job to
succeed. The support release must be public and its uploaded assets validated
before the main SDK binaries are published. The public catalog is updated only
after both releases and their asset checks pass. Per-target recipe commits and
validation evidence are preserved, including the distinct recipe histories used
for imported previews. This is an independent project, not a Google or LineageOS
official release.
