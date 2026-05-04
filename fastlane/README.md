fastlane documentation
----

# Installation

Make sure you have the latest version of the Xcode command line tools installed:

```sh
xcode-select --install
```

For _fastlane_ installation instructions, see [Installing _fastlane_](https://docs.fastlane.tools/#installing-fastlane)

# Available Actions

## iOS

### ios upload_metadata

```sh
[bundle exec] fastlane ios upload_metadata
```

Upload iOS metadata and screenshots to App Store Connect

### ios submit_for_review

```sh
[bundle exec] fastlane ios submit_for_review
```

Submit latest uploaded iOS build for App Review

----


## Android

### android upload_internal

```sh
[bundle exec] fastlane android upload_internal
```

Upload Android AAB to Google Play internal track

----


## Mac

### mac upload_testflight

```sh
[bundle exec] fastlane mac upload_testflight
```

Build and upload macOS App Store build to TestFlight

### mac publish_dmg

```sh
[bundle exec] fastlane mac publish_dmg
```

Build strict notarized DMG and publish it to say.waiwai.is

### mac upload_all

```sh
[bundle exec] fastlane mac upload_all
```

Upload macOS App Store build to TestFlight and publish direct DMG to web

### mac upload_metadata

```sh
[bundle exec] fastlane mac upload_metadata
```

Upload macOS metadata and screenshots to App Store Connect

----

This README.md is auto-generated and will be re-generated every time [_fastlane_](https://fastlane.tools) is run.

More information about _fastlane_ can be found on [fastlane.tools](https://fastlane.tools).

The documentation of _fastlane_ can be found on [docs.fastlane.tools](https://docs.fastlane.tools).
