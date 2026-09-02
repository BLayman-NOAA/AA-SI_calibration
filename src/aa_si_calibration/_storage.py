# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Minimal local/remote storage helpers for calibration *input* folders.

Remote (``gs://``) raw and calibration folders are handled at the op boundary
only: the deep readers (``raw_reader_api``, ``simrad_reader``,
``manufacturer_file_parsers``) stay strictly local-filesystem code, and this
module materializes remote inputs locally for them.

``aa_si_calibration`` intentionally depends on neither ``aa_si_utils`` nor
``aa_recipe_manager``, so the handful of helpers below are deliberately
duplicated from ``aa_si_utils._storage`` with identical names and semantics.
``fsspec`` is imported lazily, keeping it an optional dependency
(``pip install aa-si-calibration[gcs]``); the filename-time filter is pure
stdlib for local paths and works without it.
"""

from __future__ import annotations

import contextlib
import fnmatch
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

_URL_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]+://")
_LOCAL_PROTOCOLS = frozenset({"file", "local"})

_FSSPEC_HINT = (
    "Remote (gs://) input folders require fsspec and a cloud driver. "
    "Install them with: pip install 'aa-si-calibration[gcs]'"
)


def is_remote(value: Any) -> bool:
    """True when ``value`` denotes a non-local fsspec URL.

    Windows drive letters (``C:\\data``) are excluded: the scheme pattern
    requires two or more characters before ``://``.
    """
    if value is None:
        return False
    is_local = getattr(value, "is_local", None)
    if isinstance(is_local, bool):
        return not is_local
    if isinstance(value, Path):
        return False
    match = _URL_SCHEME_RE.match(str(value))
    if match is None:
        return False
    scheme = str(value)[: match.end() - 3].lower()
    return scheme not in _LOCAL_PROTOCOLS


def basename(value: Any) -> str:
    """Final path segment of a local path or a remote URL."""
    if is_remote(value):
        return str(value).rstrip("/").rsplit("/", 1)[-1]
    return Path(os.fspath(value)).name


def get_fs(url: Any, storage_options: dict[str, Any] | None = None) -> Any:
    """Return the fsspec filesystem for a remote URL."""
    try:
        import fsspec.core
    except ImportError as exc:  # pragma: no cover - exercised via message
        raise ImportError(_FSSPEC_HINT) from exc

    fs, _ = fsspec.core.url_to_fs(str(url), **(storage_options or {}))
    return fs


def glob_url(
    base: Any,
    pattern: str,
    storage_options: dict[str, Any] | None = None,
) -> list[str]:
    """Sorted full URLs of objects under a remote *base* matching *pattern*.

    ``fs.glob`` strips the protocol from results, so each match is reassembled
    with ``unstrip_protocol`` and can be reopened as-is.
    """
    fs = get_fs(base, storage_options)
    matches = fs.glob(str(base).rstrip("/") + "/" + pattern)
    return sorted(fs.unstrip_protocol(match) for match in matches)


def folder_fingerprint(
    folder: Any,
    pattern: str = "*.raw",
    storage_options: dict[str, Any] | None = None,
) -> list[list]:
    """Sorted ``[name, size]`` pairs for every *pattern* match under *folder*.

    Identifies a folder's contents without reading any of it: one directory
    listing locally, one ``ls`` call on a bucket. The folder's own location is
    excluded, so a local copy and the ``gs://`` original it was copied from
    fingerprint identically.

    Args:
        folder: Local path or remote fsspec URL to list.
        pattern: Glob pattern matched against each entry's basename.
        storage_options: fsspec options for a remote *folder*.

    Returns:
        List of ``[basename, size_in_bytes]`` pairs, sorted by basename.
    """
    if is_remote(folder):
        fs = get_fs(folder, storage_options)
        entries = fs.ls(str(folder).rstrip("/"), detail=True)
        found = [
            [_path_basename(entry["name"]), int(entry.get("size") or 0)]
            for entry in entries
            if entry.get("type") != "directory"
            and fnmatch.fnmatch(_path_basename(entry["name"]), pattern)
        ]
    else:
        found = [
            [path.name, path.stat().st_size]
            for path in Path(folder).glob(pattern)
            if path.is_file()
        ]
    return sorted(found)


def _rmtree_local(path: Path) -> None:
    """Recursively remove a local directory, clearing read-only bits (Windows)."""
    def _on_error(func, fpath, _exc_info):
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)

    shutil.rmtree(path, onerror=_on_error)


@contextlib.contextmanager
def localized_file(
    url: str,
    storage_options: dict[str, Any] | None = None,
    companion_suffixes: tuple[str, ...] = (),
) -> Iterator[Path]:
    """Download one remote file to a private local scratch dir; delete on exit.

    The scratch dir comes from :func:`tempfile.mkdtemp`, so it is genuinely
    local (the pipeline's ``temp_dir`` may itself be a bucket) and unique per
    call, letting concurrent instances run without colliding. The original
    basename is preserved because file configs record it. Only the local copy
    is removed — the remote object is never touched.
    """
    fs = get_fs(url, storage_options)
    scratch = Path(tempfile.mkdtemp(prefix="aa_si_localized_"))
    try:
        local_path = scratch / basename(url)
        fs.get(str(url), str(local_path))

        stem, _, _ = str(url).rpartition(".")
        for suffix in companion_suffixes:
            companion_url = stem + suffix
            if fs.exists(companion_url):
                fs.get(companion_url, str(scratch / basename(companion_url)))

        yield local_path
    finally:
        _rmtree_local(scratch)


@contextlib.contextmanager
def localized_file_head(
    url: str,
    storage_options: dict[str, Any] | None = None,
) -> Iterator[Any]:
    """Yield a callable that materializes a growing prefix of a remote file.

    ``fetch(n)`` extends the local copy to *n* bytes and returns its path,
    requesting only the bytes not already held. Walking a ladder of prefix
    sizes therefore costs one ranged GET per rung and transfers each byte
    once, rather than re-reading from zero at every rung.

    An EK80 file's channel configuration lives in the datagrams at the front
    of the file, so a prefix settles it without moving the sample payloads
    behind it. A prefix is a valid datagram stream up to its truncation point,
    which is where a walk over it stops. ``fetch`` returning a file shorter
    than requested means the whole object is now local.

    Args:
        url: Remote fsspec URL of the file.
        storage_options: fsspec options for the remote filesystem.

    Yields:
        Callable[[int], Path]: Extends the local prefix and returns its path.
        The scratch directory is deleted when the context exits.
    """
    fs = get_fs(url, storage_options)
    scratch = Path(tempfile.mkdtemp(prefix="aa_si_localized_head_"))
    try:
        local_path = scratch / basename(url)
        local_path.touch()
        held = 0

        def fetch(n_bytes: int) -> Path:
            nonlocal held
            if n_bytes > held:
                chunk = fs.cat_file(str(url), start=held, end=n_bytes)
                with open(local_path, "ab") as handle:
                    handle.write(chunk)
                held += len(chunk)
            return local_path

        yield fetch
    finally:
        _rmtree_local(scratch)


@contextlib.contextmanager
def localized_folder(
    url: str,
    patterns: tuple[str, ...] = ("*.cal", "*.xml"),
    storage_options: dict[str, Any] | None = None,
) -> Iterator[Path]:
    """Download a remote folder's matching files to a local scratch dir.

    Bulk download is fine here: calibration folders hold a handful of small
    ``.cal``/``.xml`` files, unlike raw folders. The directory is removed on
    exit; the remote folder is never modified.
    """
    fs = get_fs(url, storage_options)
    scratch = Path(tempfile.mkdtemp(prefix="aa_si_localized_cal_"))
    try:
        for pattern in patterns:
            for match in glob_url(url, pattern, storage_options):
                fs.get(match, str(scratch / basename(match)))
        yield scratch
    finally:
        _rmtree_local(scratch)


def execution_storage_options() -> dict[str, Any] | None:
    """Return the pipeline's fsspec options for remote input paths, or None.

    ``getattr`` tolerates recipe-manager versions predating the context field;
    ``None`` then means "use ambient credentials" (Application Default
    Credentials on GCP), which is the intended default.
    """
    try:
        from aa_recipe_manager.executor.runtime_context import get_execution_context  # noqa: PLC0415
        options = getattr(get_execution_context(), "storage_options", None)
        return dict(options) if options else None
    except ImportError:
        return None


# Filename-time filtering (pure stdlib; mirrors aa_si_utils.data_retrieval)

def parse_datetime_from_filename(filename: str) -> datetime | None:
    """Extract a datetime from a ``D{YYYYMMDD}-T{HHMMSS}`` filename stamp."""
    match = re.search(r"D(\d{8})-T(\d{6})", filename)
    if not match:
        return None
    date_part, time_part = match.groups()
    return datetime.strptime(date_part + time_part, "%Y%m%d%H%M%S")


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def _path_basename(path: Any) -> str:
    """Final segment of a local path or URL (handles ``/`` and Windows ``\\``)."""
    text = str(path).rstrip("/\\")
    return text.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]


def _next_stamp_map(stamps: list) -> dict:
    """Map each stamp to the earliest strictly-later stamp (last maps to None).

    Used to infer a file's end time: a raw file records from its own name
    stamp until the next file begins.
    """
    unique = sorted({s for s in stamps if s is not None})
    return {
        stamp: (unique[i + 1] if i + 1 < len(unique) else None)
        for i, stamp in enumerate(unique)
    }


def _boundary_stamp(stamps: list, start: datetime) -> datetime | None:
    """Stamp of the newest file starting before *start*, or None.

    That file is the only one whose name-based verdict rests on the inferred
    end time: every earlier file is bounded by another file that still starts
    before the window, so the heuristic already excludes it.
    """
    earlier = [s for s in stamps if s is not None and s < start]
    return max(earlier) if earlier else None


def _verified_keep(
    path: Any,
    start: datetime,
    name_based: bool,
    storage_options: dict[str, Any] | None,
    verbose: bool,
) -> bool:
    """Byte-accurate keep decision for a file that starts before *start*.

    Falls back to *name_based* when the file's last ping cannot be read, since
    over-including a file is easier to spot than silently dropping data.
    """
    from .raw_file_times import last_ping_time  # noqa: PLC0415

    last_ping = last_ping_time(path, storage_options=storage_options)
    if last_ping is None:
        if verbose:
            print(
                f"  Could not read last ping from {_path_basename(path)}; "
                f"keeping the filename-based decision ({name_based})"
            )
        return name_based
    return last_ping >= start


def filter_paths_by_file_time(
    paths: Any,
    file_time_start: Any = None,
    file_time_end: Any = None,
    verify_boundary: bool = True,
    storage_options: dict[str, Any] | None = None,
    verbose: bool = True,
) -> list:
    """Filter raw-file paths by the time span inferred from their file names.

    Works on local paths and remote URLs alike: only the final path segment is
    inspected. Bounds are inclusive and may be ISO strings or ``datetime``
    objects. Each name stamp is the file's recording *start*; its end is
    inferred from the next file's stamp, and files whose span overlaps the
    window are kept, so a file that starts before the window but records into
    it is included. Names without a parseable stamp are excluded whenever a
    bound is given. No bounds returns *paths* unchanged.

    That inferred end assumes recording ran continuously from one file to the
    next, which breaks across a gap between survey legs: the last file before
    the gap looks like it records for the whole gap. So the one file whose
    verdict depends on it has its real end read from the file itself, which
    also settles the chronologically last file, whose end the names cannot
    bound at all. At most one file per call is opened, and only its datagram
    headers are read.

    Args:
        paths: Iterable of path-like values or URL strings.
        file_time_start: Optional inclusive lower bound.
        file_time_end: Optional inclusive upper bound.
        verify_boundary: When True (default), read the boundary file's last
            ping instead of trusting the inferred end. Set False to keep the
            filter name-only, e.g. for paths that are not reachable.
        storage_options: fsspec options used to read a remote boundary file.
        verbose: Print a note when a boundary file cannot be read.

    Returns:
        list: The subset of *paths* overlapping the window, order preserved.
    """
    if file_time_start is None and file_time_end is None:
        return list(paths)

    start = _coerce_datetime(file_time_start)
    end = _coerce_datetime(file_time_end)

    paths = list(paths)
    stamps = [parse_datetime_from_filename(_path_basename(p)) for p in paths]
    next_stamps = _next_stamp_map(stamps)

    def _keep(stamp: datetime | None) -> bool:
        if stamp is None:
            return False
        if end is not None and stamp > end:
            return False
        if start is None or stamp >= start:
            return True
        # stamp < start: keep only when the next file proves the recording
        # extends into the window.
        nxt = next_stamps.get(stamp)
        return nxt is not None and nxt > start

    kept = [_keep(stamp) for stamp in stamps]

    if start is not None and verify_boundary:
        boundary = _boundary_stamp(stamps, start)
        if boundary is not None:
            for i, stamp in enumerate(stamps):
                if stamp == boundary:
                    kept[i] = _verified_keep(
                        paths[i], start, kept[i], storage_options, verbose
                    )

    return [path for path, keep in zip(paths, kept) if keep]
