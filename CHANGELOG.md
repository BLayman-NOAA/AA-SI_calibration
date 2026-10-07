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
- Averaging calibration candidates. A conflict in `calibration_choices` can be
  answered with a list of candidate keys, and the interactive prompt accepts
  `1,2`. The candidates are averaged into a new single-channel file keyed
  `<dates>__<frequency>__average-<digest>` with `is_averaged` set, and the
  conflict's channels are mapped to it. Gain, Sa correction and equivalent beam
  angle are averaged in the linear domain, and FM records over the union of
  their frequency points as pyEchoLab does. Calibrations that differ in
  hardware, settings or sphere are refused. New `averaging` module,
  `average_calibration_records` and `average_candidates`.
- `build_calibration_mapping` returns `single_channel_data`, which includes any
  averaged record, and takes `record_author` for it.
- The provenance report marks averaged calibration files, lists what went into
  each with the gain and Sa correction spread between them, and counts
  `calibration_files_averaged`.
- Schema field `is_averaged`.

### Changed
- `calibration_date` is a list of strings in the schema, one entry per
  calibration behind the record. Single-channel files and `override_channels`
  carrying the old single string are still accepted and read as a one-item
  list, and a one-date key, file name or conflict id is unchanged.
- `DEFAULT_TOLERANCES` moved to `constants`; `mapping_algorithm` still
  exports it.

### Deprecated
- Nothing yet

### Removed
- Nothing yet

### Fixed
- `build_calibration_mapping` returned a mapping that named the rejected
  candidate. With `short_filenames`, it remapped keys that were already
  single-channel file names, renumbering `config-N` over whatever survived a
  conflict, so choosing `config-2` came back as `config-1`. The archive call
  accepted that mapping, because `config-1` was still in `single_channel_data`.
  `channel_mapping.yaml` on disk was right; only the returned dictionaries were
  wrong. The returned keys are now remapped only when they are not file names,
  the same check `save_mapping_files` already made.
- Resolving a conflict removed a calibration file that a raw channel outside
  the conflict had matched on its own, leaving `channel_mapping.yaml` naming a
  key with no file. A rejected key is now kept while any channel is still
  mapped to it.
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
