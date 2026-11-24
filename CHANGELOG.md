# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-11-24

### Fixed
- CI: update GitHub Actions versions in the test workflow.

### Changed
- README: Safety and Supported versions are now their own sections.

## [0.1.0] - 2026-11-24

### Added
- `report`: rebuild the Home Assistant Assist system prompt from a `.storage` folder (read-only) and count tokens per entity, area and domain, with a `fits` / `tight` / `over` verdict, `--reserve`, `--margin`, `--format table|json|md` and `--fail-over`.
- `suggest`: pick entities to hide with rules (diagnostic, no area, duplicate name, long names, non-default domain or device class) plus `--keep` / `--drop`, written as a plan file; identical input gives identical bytes.
- `apply` and `undo`: dry-run by default; `--yes` checks the Home Assistant version, refuses a plan whose entities changed (exit code 5), writes the undo file first, applies, and re-reads to confirm.
- `demo`: a clearly labelled mock practice run against a bundled sample house and an in-process fake Home Assistant server.
- Prompt profiles for Home Assistant 2025.5 and later; 2026.11 is verified byte for byte against output of a real Home Assistant 2026.11.3, the others are reported as "unverified profile".
- Token counters: `approx` (no dependencies) and `tekken` (optional extra, offline).
- English and Korean output (`--lang`, `ASSIST_BUDGET_LANG`, `LC_ALL` / `LC_MESSAGES` / `LANG`).

### Known issues
- The demo's last step counts 210 registry entries (including disabled ones) while step 1 counts 207 prompt entities; both are correct.
- The comment line at the top of a plan file is always English, also with `--lang ko`.
- `--lang` must be placed before the subcommand.
