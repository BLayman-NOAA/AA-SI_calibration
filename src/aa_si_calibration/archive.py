# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Write the finished calibration to a directory the survey keeps.

The two calibration phases write into the run's own outputs tree, which for a
remote client is a container-local directory that goes away when the run ends.
This module copies the three things a survey archives out of it, into a
location the caller named:

    <archive_dir>/channel_mapping.yaml
    <archive_dir>/calibration_provenance.yaml
    <archive_dir>/Standardized_Reports/<calibration file key>.yaml

Everything is rendered from data, so a caller that holds the phase outputs and
has never seen the outputs folder can archive them. Falling back to reading the
folder is a convenience for a local run, where the data is already on disk.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from aa_si_calibration import _artifacts
from aa_si_calibration import _storage
from aa_si_calibration.mapping_algorithm import (
    dump_mapping_yaml,
    load_calibration_data_from_single_files,
)
from aa_si_calibration.provenance import PROVENANCE_FILENAME, dump_provenance_yaml
from aa_si_calibration.standardized_file_lib import dump_channel_yaml, json_safe

#: Subdirectory the single-channel files are archived under. Named for the
#: reviewer who reads them, not for the pipeline folder they come from.
REPORTS_DIRNAME = "Standardized_Reports"

MAPPING_FILENAME = "channel_mapping.yaml"

#: Where the phases write, relative to a calibration output_base. Mirrors
#: calibration._calibration_dirs, which creates them.
_SINGLE_CHANNEL_DIRNAME = "single_channel_calibration_files"
_MAPPING_DIRNAME = "mapping_files"


def _default_output_base(calibration_outputs):
    """The calibration outputs folder of the run in progress.

    Resolved the way initial_setup resolves it, so a local run that passes only
    a directory finds the files the earlier phases just wrote. Outside a recipe
    run this is a CWD-relative folder, which is where a notebook writes.
    """
    try:
        from aa_recipe_manager.executor.runtime_context import get_execution_context  # noqa: PLC0415
        artifacts_dir = getattr(get_execution_context(), "artifacts_dir", None)
    except ImportError:
        artifacts_dir = None

    if artifacts_dir is None:
        return Path(calibration_outputs)
    return Path(str(artifacts_dir)) / calibration_outputs


def _load_yaml(path):
    """Read a YAML file, or return None when it is not there."""
    path = Path(path)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _missing(name, source, base):
    return ValueError(
        f"{name} was not supplied and no {source} exists under {base}. Pass it "
        f"from the calibration_mapping recipe's outputs, or point output_base "
        f"at the calibration outputs folder of a completed run."
    )


def _resolve_content(single_channel_data, mapping_dict, provenance, base):
    """Fill in whatever the caller did not supply from the folder at *base*.

    Returns:
        tuple: ``(channels, mapping_dict, provenance)``.
    """
    if single_channel_data is None:
        single_cal_dir = Path(base) / _SINGLE_CHANNEL_DIRNAME
        if not single_cal_dir.exists():
            raise _missing("single_channel_data", _SINGLE_CHANNEL_DIRNAME, base)
        # The same read calibration._payload_from_dir does, composed here rather
        # than imported: that module pulls in echopype, and archiving a finished
        # calibration needs nothing echopype provides.
        single_channel_data = json_safe(
            load_calibration_data_from_single_files(single_cal_dir)
        )

    channels = single_channel_data
    if isinstance(channels, dict):
        channels = channels.get("channels", [])
    if not channels:
        raise ValueError(
            "single_channel_data carries no channels, so there is nothing to "
            "archive."
        )
    if not all(isinstance(channel, dict) for channel in channels):
        raise ValueError(
            "single_channel_data must carry one dictionary per channel, in "
            "the shape the standardization step returns it."
        )

    if mapping_dict is None:
        mapping_dict = _load_yaml(Path(base) / _MAPPING_DIRNAME / MAPPING_FILENAME)
        if mapping_dict is None:
            raise _missing("mapping_dict", MAPPING_FILENAME, base)
    if not mapping_dict:
        raise ValueError(
            "mapping_dict is empty, which is what the mapping step returns "
            "while conflicts are unresolved. Resolve them and re-run the "
            "mapping before archiving: an archive that looks complete and is "
            "not is worse than a failed run."
        )

    if provenance is None:
        provenance = _load_yaml(Path(base) / _MAPPING_DIRNAME / PROVENANCE_FILENAME)
        if provenance is None:
            raise _missing("provenance", PROVENANCE_FILENAME, base)

    return channels, mapping_dict, provenance


#: Characters no calibration file key may contain. The key becomes a filename,
#: and calibration_key_to_filename already replaces the three separators, so a
#: key carrying one did not come from this library.
_UNSAFE_IN_STEM = frozenset('/*?"<>|') | {"\\", ":", "\x00"}


def _check_file_keys(channels):
    """Raise unless every channel names exactly one file the archive can hold.

    A key becomes a filename, and ``single_channel_data`` reaches a server
    straight from a client, so a key is checked rather than trusted: one
    carrying a separator would write outside the archive directory, and two
    channels sharing a key would write one file and silently drop a channel
    while still reporting both as archived.

    Returns:
        list: The file key of each channel, in order.
    """
    keys = [channel.get("_calibration_file_key") for channel in channels]

    if not all(keys):
        raise ValueError(
            f"{sum(1 for key in keys if not key)} channel(s) carry no "
            f"_calibration_file_key, so they have no filename to archive "
            f"under. Pass single_channel_data through unchanged from the "
            f"standardization step, which is what attaches the keys the "
            f"mapping refers to."
        )

    unsafe = sorted(
        {key for key in keys
         if set(key) & _UNSAFE_IN_STEM or key.strip(".") == ""}
    )
    if unsafe:
        raise ValueError(
            f"These calibration file key(s) cannot be used as filenames: "
            f"{', '.join(repr(key) for key in unsafe)}. A key is a single "
            f"file name, never a path. Pass single_channel_data through "
            f"unchanged from the standardization step."
        )

    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ValueError(
            f"{len(duplicates)} calibration file key(s) appear on more than "
            f"one channel: {', '.join(duplicates)}. Each key names one file, "
            f"so archiving these would write one channel over another and "
            f"report both as kept."
        )

    return keys


def _check_mapping_is_covered(keys, mapping_dict):
    """Raise when the mapping names a calibration file the archive would lack.

    The mapping's values are the single-channel file *stems*, so a stem with no
    channel behind it archives as a mapping pointing at a file that is not
    there. Checked before anything is written, because the archive is what gets
    read years later, with nothing around to regenerate it from, and a
    half-written one is worse than none.
    """
    if not all(isinstance(entry, dict) for entry in mapping_dict.values()):
        raise ValueError(
            "mapping_dict must map each raw filename to a dictionary of "
            "channel id to calibration key, in the shape the mapping step "
            "returns it."
        )

    referenced = {
        cal_key
        for channel_keys in mapping_dict.values()
        for cal_key in channel_keys.values()
    }
    orphans = sorted(referenced - set(keys))
    if orphans:
        raise ValueError(
            f"The mapping references {len(orphans)} calibration file(s) that "
            f"are not in single_channel_data, so the archive would point at "
            f"files it does not contain: {', '.join(orphans)}. The two must "
            f"come from the same mapping run."
        )


def _check_destination(archive_dir, reports_dir, overwrite, options):
    """Refuse a non-empty destination, or clear what overwrite replaces."""
    if not _storage.is_remote(archive_dir) and Path(archive_dir).is_file():
        raise ValueError(
            f"{archive_dir} is a file. archive_dir names the directory the "
            f"archive is written into, not a file to write."
        )

    if _storage.is_empty_dir(archive_dir, options):
        return

    if not overwrite:
        raise ValueError(
            f"{archive_dir} is not empty. An archive directory is written once "
            f"and kept, so this run would overwrite something. Pass "
            f"overwrite=True to replace what is there, or name a new directory."
        )

    # The channel set is a complete statement: without the clear, a channel
    # dropped during review survives as an orphan file in the archive.
    _storage.clear_dir(reports_dir, options)


def save_calibration_archive(
    archive_dir,
    single_channel_data=None,
    mapping_dict=None,
    provenance=None,
    output_base=None,
    calibration_outputs="calibration",
    overwrite=False,
    verbose=True,
):
    """Write the finished calibration outputs to *archive_dir* for keeping.

    Writes ``channel_mapping.yaml`` and ``calibration_provenance.yaml`` at the
    top of the directory, and one file per channel under
    ``Standardized_Reports/``. The channel files are named by each channel's
    ``_calibration_file_key``, which is what the mapping refers to, so the
    archive resolves against itself.

    Any of the three content arguments may be omitted, in which case it is read
    from the calibration outputs folder of the run in progress. Supply all
    three and nothing is read from disk, which is how a caller with no access
    to that folder archives what the earlier phases returned to it.

    Args:
        archive_dir: Directory to write the archive into. May be a remote
            fsspec URL (e.g. gs://bucket/surveys/RL2307/calibration).
        single_channel_data: The standardized channels, as returned on the
            standardization step's single_channel_data output. Read from
            single_channel_calibration_files/ when omitted.
        mapping_dict: Each raw file's channels mapped to their calibration key,
            from the mapping step. Read from channel_mapping.yaml when omitted.
        provenance: The provenance report from the mapping step. Read from
            calibration_provenance.yaml when omitted.
        output_base: Calibration outputs folder to read anything omitted from.
            Defaults to the folder the run in progress is writing.
        calibration_outputs: Subdirectory name under the run's outputs folder,
            used only to build that default.
        overwrite: If True, replace an archive already in *archive_dir*.
        verbose: If True, print what was written.

    Returns:
        dict with keys:
            - archive_dir: The directory that was written.
            - mapping_path: Full path of the archived mapping file.
            - provenance_path: Full path of the archived provenance report.
            - reports_dir: The Standardized_Reports folder.
            - channel_count: How many channel files were written.
            - files_written: Every path written, in write order.

    Raises:
        ValueError: If content is neither supplied nor on disk; if the mapping
            is empty or references a calibration file the channels do not
            carry; if a channel's file key is missing, shared with another
            channel, or not a plain file name; or if *archive_dir* is not empty
            and *overwrite* is False. Nothing is written when any of these
            fires.
    """
    base = output_base if output_base is not None else _default_output_base(
        calibration_outputs
    )

    channels, mapping_dict, provenance = _resolve_content(
        single_channel_data, mapping_dict, provenance, base
    )
    file_keys = _check_file_keys(channels)
    _check_mapping_is_covered(file_keys, mapping_dict)

    options = _storage.execution_storage_options() if _storage.is_remote(
        archive_dir
    ) else None
    reports_dir = _storage.join(archive_dir, REPORTS_DIRNAME)
    _check_destination(archive_dir, reports_dir, overwrite, options)

    files_written = []

    mapping_path = _storage.write_text(
        _storage.join(archive_dir, MAPPING_FILENAME),
        dump_mapping_yaml(mapping_dict),
        options,
    )
    files_written.append(mapping_path)

    provenance_path = _storage.write_text(
        _storage.join(archive_dir, PROVENANCE_FILENAME),
        dump_provenance_yaml(provenance),
        options,
    )
    files_written.append(provenance_path)

    for file_key, channel in zip(file_keys, channels):
        files_written.append(
            _storage.write_text(
                _storage.join(reports_dir, f"{file_key}.yaml"),
                dump_channel_yaml(channel),
                options,
            )
        )

    for path in files_written:
        _artifacts.record_artifact(path)

    if verbose:
        print(f"\nArchived the calibration to: {archive_dir}")
        print(f"  {MAPPING_FILENAME} ({len(mapping_dict)} raw file(s))")
        print(f"  {PROVENANCE_FILENAME}")
        print(f"  {REPORTS_DIRNAME}/ ({len(channels)} channel file(s))")

    return {
        "archive_dir": str(archive_dir),
        "mapping_path": mapping_path,
        "provenance_path": provenance_path,
        "reports_dir": str(reports_dir),
        "channel_count": len(channels),
        "files_written": files_written,
    }
