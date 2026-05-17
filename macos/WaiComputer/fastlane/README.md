fastlane documentation
----

# Installation

Make sure you have the latest version of the Xcode command line tools installed:

```sh
xcode-select --install
```

For _fastlane_ installation instructions, see [Installing _fastlane_](https://docs.fastlane.tools/#installing-fastlane)

# Available Actions

## Mac

### mac testflight_upload

```sh
[bundle exec] fastlane mac testflight_upload
```

Build and upload to TestFlight

### mac publish_dmg

```sh
[bundle exec] fastlane mac publish_dmg
```

Build strict notarized DMG and publish it to wai.computer

### mac upload_all

```sh
[bundle exec] fastlane mac upload_all
```

Upload macOS App Store build to TestFlight and publish direct DMG to web

----

This README.md is auto-generated and will be re-generated every time [_fastlane_](https://fastlane.tools) is run.

More information about _fastlane_ can be found on [fastlane.tools](https://fastlane.tools).

The documentation of _fastlane_ can be found on [docs.fastlane.tools](https://docs.fastlane.tools).
