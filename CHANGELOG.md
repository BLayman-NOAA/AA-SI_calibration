# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- The pipeline is callable as separate steps: `read_raw_file_config` (one raw
  file), `record_raw_file_configs` (sort and save the survey's configurations),
  `standardize_calibration_files`, and `build_calibration_mapping`.
  `generate_standardized_cal_mapping` is unchanged and is now a thin sequence
  over them. Splitting them lets a caller cache, resume, or re-run each stage
  on its own.
- `standardization.fingerprint.json`, recording which manufacturer files
  produced the single-channel files. Step 2 previously skipped whenever the
  output directory was non-empty, so a parse interrupted part way through left
  a partial set that the next run treated as complete. The sidecar is written
  only after every channel file lands. It answers to the manufacturer folder,
  so deleting a single-channel file still does not bring it back, which the
  `conflict_resolution="error"` workflow depends on; emptying the folder
  re-parses.
- `conflict_resolution="interactive"` now works inside a recipe step. The
  conflict options go to the terminal rather than only the captured run log,
  and a run with no interactive input fails before any calibration file is
  moved. Standalone and notebook callers are unaffected: with no recipe step in
  play the prompt is the builtin `input()`.

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
- Filename-time filtering pulled in a stale raw file from before a gap between
  survey legs. Inferring a file's end from the next file's start stamp assumes
  recording ran continuously, so the last file before a gap looked like it
  recorded for the whole gap and was kept as if it straddled the window start.
  `_storage.filter_paths_by_file_time` now reads the real last ping from the one
  file whose verdict depends on that inference, via the new `raw_file_times`
  module (stdlib-only, deliberately mirrored from `aa_si_utils.raw_file_times`
  rather than shared, per this package's no-dependency-on-`aa_si_utils` rule).
  This also settles the chronologically last file, whose end the names cannot
  bound at all. At most one file per call is opened and only its datagram
  headers are read; for remote folders that is a couple of range requests, not
  a download. Pass `verify_boundary=False` to keep the filter name-only.
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
