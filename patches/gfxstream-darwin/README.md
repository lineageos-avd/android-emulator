# ASTC target selection when cross compiling

The parent QEMU build chooses ASTC decoder ISA from `ANDROID_TARGET_TAG`, while
gfxstream previously linked a decoder using the build host CPU. An Intel build on
Apple Silicon therefore referenced a nonexistent ARM decoder target and failed
license closure validation. This patch uses the same target tag (or the normal
CMake target processor for standalone gfxstream), preserving the actual Apache-2.0
decoder and all license validation. It changes dependency selection, not licenses.
