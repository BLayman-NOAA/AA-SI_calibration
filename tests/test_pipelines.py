# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""End-to-end pipeline integration tests.

These tests mirror the workflow demonstrated in the example notebooks:
- full_pipeline.ipynb        -> test_full_pipeline
- manual_pipeline.ipynb      -> test_manual_pipeline
- user_provided_cal_pipeline.ipynb -> test_user_provided_cal_pipeline

Each test runs against real example data from notebooks/example_data/ and
writes all outputs to pytest's tmp_path so nothing permanent is modified.

builtins.input is always monkeypatched to return "1" (first option).  Whether
conflicts actually arise depends on the dataset; the patch is a no-op when
there are no conflicts.

Mark: @pytest.mark.slow  — run with:  pytest -m slow
Skip slow tests with:          pytest -m "not slow"
"""

import yaml
import pytest

from aa_si_calibration import calibration as calibration_module
from aa_si_calibration.raw_reader_api import (
    process_raw_folder,
    save_yaml,
    extract_unique_channels,
)
from aa_si_calibration import manufacturer_file_parsers, standardized_file_lib
from aa_si_calibration.mapping_algorithm import (
    load_raw_configs,
    load_calibration_data_from_single_files,
    build_mapping,
    get_calibration,
    save_mapping_files,
    handle_unused_calibration_files,
    resolve_conflicts_interactive,
    check_required_calibration_params,
    verify_calibration_file_usage,
    build_mapping_from_raw_configs,
)
from aa_si_calibration.standardized_file_lib import (
    generate_calibration_templates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GLOBAL_PARAMS = {
    "cruise_id": "test_run",
    "record_author": "Test Suite",
}


class _DummyMappingResult:
    def __init__(self):
        self.mapping_dict = {"file.raw": {"channel-1": "cal-key-1"}}
        self.calibration_dict = {"cal-key-1": {"gain_correction": 1.0}}

    def print_summary(self):
        return None


def _patch_generate_standardized_cal_mapping(monkeypatch, tmp_path):
    captured = {}
    dummy_result = _DummyMappingResult()

    monkeypatch.setattr(
        calibration_module,
        "process_raw_folder",
        lambda *_args, **_kwargs: (
            [{"filename": "file.raw", "channels": [{"channel_id": "channel-1"}]}],
            {38000},
        ),
    )
    monkeypatch.setattr(calibration_module, "save_yaml", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        calibration_module.manufacturer_file_parsers,
        "extract_and_convert_calibration_params",
        lambda *_args, **_kwargs: (
            {"gain_correction": [1.0]},
            {"sound_speed": 1500.0},
            {"channel": ["channel-1"]},
            ".cal",
        ),
    )

    def _save_single_channel_files(*_args, global_params, **_kwargs):
        captured["global_params"] = global_params
        return 1, None, {"saved": True}

    monkeypatch.setattr(
        calibration_module.standardized_file_lib,
        "save_single_channel_files_from_params",
        _save_single_channel_files,
    )
    monkeypatch.setattr(
        calibration_module,
        "load_raw_configs",
        lambda *_args, **_kwargs: [{"filename": "file.raw"}],
    )
    monkeypatch.setattr(
        calibration_module,
        "load_calibration_data_from_single_files",
        lambda *_args, **_kwargs: {"channels": ["channel-1"]},
    )
    monkeypatch.setattr(
        calibration_module,
        "build_mapping",
        lambda *_args, **_kwargs: dummy_result,
    )
    monkeypatch.setattr(
        calibration_module,
        "handle_unused_calibration_files",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        calibration_module,
        "check_for_conflicts",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        calibration_module,
        "print_mapping_preview",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        calibration_module,
        "save_mapping_files",
        lambda *_args, **_kwargs: (
            tmp_path / "mapping.yaml",
            tmp_path / "calibration.yaml",
        ),
    )
    monkeypatch.setattr(
        calibration_module,
        "check_required_calibration_params",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        calibration_module,
        "verify_calibration_file_usage",
        lambda *_args, **_kwargs: [],
    )

    return captured, dummy_result


def _run_full_pipeline(raw_dir, cal_dir, dirs, monkeypatch):
    """Execute the full pipeline against a single dataset.

    Mirrors the cells in full_pipeline.ipynb.  Returns mapping_dict and
    calibration_dict for further assertions.
    """
    # Always respond "1" to any interactive conflict prompt.
    monkeypatch.setattr("builtins.input", lambda _: "1")

    # Step 1: extract raw configs
    file_configs, frequencies_set = process_raw_folder(raw_dir, verbose=False)
    assert file_configs, "process_raw_folder returned no file configs"

    raw_configs_path = dirs["raw_configs"] / "raw_file_configs.yaml"
    save_yaml(file_configs, raw_configs_path)
    assert raw_configs_path.exists()

    # Step 2: parse manufacturer calibration files and save single-channel files
    cal_params, env_params, other_params, _cal_file_type = (
        manufacturer_file_parsers.extract_and_convert_calibration_params(
            cal_dir,
            nc_frequencies=frequencies_set,
            output_logs_folder=dirs["logs"],
        )
    )
    assert cal_params, "No calibration parameters extracted"

    saved_count, _, _standardized_dict = (
        standardized_file_lib.save_single_channel_files_from_params(
            cal_params,
            env_params,
            other_params,
            _GLOBAL_PARAMS,
            output_dir=dirs["single_cal"],
            short_filenames=True,
        )
    )
    assert saved_count > 0, "No single-channel calibration files were saved"

    # Step 3: load raw configs + calibration data, build mapping
    raw_file_configs = load_raw_configs(raw_configs_path)
    calibration_data = load_calibration_data_from_single_files(dirs["single_cal"])

    result = build_mapping(raw_file_configs, calibration_data, verbose=False)

    handle_unused_calibration_files(
        result,
        calibration_data,
        dirs["single_cal"],
        keep_unused=True,
        unused_dir=dirs["unused"],
    )

    resolve_conflicts_interactive(
        result,
        dirs["single_cal"],
        keep_unused=True,
        unused_dir=dirs["unused"],
    )

    # After resolution there must be no remaining multiple-match conflicts.
    assert result.multiple_matches == [], (
        f"Unresolved conflicts remain: {result.multiple_matches}"
    )

    # Every raw channel must appear in the mapping.
    all_raw_channel_ids = {
        channel["channel_id"]
        for fc in file_configs
        for channel in fc.get("channels", [])
    }
    mapped_channel_ids = {
        channel_id
        for channels in result.mapping_dict.values()
        for channel_id in channels.keys()
    }
    assert all_raw_channel_ids == mapped_channel_ids, (
        f"Some channels were not mapped.\n"
        f"  Expected: {sorted(all_raw_channel_ids)}\n"
        f"  Got:      {sorted(mapped_channel_ids)}"
    )

    # Save mapping files
    mapping_path, calibration_path = save_mapping_files(
        result, dirs["mapping"], short_filenames=True
    )
    assert mapping_path.exists(), "Mapping YAML was not written"
    assert calibration_path.exists(), "Calibration YAML was not written"

    # Both output files must be loadable as valid YAML
    with open(mapping_path) as f:
        mapping_dict = yaml.safe_load(f)
    with open(calibration_path) as f:
        calibration_dict = yaml.safe_load(f)

    assert mapping_dict, "Loaded mapping_dict is empty"
    assert calibration_dict, "Loaded calibration_dict is empty"

    # get_calibration() must return data for every mapped channel
    for filename, channels in mapping_dict.items():
        for channel_id in channels:
            cal_data = get_calibration(
                filename, channel_id, mapping_dict, calibration_dict
            )
            assert cal_data is not None, (
                f"get_calibration returned None for {filename} -> {channel_id}"
            )

    return mapping_dict, calibration_dict


def test_generate_standardized_cal_mapping_accepts_explicit_metadata(tmp_path, monkeypatch):
    captured, dummy_result = _patch_generate_standardized_cal_mapping(monkeypatch, tmp_path)

    result = calibration_module.generate_standardized_cal_mapping(
        raw_input_folder=tmp_path / "raw",
        cal_input_folder=tmp_path / "cal",
        output_base=tmp_path / "out",
        cruise_id="HB1603",
        record_author="Tester",
        short_filenames=False,
        verbose=False,
    )

    assert captured["global_params"] == {
        "cruise_id": "HB1603",
        "record_author": "Tester",
    }
    assert result["mapping_dict"] == dummy_result.mapping_dict
    assert result["calibration_dict"] == dummy_result.calibration_dict


def test_generate_standardized_cal_mapping_accepts_global_params_fallback(tmp_path, monkeypatch):
    captured, _dummy_result = _patch_generate_standardized_cal_mapping(monkeypatch, tmp_path)

    calibration_module.generate_standardized_cal_mapping(
        raw_input_folder=tmp_path / "raw",
        cal_input_folder=tmp_path / "cal",
        output_base=tmp_path / "out",
        global_params={"cruise_id": "HB1603", "record_author": "Tester"},
        short_filenames=False,
        verbose=False,
    )

    assert captured["global_params"] == {
        "cruise_id": "HB1603",
        "record_author": "Tester",
    }


def test_generate_standardized_cal_mapping_rejects_conflicting_metadata(tmp_path):
    with pytest.raises(ValueError, match="cruise_id does not match"):
        calibration_module.generate_standardized_cal_mapping(
            raw_input_folder=tmp_path / "raw",
            cal_input_folder=tmp_path / "cal",
            output_base=tmp_path / "out",
            global_params={"cruise_id": "OLD", "record_author": "Tester"},
            cruise_id="NEW",
            record_author="Tester",
            verbose=False,
        )


# ---------------------------------------------------------------------------
# Full pipeline — parameterized over all four datasets
# ---------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.parametrize("dataset", ["ek60", "ek80_fm", "hb2407"])
def test_full_pipeline(dataset, request, tmp_output_dir, monkeypatch):
    """Full pipeline (manufacturer cal files -> mapping) for each dataset.

    Mirrors full_pipeline.ipynb.  Parameterized so EK60, EK80 FM, and HB2407
    data are all exercised.  Conflict resolution is always handled via
    ``resolve_conflicts_interactive`` with input monkeypatched to "1".

    Note: EK80 CW is not included because the example data only provides
    FM-mode calibration files (ek80_cal_file_input_folder contains
    "FM_settings" XML files with pulse_form="1"), which do not match the
    CW raw channels (pulse_form="0").  The ek80_fm case covers EK80 testing.
    """
    raw_dirs = {
        "ek60":    request.getfixturevalue("ek60_raw_dir"),
        "ek80_fm": request.getfixturevalue("ek80_fm_raw_dir"),
        "hb2407":  request.getfixturevalue("hb2407_raw_dir"),
    }
    cal_dirs = {
        "ek60":    request.getfixturevalue("ek60_cal_dir"),
        "ek80_fm": request.getfixturevalue("ek80_fm_cal_dir"),
        "hb2407":  request.getfixturevalue("hb2407_cal_dir"),
    }

    _run_full_pipeline(raw_dirs[dataset], cal_dirs[dataset], tmp_output_dir, monkeypatch)


# ---------------------------------------------------------------------------
# Manual pipeline (EK60)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_manual_pipeline(ek60_raw_dir, tmp_output_dir):
    """Manual pipeline: raw -> unique channels -> templates -> mapping.

    Mirrors manual_pipeline.ipynb.
    """
    calibration_date = "2026-02-18"

    # Step 1: extract raw configs
    file_configs, _frequencies_set = process_raw_folder(ek60_raw_dir, verbose=False)
    assert file_configs

    # Step 2: identify unique channel configurations
    unique_channels = extract_unique_channels(file_configs, calibration_date)
    assert unique_channels, "No unique channels found"

    # Step 3: generate calibration templates (one file per unique channel)
    templates = generate_calibration_templates(
        unique_channels,
        calibration_date=calibration_date,
        record_author="Test Suite",
        output_dir=tmp_output_dir["single_cal"],
        short_filenames=True,
    )

    template_files = list(tmp_output_dir["single_cal"].glob("*.yaml")) + \
                     list(tmp_output_dir["single_cal"].glob("*.yml"))
    assert len(template_files) == len(unique_channels), (
        f"Expected {len(unique_channels)} template files, "
        f"found {len(template_files)}"
    )

    # Step 4: generate mapping from raw configs (deterministic, no algorithm needed)
    mapping_dict = build_mapping_from_raw_configs(file_configs, calibration_date)
    assert mapping_dict, "build_mapping_from_raw_configs returned empty dict"

    # Every raw file must appear in the mapping
    raw_filenames = {fc["filename"] for fc in file_configs}
    mapped_filenames = set(mapping_dict.keys())
    assert raw_filenames == mapped_filenames


# ---------------------------------------------------------------------------
# User-provided calibration pipeline (EK60 pre-made YAMLs)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_user_provided_cal_pipeline(
    ek60_raw_dir, ek60_single_channel_dir, tmp_output_dir
):
    """User-provided pipeline: pre-made single-channel YAMLs + raw -> mapping.

    Mirrors user_provided_cal_pipeline.ipynb.
    """
    # Step 1: extract raw configs
    file_configs, _frequencies_set = process_raw_folder(ek60_raw_dir, verbose=False)
    raw_configs_path = tmp_output_dir["raw_configs"] / "raw_file_configs.yaml"
    save_yaml(file_configs, raw_configs_path)

    raw_file_configs = load_raw_configs(raw_configs_path)

    # Step 2: load pre-made calibration data and build mapping
    calibration_data = load_calibration_data_from_single_files(
        ek60_single_channel_dir
    )
    assert calibration_data["channels"], "No calibration channels loaded"

    result = build_mapping(raw_file_configs, calibration_data, verbose=False)

    # No conflicts expected with the curated example data
    assert result.multiple_matches == [], (
        "Unexpected conflicts in user-provided pipeline example data"
    )

    # All raw channels must be matched
    assert result.unmatched_channels == [], (
        f"Unmatched channels: {result.unmatched_channels}"
    )

    # get_calibration() must return data for every mapped channel
    for filename, channels in result.mapping_dict.items():
        for channel_id in channels:
            cal_data = get_calibration(
                filename,
                channel_id,
                result.mapping_dict,
                result.calibration_dict,
            )
            assert cal_data is not None, (
                f"get_calibration returned None for {filename} -> {channel_id}"
            )


# ---------------------------------------------------------------------------
# Round-trip test: save -> reload -> map -> retrieve
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_round_trip(ek60_raw_dir, ek60_cal_dir, tmp_output_dir, monkeypatch):
    """Round-trip: save single-channel files, reload, map, retrieve calibration.

    Ensures the serialisation / deserialisation cycle is lossless enough for
    the mapping algorithm to reconstruct the correct channel-to-calibration
    assignments.
    """
    monkeypatch.setattr("builtins.input", lambda _: "1")

    # Generate single-channel files from source cal data
    file_configs, frequencies_set = process_raw_folder(ek60_raw_dir, verbose=False)

    raw_configs_path = tmp_output_dir["raw_configs"] / "raw_file_configs.yaml"
    save_yaml(file_configs, raw_configs_path)

    cal_params, env_params, other_params, _cal_file_type = (
        manufacturer_file_parsers.extract_and_convert_calibration_params(
            ek60_cal_dir,
            nc_frequencies=frequencies_set,
            output_logs_folder=tmp_output_dir["logs"],
        )
    )
    saved_count, _, original_standardized = (
        standardized_file_lib.save_single_channel_files_from_params(
            cal_params,
            env_params,
            other_params,
            _GLOBAL_PARAMS,
            output_dir=tmp_output_dir["single_cal"],
            short_filenames=True,
        )
    )
    assert saved_count > 0

    # Reload from disk
    raw_file_configs = load_raw_configs(raw_configs_path)
    calibration_data = load_calibration_data_from_single_files(
        tmp_output_dir["single_cal"]
    )

    result = build_mapping(raw_file_configs, calibration_data, verbose=False)
    resolve_conflicts_interactive(
        result, tmp_output_dir["single_cal"],
        keep_unused=True, unused_dir=tmp_output_dir["unused"],
    )

    assert result.multiple_matches == []
    assert result.unmatched_channels == []

    # Every mapped channel must return calibration data
    for filename, channels in result.mapping_dict.items():
        for channel_id in channels:
            cal = get_calibration(
                filename, channel_id, result.mapping_dict, result.calibration_dict
            )
            assert cal is not None
            # Core calibration fields must be present (not None) after a
            # round-trip with real manufacturer files
            assert cal.get("gain_correction") is not None, (
                f"gain_correction missing for {filename} -> {channel_id}"
            )
            assert cal.get("sa_correction") is not None, (
                f"sa_correction missing for {filename} -> {channel_id}"
            )
