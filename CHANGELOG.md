# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Remote (`gs://`) raw and calibration **input folders** in
  `generate_standardized_cal_mapping`, detected by URL scheme. Remote raw files
  are scanned one at a time (each downloaded to local scratch, read for channel
  config, then the local copy deleted before the next — the deep readers stay
  strictly local); a remote calibration folder is bulk-localized for the parse.
  New `gcs` extra (`pip install aa-si-calibration[gcs]`) provides fsspec/gcsfs;
  new `aa_si_calibration._storage` helper module.
- `process_raw_file` (single-file public entry point) and `_config_sort_key`,
  factored out of `process_raw_folder` (which is unchanged for local callers
  and gained an optional pre-resolved `raw_files` argument).
- Optional filename-datetime filtering (`file_time_start` / `file_time_end`)
  on `generate_standardized_cal_mapping`, matching the datetime encoded in each
  raw file's name; out-of-window remote files are never downloaded.
- Initial project structure from NOAA Fisheries AA-SI Python template

### Changed
- Nothing yet

### Deprecated
- Nothing yet

### Removed
- Nothing yet

### Fixed
- `file_time_start` / `file_time_end` filtering missed raw files that start
  before the window but record into it, because only each file's own name
  stamp (its recording *start*) was compared against the window.
  `_storage.filter_paths_by_file_time` now keeps a file when its span (own
  stamp → next file's stamp) overlaps the window; the chronologically last
  file has no inferred end and still uses the own-stamp rule. Matches the
  same fix in `aa_si_utils.data_retrieval`.

### Security
- Nothing yet

## [0.1.0] - YYYY-MM-DD

### Added
- Initial release
- Basic package structure with src layout
- Development tooling (pytest, black, pylint, pre-commit)

<!--
=============================================================================
CHANGELOG GUIDELINES
=============================================================================

When adding entries, use the following categories:
- Added: for new features
- Changed: for changes in existing functionality
- Deprecated: for soon-to-be removed features
- Removed: for now removed features
- Fixed: for any bug fixes
- Security: in case of vulnerabilities

Each release should have a version number and date in the format:
## [X.Y.Z] - YYYY-MM-DD

Link definitions should be added at the bottom (optional)
