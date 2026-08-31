# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Reporting written files back to a recipe run.

The executor collects the user facing files each step wrote through
``ExecutionContext.artifact_sink``, and checks they still exist before skipping
the step from cache. This package does not depend on aa_recipe_manager (see
``_storage``), so recording is a no-op when it is not installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _execution_context() -> Any | None:
    """Return the recipe run's execution context, or None outside a run."""
    try:
        from aa_recipe_manager.executor.runtime_context import get_execution_context  # noqa: PLC0415
        return get_execution_context()
    except ImportError:
        return None


def record_artifact(path) -> None:
    """Record *path* as a user facing file this step wrote.

    Paths are recorded relative to the run's artifacts directory. A path
    outside it cannot be relativized and is skipped, which leaves the step
    unverifiable so the executor regenerates it. Directories are recordable
    too: the executor only checks existence.

    Args:
        path: File or directory that was written.
    """
    ctx = _execution_context()
    if ctx is None:
        return

    sink = getattr(ctx, "artifact_sink", None)
    artifacts_dir = getattr(ctx, "artifacts_dir", None)
    if sink is None or artifacts_dir is None:
        return

    try:
        relative = Path(path).resolve().relative_to(Path(str(artifacts_dir)).resolve())
    except (ValueError, OSError):
        return

    sink.append(relative.as_posix())
