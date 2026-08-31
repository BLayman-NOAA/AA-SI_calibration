# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""The calibration pipeline as separate steps.

Pins the behaviour a caller depends on: the standardization reuse guard
survives an interrupted parse, does not undo a deliberate single-file deletion
(the conflict workflow), and still re-parses when the folder is emptied.
"""

import json

import pytest
import yaml

from aa_si_calibration import calibration as calibration_module


@pytest.fixture
def stub_steps(monkeypatch):
    """Patch out the real parsers, counting the expensive calls.

    Patched as module attributes of ``calibration``, which is where the steps
    resolve these names from.
    """
    calls = {"parse": 0}

    def _parse(*_args, **_kwargs):
        calls["parse"] += 1
        return (
            {"gain_correction": [1.0]},
            {"sound_speed": 1500.0},
            {"channel": ["ch-1"]},
            ".cal",
        )

    def _save_single_channel_files(*_args, **kwargs):
        # Two channels, so "deleted one of several" is distinguishable from
        # "emptied the folder"; they mean different things to the guard.
        out_dir = kwargs["output_dir"]
        (out_dir / "ch-1.yaml").write_text("channel_id: ch-1\n", encoding="utf-8")
        (out_dir / "ch-2.yaml").write_text("channel_id: ch-2\n", encoding="utf-8")
        return 2, None, [{"channel_id": "ch-1"}, {"channel_id": "ch-2"}]

    monkeypatch.setattr(
        calibration_module.manufacturer_file_parsers,
        "extract_and_convert_calibration_params",
        _parse,
    )
    monkeypatch.setattr(
        calibration_module.standardized_file_lib,
        "save_single_channel_files_from_params",
        _save_single_channel_files,
    )
    return calls


def _cal_folder(tmp_path, *names):
    folder = tmp_path / "cal"
    folder.mkdir(exist_ok=True)
    for name in names:
        (folder / name).write_text("cal", encoding="utf-8")
    return folder


# ---------------------------------------------------------------------------
# record_raw_file_configs
# ---------------------------------------------------------------------------


def test_record_sorts_and_reports_frequencies(tmp_path):
    configs = [
        {"filename": "b.raw", "metadata_start_time": "2024-01-02T00:00:00",
         "channels": [{"channel_id": "c", "frequency": 120000}]},
        {"filename": "a.raw", "metadata_start_time": "2024-01-01T00:00:00",
         "channels": [{"channel_id": "c", "frequency": 38000}]},
    ]
    out = calibration_module.record_raw_file_configs(configs, tmp_path / "out", verbose=False)

    assert [c["filename"] for c in out["raw_file_configs"]] == ["a.raw", "b.raw"]
    assert out["frequencies"] == [38000, 120000]

    saved = yaml.safe_load(
        (tmp_path / "out" / "raw_file_configs" / "raw_file_configs.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert [c["filename"] for c in saved] == ["a.raw", "b.raw"]


def test_record_drops_unreadable_files(tmp_path):
    """A file the scanner could not identify comes back as None."""
    configs = [
        None,
        {"filename": "a.raw", "metadata_start_time": "2024-01-01T00:00:00",
         "channels": [{"channel_id": "c", "frequency": 38000}]},
        None,
    ]
    out = calibration_module.record_raw_file_configs(configs, tmp_path / "out", verbose=False)
    assert [c["filename"] for c in out["raw_file_configs"]] == ["a.raw"]


def test_record_rejects_an_empty_scan(tmp_path):
    with pytest.raises(ValueError, match="No raw file configurations"):
        calibration_module.record_raw_file_configs([None], tmp_path / "out", verbose=False)


# ---------------------------------------------------------------------------
# standardize_calibration_files: the reuse guard
# ---------------------------------------------------------------------------


def _standardize(tmp_path, cal_dir, **kwargs):
    return calibration_module.standardize_calibration_files(
        cal_dir,
        tmp_path / "out",
        frequencies=[38000],
        cruise_id="TEST",
        record_author="Tester",
        verbose=False,
        **kwargs,
    )


def test_unchanged_manufacturer_files_skip_the_parse(tmp_path, stub_steps):
    cal_dir = _cal_folder(tmp_path, "a.cal")
    assert _standardize(tmp_path, cal_dir)["skipped"] is False
    assert _standardize(tmp_path, cal_dir)["skipped"] is True
    assert stub_steps["parse"] == 1


def test_changed_manufacturer_files_re_parse(tmp_path, stub_steps):
    cal_dir = _cal_folder(tmp_path, "a.cal")
    _standardize(tmp_path, cal_dir)
    (cal_dir / "b.cal").write_text("cal", encoding="utf-8")
    assert _standardize(tmp_path, cal_dir)["skipped"] is False
    assert stub_steps["parse"] == 2


def test_interrupted_parse_is_not_mistaken_for_a_complete_one(tmp_path, stub_steps):
    """A partial write leaves no sidecar, so the next run redoes it."""
    cal_dir = _cal_folder(tmp_path, "a.cal")
    _standardize(tmp_path, cal_dir)
    # Simulate the crash: the channel files landed, the sidecar never did.
    (tmp_path / "out" / "standardization.fingerprint.json").unlink()

    assert _standardize(tmp_path, cal_dir)["skipped"] is False
    assert stub_steps["parse"] == 2


def test_deleted_single_channel_file_is_not_regenerated(tmp_path, stub_steps):
    """The conflict workflow: delete the unwanted file, re-run, rest survive."""
    cal_dir = _cal_folder(tmp_path, "a.cal")
    _standardize(tmp_path, cal_dir)
    single_cal = tmp_path / "out" / "single_channel_calibration_files"
    (single_cal / "ch-1.yaml").unlink()

    assert _standardize(tmp_path, cal_dir)["skipped"] is True
    assert not (single_cal / "ch-1.yaml").exists()
    assert (single_cal / "ch-2.yaml").exists()
    assert stub_steps["parse"] == 1


def test_emptying_the_folder_rebuilds_it(tmp_path, stub_steps):
    """Removing every channel file re-parses, unlike removing one."""
    cal_dir = _cal_folder(tmp_path, "a.cal")
    _standardize(tmp_path, cal_dir)
    single_cal = tmp_path / "out" / "single_channel_calibration_files"
    for f in single_cal.glob("*.yaml"):
        f.unlink()

    assert _standardize(tmp_path, cal_dir)["skipped"] is False
    assert stub_steps["parse"] == 2
    assert len(list(single_cal.glob("*.yaml"))) == 2


def test_overwrite_forces_a_re_parse(tmp_path, stub_steps):
    cal_dir = _cal_folder(tmp_path, "a.cal")
    _standardize(tmp_path, cal_dir)
    assert _standardize(tmp_path, cal_dir, overwrite=True)["skipped"] is False
    assert stub_steps["parse"] == 2


def test_standardize_returns_a_json_safe_dir(tmp_path, stub_steps):
    """Outputs are checkpointed, and a Path would force a pickle."""
    result = _standardize(tmp_path, _cal_folder(tmp_path, "a.cal"))
    assert isinstance(result["single_channel_dir"], str)
    json.dumps(result)


# ---------------------------------------------------------------------------
# build_calibration_mapping
# ---------------------------------------------------------------------------


def test_interactive_without_a_console_fails_before_moving_anything(tmp_path, monkeypatch):
    """The check runs before any file is moved."""
    moved = []
    monkeypatch.setattr(
        calibration_module,
        "handle_unused_calibration_files",
        lambda *a, **k: moved.append(True),
    )

    def _no_console():
        raise RuntimeError("no terminal")

    monkeypatch.setattr(calibration_module._console, "require_console", _no_console)

    with pytest.raises(RuntimeError, match="no terminal"):
        calibration_module.build_calibration_mapping(
            tmp_path / "out", conflict_resolution="interactive", verbose=False
        )
    assert moved == []


def test_unknown_conflict_mode_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unknown conflict_resolution"):
        calibration_module.build_calibration_mapping(
            tmp_path / "out", conflict_resolution="shrug", verbose=False
        )
