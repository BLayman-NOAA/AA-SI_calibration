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
stdlib and works without it.
"""

from __future__ import annotations

import contextlib
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


def filter_paths_by_file_time(
    paths: Any,
    file_time_start: Any = None,
    file_time_end: Any = None,
) -> list:
    """Filter raw-file paths by the time span inferred from their file names.

    Works on local paths and remote URLs alike: only the final path segment is
    inspected, so nothing is opened or downloaded. Bounds are inclusive and may
    be ISO strings or ``datetime`` objects. Each name stamp is the file's
    recording *start*; its end is inferred from the next file's stamp, and
    files whose span overlaps the window are kept — so a file that starts
    before the window but records into it is included. The chronologically
    last file has no inferred end and is kept only when its own stamp falls
    inside the window. Names without a parseable stamp are excluded whenever a
    bound is given. No bounds returns *paths* unchanged.
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

    return [path for path, stamp in zip(paths, stamps) if _keep(stamp)]
