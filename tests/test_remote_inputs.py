# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Tests for gs://-shaped (remote) raw and calibration *input* folders.

``memory://`` stands in for ``gs://`` — a non-local fsspec store needing no
credentials. The deep readers are never exercised against remote data; remote
inputs are materialized locally at the op boundary.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import fsspec
import pytest

from aa_si_calibration import _storage
from aa_si_calibration import calibration as calibration_module
from aa_si_calibration import raw_reader_api


@pytest.fixture(autouse=True)
def clear_memory_fs():
    mem = fsspec.filesystem("memory")
    mem.store.clear()
    mem.pseudo_dirs[:] = [""]
    yield
    mem.store.clear()
    mem.pseudo_dirs[:] = [""]


_RAW_A = "D20160725-T205832.raw"   # 20:58:32
_RAW_B = "D20160725-T210500.raw"   # 21:05:00
_RAW_C = "D20160725-T213000.raw"   # 21:30:00


# ---------------------------------------------------------------------------
# _storage helpers
# ---------------------------------------------------------------------------


def test_is_remote_and_basename():
    assert _storage.is_remote("memory://b/x.raw")
    assert not _storage.is_remote(r"C:\data\x.raw")   # Windows drive, not a URL
    assert not _storage.is_remote(Path("x.raw"))
    assert _storage.basename("memory://b/sub/x.raw") == "x.raw"


def test_localized_file_downloads_and_cleans_up():
    fs = fsspec.filesystem("memory")
    fs.pipe_file("/b/" + _RAW_A, b"payload")

    captured = {}
    with _storage.localized_file("memory://b/" + _RAW_A) as local:
        captured["path"] = local
        assert local.exists()
        assert local.name == _RAW_A
        assert local.read_bytes() == b"payload"

    assert not captured["path"].exists()          # local copy removed
    assert not captured["path"].parent.exists()    # scratch dir removed
    assert fs.exists("/b/" + _RAW_A)               # bucket object intact


def test_localized_file_companion():
    fs = fsspec.filesystem("memory")
    fs.pipe_file("/b/" + _RAW_A, b"raw")
    fs.pipe_file("/b/" + _RAW_A.replace(".raw", ".bot"), b"bot")

    with _storage.localized_file(
        "memory://b/" + _RAW_A, companion_suffixes=(".bot",)
    ) as local:
        assert local.with_suffix(".bot").exists()


def test_localized_folder_downloads_matching_files():
    fs = fsspec.filesystem("memory")
    fs.pipe_file("/b/cal/a.cal", b"a")
    fs.pipe_file("/b/cal/b.xml", b"b")
    fs.pipe_file("/b/cal/notes.txt", b"skip")

    with _storage.localized_folder("memory://b/cal", ("*.cal", "*.xml")) as folder:
        names = sorted(p.name for p in folder.iterdir())
        assert names == ["a.cal", "b.xml"]
        assert folder.is_dir()

    assert not folder.exists()          # scratch removed
    assert fs.exists("/b/cal/a.cal")    # bucket intact


def test_glob_url_returns_reopenable_urls():
    fs = fsspec.filesystem("memory")
    fs.pipe_file("/b/raw/" + _RAW_B, b"x")
    fs.pipe_file("/b/raw/" + _RAW_A, b"x")
    urls = _storage.glob_url("memory://b/raw", "*.raw")
    assert [_storage.basename(u) for u in urls] == [_RAW_A, _RAW_B]  # sorted
    assert all(fs.exists(u) for u in urls)


# ---------------------------------------------------------------------------
# filter_paths_by_file_time (calibration's local copy)
# ---------------------------------------------------------------------------


def test_parse_and_filter():
    assert _storage.parse_datetime_from_filename(_RAW_A) == datetime(2016, 7, 25, 20, 58, 32)
    paths = [_RAW_A, _RAW_B, _RAW_C]
    assert _storage.filter_paths_by_file_time(paths) == paths
    assert _storage.filter_paths_by_file_time(
        paths, "2016-07-25T21:00", "2016-07-25T21:05:00"
    ) == [_RAW_B]
    assert _storage.filter_paths_by_file_time([_RAW_A, "x.raw"], "2016-01-01T00:00", None) == [_RAW_A]


# ---------------------------------------------------------------------------
# _process_raw_folder_remote: per-file download/delete, sort, filter
# ---------------------------------------------------------------------------


def _patch_process_raw_file(monkeypatch, recorder=None):
    """Stub raw_reader_api.process_raw_file (imported lazily inside the helper)."""
    def fake(raw_path, verbose=True, verify_start_time=False):
        p = Path(raw_path)
        assert p.exists()  # a real local copy exists while "processing"
        if recorder is not None:
            recorder(p)
        # metadata_start_time drives sorting; derive from the filename stamp.
        stamp = _storage.parse_datetime_from_filename(p.name)
        return {
            "filename": p.name,
            "metadata_start_time": stamp.isoformat() if stamp else None,
            "channels": [{"frequency": 38000}],
        }

    monkeypatch.setattr(raw_reader_api, "process_raw_file", fake)


def test_process_raw_folder_remote_sorts_and_returns_freqs(monkeypatch):
    fs = fsspec.filesystem("memory")
    for n in [_RAW_C, _RAW_A, _RAW_B]:
        fs.pipe_file("/s/raw/" + n, b"x")
    _patch_process_raw_file(monkeypatch)

    configs, freqs = calibration_module._process_raw_folder_remote(
        "memory://s/raw", verbose=False
    )
    assert [c["filename"] for c in configs] == [_RAW_A, _RAW_B, _RAW_C]  # sorted by time
    assert freqs == {38000}


def test_process_raw_folder_remote_deletes_between_files(monkeypatch):
    fs = fsspec.filesystem("memory")
    for n in [_RAW_A, _RAW_B]:
        fs.pipe_file("/s/raw/" + n, b"x")

    seen: list[Path] = []

    def recorder(p):
        assert all(not s.exists() for s in seen)  # previous copies already gone
        seen.append(p)

    _patch_process_raw_file(monkeypatch, recorder)
    calibration_module._process_raw_folder_remote("memory://s/raw", verbose=False)

    assert all(not s.exists() for s in seen)        # nothing left locally
    for n in [_RAW_A, _RAW_B]:
        assert fs.exists("/s/raw/" + n)             # bucket intact


def test_process_raw_folder_remote_empty_raises(monkeypatch):
    fsspec.filesystem("memory").makedirs("/s/empty", exist_ok=True)
    _patch_process_raw_file(monkeypatch)
    with pytest.raises(FileNotFoundError, match="No .raw files"):
        calibration_module._process_raw_folder_remote("memory://s/empty", verbose=False)


def test_process_raw_folder_remote_time_filter_before_download(monkeypatch):
    fs = fsspec.filesystem("memory")
    for n in [_RAW_A, _RAW_B, _RAW_C]:
        fs.pipe_file("/s/raw/" + n, b"x")

    downloaded: list[str] = []
    _patch_process_raw_file(monkeypatch, lambda p: downloaded.append(p.name))

    configs, _ = calibration_module._process_raw_folder_remote(
        "memory://s/raw", verbose=False, file_time_start="2016-07-25T21:00"
    )
    # Out-of-window file A was never downloaded / processed.
    assert downloaded == [_RAW_B, _RAW_C]
    assert [c["filename"] for c in configs] == [_RAW_B, _RAW_C]


# ---------------------------------------------------------------------------
# generate_standardized_cal_mapping: remote cal folder localized for parser
# ---------------------------------------------------------------------------


class _Stop(Exception):
    pass


def test_generate_cal_mapping_localizes_remote_cal_folder(monkeypatch, tmp_path):
    fs = fsspec.filesystem("memory")
    fs.pipe_file("/s/raw/" + _RAW_A, b"raw")
    fs.pipe_file("/s/cal/foo.cal", b"cal")
    fs.pipe_file("/s/cal/bar.xml", b"xml")

    _patch_process_raw_file(monkeypatch)

    captured = {}

    def fake_extract(cal_folder, **kwargs):
        captured["is_dir"] = Path(cal_folder).is_dir()
        captured["files"] = sorted(p.name for p in Path(cal_folder).iterdir())
        raise _Stop  # stop before the fragile downstream mapping chain

    monkeypatch.setattr(
        calibration_module.manufacturer_file_parsers,
        "extract_and_convert_calibration_params",
        fake_extract,
    )

    with pytest.raises(_Stop):
        calibration_module.generate_standardized_cal_mapping(
            "memory://s/raw",
            "memory://s/cal",
            tmp_path,
            cruise_id="C",
            record_author="A",
            verbose=False,
        )

    # The parser received a real local directory holding the bucket's cal files.
    assert captured["is_dir"] is True
    assert captured["files"] == ["bar.xml", "foo.cal"]
    # Bucket objects were not modified or removed.
    assert fs.exists("/s/cal/foo.cal")
    assert fs.exists("/s/raw/" + _RAW_A)
