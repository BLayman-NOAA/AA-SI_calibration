# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Prompting the user from code that may run inside a recipe step.

A step's stdout goes to the run log, so a plain input() prompt is invisible
there and the run looks like it hung. The recipe manager provides helpers that
reach the terminal and refuse when there is none. This package does not depend
on aa_recipe_manager (see ``_storage``), so each helper falls back to the
builtins when it is not installed.
"""

from __future__ import annotations

#: Named in the error so an unattended run says how to fix itself.
_REMEDY = (
    'Set conflict_resolution="error" (the default) to list the conflicting '
    "calibration files and stop, then delete the unwanted single-channel "
    ".yaml and re-run. Or run this step from a terminal."
)


def require_console() -> None:
    """Raise if this run could not answer a prompt later.

    A no-op outside a recipe step. Call it before doing work that would
    otherwise have to be undone.
    """
    try:
        from aa_recipe_manager.executor.console import require_console as _require  # noqa: PLC0415
    except ImportError:
        return
    _require(remedy=_REMEDY)


def console_print(*args, **kwargs) -> None:
    """Print to the terminal rather than into the step log."""
    try:
        from aa_recipe_manager.executor.console import console_print as _print  # noqa: PLC0415
    except ImportError:
        print(*args, **kwargs)
        return
    _print(*args, **kwargs)


def prompt(message: str, context: str = "") -> str:
    """Read one line from the user.

    Outside a recipe run this is ``input()``, so notebook and script callers
    are unaffected.

    Args:
        message: The question to ask.
        context: Options the user needs in order to answer, shown first.

    Returns:
        The line the user entered.
    """
    try:
        from aa_recipe_manager.executor.console import interactive_prompt  # noqa: PLC0415
    except ImportError:
        return input(message)
    return interactive_prompt(message, context=context, remedy=_REMEDY)
