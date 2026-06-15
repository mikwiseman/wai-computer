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

## Mac

### mac publish_dmg

```sh
[bundle exec] fastlane mac publish_dmg
```

Build strict notarized DMG and publish it to wai.computer

### mac upload_all

```sh
[bundle exec] fastlane mac upload_all
```

Build strict notarized DMG and publish it to wai.computer (alias for publish_dmg)

----

This README.md is auto-generated and will be re-generated every time [_fastlane_](https://fastlane.tools) is run.

More information about _fastlane_ can be found on [fastlane.tools](https://fastlane.tools).

The documentation of _fastlane_ can be found on [docs.fastlane.tools](https://docs.fastlane.tools).
