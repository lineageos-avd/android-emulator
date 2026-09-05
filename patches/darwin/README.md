# Installed macOS SDK discovery

The public emulator build script parsed `xcodebuild -showsdks` with a 10.x-specific
expression and assumed the full Xcode directory layout. This patch uses an explicit
installed `EMULATOR_MACOS_SDK` or `xcrun --show-sdk-path`, validates SDKSettings.plist,
and reads its real version. Both Command Line Tools and full Xcode are supported.

The physical Mac driver prefers its installed SDK 14.5. Disposable CI machines
select an installed 14.5/15.1/15.0 SDK before removing unused SDK bundles. No fake
Xcode version, fabricated SDK, or global setting change is made on a user's Mac.
