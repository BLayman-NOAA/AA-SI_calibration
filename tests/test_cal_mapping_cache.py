# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Step 1 / Step 2 reuse in generate_standardized_cal_mapping.

The two steps are cached against different inputs and must be skipped
independently: Step 1 answers to the raw folder and the time window, Step 2 to
the manufacturer calibration folder. These tests pin both halves, and the case
that motivated splitting them -- a changed raw folder being silently ignored
because single-channel files happened to exist.
"""

import yaml
import pytest

from aa_si_calibration import calibration as calibration_module


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Patch out every step's real work, counting Step 1 and Step 2 runs.

    Step 1 records the raw filenames it was asked to scan so a test can tell
    which raw folder the saved configs came from. Step 2 writes real
    single-channel files, because the Step 2 guard reads that directory.
    """
    calls = {"scan": [], "parse": 0}

    def _scan(raw_input_folder, *_args, **kwargs):
        raw_files = kwargs.get("raw_files")
        if raw_files is None:
            raw_files = sorted(raw_input_folder.glob("*.raw"))
        names = [p.name for p in raw_files]
        calls["scan"].append(names)
        configs = [
            {"filename": name, "channels": [{"channel_id": "ch-1", "frequency": 38000}]}
            for name in names
        ]
        return configs, {38000}

    def _parse(*_args, **_kwargs):
        calls["parse"] += 1
        return (
            {"gain_correction": [1.0]},
            {"sound_speed": 1500.0},
            {"channel": ["ch-1"]},
            ".cal",
        )

    def _save_single_channel_files(*_args, **kwargs):
        out_dir = kwargs["output_dir"]
        (out_dir / "ch-1.yaml").write_text("channel_id: ch-1\n", encoding="utf-8")
        return 1, None, {"saved": True}

    monkeypatch.setattr(calibration_module, "process_raw_folder", _scan)
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

    # Steps 3-4 always run; stub them so the tests stay about steps 1-2.
    dummy = type(
        "Result",
        (),
        {
            "mapping_dict": {"file.raw": {"ch-1": "key-1"}},
            "calibration_dict": {"key-1": {"gain_correction": 1.0}},
            "print_summary": lambda self: None,
        },
    )()
    monkeypatch.setattr(
        calibration_module, "load_calibration_data_from_single_files",
        lambda *_a, **_k: {"channels": ["ch-1"]},
    )
    monkeypatch.setattr(calibration_module, "build_mapping", lambda *_a, **_k: dummy)
    for name in (
        "handle_unused_calibration_files",
        "check_for_conflicts",
        "print_mapping_preview",
    ):
        monkeypatch.setattr(calibration_module, name, lambda *_a, **_k: None)
    monkeypatch.setattr(
        calibration_module, "save_mapping_files",
        lambda *_a, **_k: ("mapping.yaml", "calibration.yaml"),
    )
    monkeypatch.setattr(
        calibration_module, "check_required_calibration_params", lambda *_a, **_k: {},
    )
    monkeypatch.setattr(
        calibration_module, "verify_calibration_file_usage", lambda *_a, **_k: [],
    )
    return calls


def _make_raw_folder(path, names):
    path.mkdir(parents=True, exist_ok=True)
    for name in names:
        (path / name).write_bytes(b"raw")
    return path


def _run(raw_dir, cal_dir, out_base, **kwargs):
    return calibration_module.generate_standardized_cal_mapping(
        raw_input_folder=raw_dir,
        cal_input_folder=cal_dir,
        output_base=out_base,
        cruise_id="TEST",
        record_author="Tester",
        short_filenames=False,
        verbose=False,
        **kwargs,
    )


def test_unchanged_inputs_reuse_both_steps(tmp_path, stub_pipeline):
    raw_dir = _make_raw_folder(tmp_path / "raw", ["D20240101-T000000.raw"])
    cal_dir = tmp_path / "cal"
    cal_dir.mkdir()
    out_base = tmp_path / "out"

    _run(raw_dir, cal_dir, out_base)
    _run(raw_dir, cal_dir, out_base)

    assert len(stub_pipeline["scan"]) == 1, "raw folder was rescanned unnecessarily"
    assert stub_pipeline["parse"] == 1, "calibration files were reparsed unnecessarily"


def test_added_raw_file_forces_rescan(tmp_path, stub_pipeline):
    """The bug this split fixes: a changed raw folder must not be ignored.

    Single-channel files exist after the first run, which previously skipped
    the raw scan too and left the mapping built from a stale file list.
    """
    raw_dir = _make_raw_folder(tmp_path / "raw", ["D20240101-T000000.raw"])
    cal_dir = tmp_path / "cal"
    cal_dir.mkdir()
    out_base = tmp_path / "out"

    _run(raw_dir, cal_dir, out_base)
    _make_raw_folder(raw_dir, ["D20240102-T000000.raw"])
    _run(raw_dir, cal_dir, out_base)

    assert len(stub_pipeline["scan"]) == 2, "added raw file did not trigger a rescan"
    assert stub_pipeline["scan"][1] == [
        "D20240101-T000000.raw",
        "D20240102-T000000.raw",
    ]
    # Step 2 answers to the calibration folder, which did not change.
    assert stub_pipeline["parse"] == 1

    saved = yaml.safe_load(
        (out_base / "raw_file_configs" / "raw_file_configs.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert [entry["filename"] for entry in saved] == [
        "D20240101-T000000.raw",
        "D20240102-T000000.raw",
    ]


def test_changed_time_window_forces_rescan(tmp_path, stub_pipeline):
    raw_dir = _make_raw_folder(
        tmp_path / "raw", ["D20240101-T000000.raw", "D20240102-T000000.raw"]
    )
    cal_dir = tmp_path / "cal"
    cal_dir.mkdir()
    out_base = tmp_path / "out"

    _run(raw_dir, cal_dir, out_base)
    _run(raw_dir, cal_dir, out_base, file_time_start="2024-01-02T00:00")

    assert len(stub_pipeline["scan"]) == 2, "changed window did not trigger a rescan"
    assert stub_pipeline["scan"][1] == ["D20240102-T000000.raw"]


def test_deleted_single_channel_file_is_not_regenerated(tmp_path, stub_pipeline):
    """The conflict-resolution workflow the Step 2 guard exists to support."""
    raw_dir = _make_raw_folder(tmp_path / "raw", ["D20240101-T000000.raw"])
    cal_dir = tmp_path / "cal"
    cal_dir.mkdir()
    out_base = tmp_path / "out"
    single_cal = out_base / "single_channel_calibration_files"

    _run(raw_dir, cal_dir, out_base)
    (single_cal / "ch-1.yaml").write_text("channel_id: ch-1\nedited: true\n", encoding="utf-8")
    _run(raw_dir, cal_dir, out_base)

    assert stub_pipeline["parse"] == 1, "Step 2 overwrote the user's edited file"
    assert "edited: true" in (single_cal / "ch-1.yaml").read_text(encoding="utf-8")


def test_missing_fingerprint_sidecar_forces_rescan(tmp_path, stub_pipeline):
    """Configs of unknown provenance are re-scanned rather than trusted."""
    raw_dir = _make_raw_folder(tmp_path / "raw", ["D20240101-T000000.raw"])
    cal_dir = tmp_path / "cal"
    cal_dir.mkdir()
    out_base = tmp_path / "out"

    _run(raw_dir, cal_dir, out_base)
    (out_base / "raw_file_configs" / "raw_file_configs.fingerprint.json").unlink()
    _run(raw_dir, cal_dir, out_base)

    assert len(stub_pipeline["scan"]) == 2
