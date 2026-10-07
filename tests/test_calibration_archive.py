# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Tests for archiving the finished calibration to a directory of one's choosing.

The archive is what gets read years after the run that produced it, with
nothing around to regenerate it from, so the properties that matter are the
ones nothing downstream can repair: the channel files have to be named what the
mapping says they are, and an archive must never look complete when it is not.

``memory://`` stands in for ``gs://`` - a non-local fsspec store needing no
credentials.
"""

from __future__ import annotations

from pathlib import Path

import fsspec
import pytest
import yaml

from aa_si_calibration import archive
from aa_si_calibration import provenance as provenance_module
from aa_si_calibration import standardized_file_lib as sfl


@pytest.fixture(autouse=True)
def clear_memory_fs():
    mem = fsspec.filesystem("memory")
    mem.store.clear()
    mem.pseudo_dirs[:] = [""]
    yield
    mem.store.clear()
    mem.pseudo_dirs[:] = [""]


def _channel(**overrides):
    """A schema-valid standardized channel."""
    channel = {
        "channel": "ES38-7 Serial No: 337 - Narrow",
        "frequency": [38000.0],
        "calibration_date": ["2023-06-27"],
        "source_filenames": ["cal_38kHz_CW.xml"],
        "transducer_model": "ES38-7",
        "transducer_serial_number": "337",
        "pulse_form": "CW",
        "nominal_transducer_frequency": 38000,
        "transmit_power": 2000.0,
        "transmit_duration_nominal": 0.001024,
        "frequency_start": 38000,
        "frequency_end": 38000,
    }
    channel.update(overrides)
    return channel


def _payload(channels):
    """The single_channel_data a standardization run would return."""
    return sfl.single_channel_payload(
        sfl.assign_calibration_file_stems(channels, short_filenames=True)
    )


def _stems(payload):
    return [ch["_calibration_file_key"] for ch in payload["channels"]]


def _mapping_for(payload):
    """A one-raw-file mapping naming every channel in *payload*."""
    return {
        "2307RL_CW-D20230717-T163046.raw": {
            f"WBT 98776{i}-15 ES-{i}": stem
            for i, stem in enumerate(_stems(payload))
        }
    }


@pytest.fixture
def supplied():
    """Two channels, their mapping, and a provenance report."""
    channels = [
        _channel(),
        _channel(
            channel="ES120-7C Serial No: 421 - Narrow",
            frequency=[120000.0],
            transducer_model="ES120-7C",
            transducer_serial_number="421",
            nominal_transducer_frequency=120000,
            frequency_start=120000,
            frequency_end=120000,
            source_filenames=["cal_120kHz_CW.xml"],
        ),
    ]
    payload = _payload(channels)
    return {
        "single_channel_data": payload,
        "mapping_dict": _mapping_for(payload),
        "provenance": {"schema_version": "1", "cruise_id": "RL2307", "channels": {}},
    }


def _archived_stems(archive_dir):
    reports = Path(archive_dir) / archive.REPORTS_DIRNAME
    return sorted(p.stem for p in reports.glob("*.yaml"))


# ---------------------------------------------------------------------------
# What the archive holds
# ---------------------------------------------------------------------------


def test_archive_holds_the_mapping_provenance_and_one_file_per_channel(
    tmp_path, supplied
):
    destination = tmp_path / "archive"

    result = archive.save_calibration_archive(destination, **supplied)

    assert (destination / "channel_mapping.yaml").exists()
    assert (destination / "calibration_provenance.yaml").exists()
    assert result["channel_count"] == 2
    assert len(_archived_stems(destination)) == 2
    assert len(result["files_written"]) == 4


def test_archived_channel_files_are_named_what_the_mapping_references(
    tmp_path, supplied
):
    """The archive has to resolve against itself, with nothing else around."""
    destination = tmp_path / "archive"

    archive.save_calibration_archive(destination, **supplied)

    mapping = yaml.safe_load((destination / "channel_mapping.yaml").read_text())
    referenced = {
        cal_key
        for channels in mapping.values()
        for cal_key in channels.values()
    }
    assert referenced == set(_archived_stems(destination))


def test_an_archived_channel_file_matches_the_one_a_local_run_writes(
    tmp_path, supplied
):
    """Same renderer, so the archive is not a second dialect of the format."""
    destination = tmp_path / "archive"
    local_run = tmp_path / "single_channel_calibration_files"

    archive.save_calibration_archive(destination, **supplied)
    sfl.save_single_channel_files([_channel()], local_run, short_filenames=True)

    stem = _stems(supplied["single_channel_data"])[0]
    archived = destination / archive.REPORTS_DIRNAME / f"{stem}.yaml"
    assert archived.read_text() == (local_run / f"{stem}.yaml").read_text()


def test_a_local_and_a_remote_archive_are_byte_for_byte_the_same(
    tmp_path, supplied
):
    """An archive is checksummed and compared, so where it went cannot show.

    Left to the platform, the local copy would carry Windows line endings and
    the bucket copy would not, and the two would never match.
    """
    local = tmp_path / "archive"
    archive.save_calibration_archive(local, **supplied)
    archive.save_calibration_archive("memory://arch", **supplied)

    fs = fsspec.filesystem("memory")
    for path in sorted(local.rglob("*.yaml")):
        relative = path.relative_to(local).as_posix()
        assert path.read_bytes() == fs.cat_file(f"/arch/{relative}"), relative


def test_the_archived_provenance_matches_the_report_the_mapping_writes(
    tmp_path, supplied
):
    destination = tmp_path / "archive"
    local_run = tmp_path / "mapping_files"

    archive.save_calibration_archive(destination, **supplied)
    written = provenance_module.save_calibration_provenance(
        supplied["provenance"], local_run
    )

    assert (destination / "calibration_provenance.yaml").read_text() == (
        Path(written).read_text()
    )


# ---------------------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------------------


def test_a_mapping_naming_a_channel_that_is_not_there_is_refused(tmp_path, supplied):
    supplied["mapping_dict"] = {
        "2307RL_CW-D20230717-T163046.raw": {"WBT 1": "2023-06-27__333000__config-1"}
    }

    with pytest.raises(ValueError, match="not in single_channel_data"):
        archive.save_calibration_archive(tmp_path / "archive", **supplied)


def test_an_empty_mapping_is_refused(tmp_path, supplied):
    """That is what the mapping step returns while conflicts are unresolved."""
    supplied["mapping_dict"] = {}

    with pytest.raises(ValueError, match="conflicts are unresolved"):
        archive.save_calibration_archive(tmp_path / "archive", **supplied)


def test_a_channel_with_no_file_key_is_refused_before_anything_is_written(
    tmp_path, supplied
):
    """A half-written archive is worse than none, so this fires up front."""
    destination = tmp_path / "archive"
    supplied["single_channel_data"]["channels"][0].pop("_calibration_file_key")

    with pytest.raises(ValueError, match="no _calibration_file_key"):
        archive.save_calibration_archive(destination, **supplied)

    assert not destination.exists()


def test_two_channels_sharing_a_file_key_are_refused(tmp_path, supplied):
    """One key names one file, so this would write one channel over another."""
    destination = tmp_path / "archive"
    channels = supplied["single_channel_data"]["channels"]
    channels[1]["_calibration_file_key"] = channels[0]["_calibration_file_key"]

    with pytest.raises(ValueError, match="more than"):
        archive.save_calibration_archive(destination, **supplied)

    assert not destination.exists()


@pytest.mark.parametrize(
    "file_key",
    ["../escaped", "sub/dir", r"sub\dir", "..", "C:evil"],
)
def test_a_file_key_that_is_not_a_plain_filename_is_refused(
    tmp_path, supplied, file_key
):
    """single_channel_data reaches a server from a client, so keys are checked.

    A key carrying a separator would write outside the archive directory.
    """
    destination = tmp_path / "archive" / "inner"
    supplied["single_channel_data"]["channels"][0]["_calibration_file_key"] = file_key
    supplied["mapping_dict"] = {"a.raw": {"WBT 1": file_key}}

    with pytest.raises(ValueError, match="cannot be used as filenames"):
        archive.save_calibration_archive(destination, **supplied)

    assert not list((tmp_path / "archive").rglob("*.yaml"))


def test_malformed_payloads_are_refused_with_a_clear_error(tmp_path, supplied):
    """A server turns these into a bad-request, so they must not be crashes."""
    destination = tmp_path / "archive"

    bad_channels = dict(supplied, single_channel_data={"channels": ["oops"]})
    with pytest.raises(ValueError, match="one dictionary per channel"):
        archive.save_calibration_archive(destination, **bad_channels)

    bad_mapping = dict(supplied, mapping_dict={"a.raw": "not-a-dict"})
    with pytest.raises(ValueError, match="channel id to calibration key"):
        archive.save_calibration_archive(destination, **bad_mapping)


def test_an_archive_dir_that_is_a_file_is_refused(tmp_path, supplied):
    destination = tmp_path / "not_a_dir.yaml"
    destination.write_text("x")

    with pytest.raises(ValueError, match="is a file"):
        archive.save_calibration_archive(destination, **supplied)


def test_a_non_empty_destination_is_refused(tmp_path, supplied):
    destination = tmp_path / "archive"
    destination.mkdir()
    (destination / "channel_mapping.yaml").write_text("old: archive\n")

    with pytest.raises(ValueError, match="not empty"):
        archive.save_calibration_archive(destination, **supplied)

    assert (destination / "channel_mapping.yaml").read_text() == "old: archive\n"


def test_overwrite_replaces_the_archive_and_leaves_no_orphan_channel_file(
    tmp_path, supplied
):
    """A channel dropped during review must not survive in the new archive."""
    destination = tmp_path / "archive"
    archive.save_calibration_archive(destination, **supplied)
    before = _archived_stems(destination)

    payload = _payload([_channel()])
    archive.save_calibration_archive(
        destination,
        single_channel_data=payload,
        mapping_dict=_mapping_for(payload),
        provenance=supplied["provenance"],
        overwrite=True,
    )

    assert len(before) == 2
    assert _archived_stems(destination) == _stems(payload)


# ---------------------------------------------------------------------------
# Reading the outputs folder instead
# ---------------------------------------------------------------------------


def _write_outputs_folder(base, supplied):
    """The calibration outputs tree the first two phases leave behind."""
    single_cal = base / "single_channel_calibration_files"
    mapping_dir = base / "mapping_files"
    single_cal.mkdir(parents=True)
    mapping_dir.mkdir(parents=True)

    for channel in supplied["single_channel_data"]["channels"]:
        stem = channel["_calibration_file_key"]
        (single_cal / f"{stem}.yaml").write_text(sfl.dump_channel_yaml(channel))
    (mapping_dir / "channel_mapping.yaml").write_text(
        yaml.dump(supplied["mapping_dict"], sort_keys=False)
    )
    provenance_module.save_calibration_provenance(supplied["provenance"], mapping_dir)


def test_a_local_run_archives_from_the_outputs_folder_with_no_data_passed(
    tmp_path, supplied
):
    base = tmp_path / "outputs" / "calibration"
    _write_outputs_folder(base, supplied)
    destination = tmp_path / "archive"

    result = archive.save_calibration_archive(destination, output_base=base)

    assert result["channel_count"] == 2
    assert _archived_stems(destination) == sorted(
        _stems(supplied["single_channel_data"])
    )


def test_the_folder_and_the_data_produce_the_same_archive(tmp_path, supplied):
    """The two ways in have to agree, or the remote archive is a different thing."""
    base = tmp_path / "outputs" / "calibration"
    _write_outputs_folder(base, supplied)

    from_folder = tmp_path / "from_folder"
    from_data = tmp_path / "from_data"
    archive.save_calibration_archive(from_folder, output_base=base)
    archive.save_calibration_archive(from_data, **supplied)

    written = sorted(
        p.relative_to(from_folder).as_posix() for p in from_folder.rglob("*.yaml")
    )
    assert written == sorted(
        p.relative_to(from_data).as_posix() for p in from_data.rglob("*.yaml")
    )
    for relative in written:
        assert (from_folder / relative).read_text() == (from_data / relative).read_text()


def test_a_missing_outputs_folder_names_what_it_could_not_find(tmp_path, supplied):
    with pytest.raises(ValueError, match="single_channel_data was not supplied"):
        archive.save_calibration_archive(
            tmp_path / "archive", output_base=tmp_path / "nothing_here"
        )


# ---------------------------------------------------------------------------
# A remote destination
# ---------------------------------------------------------------------------


def test_the_archive_can_be_written_to_a_remote_destination(supplied):
    destination = "memory://surveys/RL2307/calibration"

    result = archive.save_calibration_archive(destination, **supplied)

    fs = fsspec.filesystem("memory")
    expected = [
        f"/surveys/RL2307/calibration/Standardized_Reports/{stem}.yaml"
        for stem in sorted(_stems(supplied["single_channel_data"]))
    ] + [
        "/surveys/RL2307/calibration/calibration_provenance.yaml",
        "/surveys/RL2307/calibration/channel_mapping.yaml",
    ]
    assert sorted(fs.find("/surveys/RL2307/calibration")) == sorted(expected)
    assert result["channel_count"] == 2

    mapping = yaml.safe_load(
        fs.cat_file("/surveys/RL2307/calibration/channel_mapping.yaml")
    )
    assert mapping == supplied["mapping_dict"]


def test_a_non_empty_remote_destination_is_refused(supplied):
    destination = "memory://surveys/RL2307/calibration"
    fsspec.filesystem("memory").pipe_file(
        "/surveys/RL2307/calibration/channel_mapping.yaml", b"old: archive\n"
    )

    with pytest.raises(ValueError, match="not empty"):
        archive.save_calibration_archive(destination, **supplied)
