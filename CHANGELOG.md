# Changelog

All notable changes to AutoRewarder are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Added source-based macOS support using pywebview's native Cocoa backend.
- Added macOS runtime storage under `~/Library/Application Support/AutoRewarder`.
- Added conditional PyObjC dependencies for macOS installations.

### Documentation

- Documented macOS source setup, runtime data paths, and platform limitations.
- Documented that OS-level autostart remains available only on Windows and Linux.

### Limitations

- No pre-built macOS release archive is currently published.
