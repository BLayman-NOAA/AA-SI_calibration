# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Reporting written files back to a recipe run.

The executor decides whether a cached step needs to re-run by checking that the
files it recorded are still there, so the granularity matters: recording each
single-channel file would make a recipe regenerate one a user had deleted.
"""

import sys

import pytest

from aa_si_calibration import _artifacts, _console


class _Ctx:
    """Stand-in for the recipe executor's ExecutionContext."""

    def __init__(self, artifacts_dir=None, artifact_sink=None, mode=None):
        self.artifacts_dir = artifacts_dir
        self.artifact_sink = artifact_sink
        self.mode = mode
        self.step_id = None


@pytest.fixture
def fake_context(monkeypatch):
    """Install a fake execution context both helpers will read."""

    def _install(ctx):
        monkeypatch.setattr(_artifacts, "_execution_context", lambda: ctx)
        return ctx

    return _install


def test_paths_are_recorded_relative_to_the_outputs_dir(tmp_path, fake_context):
    sink = []
    fake_context(_Ctx(artifacts_dir=tmp_path, artifact_sink=sink))
    written = tmp_path / "calibration" / "mapping_files" / "channel_mapping.yaml"
    written.parent.mkdir(parents=True)
    written.write_text("x", encoding="utf-8")

    _artifacts.record_artifact(written)

    # Forward slashes, relative: what the executor stores in its sidecar.
    assert sink == ["calibration/mapping_files/channel_mapping.yaml"]


def test_a_directory_is_recordable(tmp_path, fake_context):
    """standardize_calibration_files records its folder, not the files in it.

    Wiping the folder must rebuild it; deleting one file inside must not.
    """
    sink = []
    fake_context(_Ctx(artifacts_dir=tmp_path, artifact_sink=sink))
    folder = tmp_path / "calibration" / "single_channel_calibration_files"
    folder.mkdir(parents=True)

    _artifacts.record_artifact(folder)

    assert sink == ["calibration/single_channel_calibration_files"]


def test_a_path_outside_the_outputs_dir_is_skipped(tmp_path, fake_context):
    """Paths that cannot be relativized are dropped, not recorded absolute.

    The executor resolves recorded entries against the outputs dir, so an
    absolute entry would never be found.
    """
    sink = []
    fake_context(_Ctx(artifacts_dir=tmp_path / "outputs", artifact_sink=sink))
    (tmp_path / "outputs").mkdir()
    elsewhere = tmp_path / "elsewhere.yaml"
    elsewhere.write_text("x", encoding="utf-8")

    _artifacts.record_artifact(elsewhere)

    assert sink == []


def test_recording_is_a_noop_without_a_sink(tmp_path, fake_context):
    fake_context(_Ctx(artifacts_dir=tmp_path, artifact_sink=None))
    _artifacts.record_artifact(tmp_path / "x.yaml")  # must not raise


def test_recording_is_a_noop_outside_a_recipe_run(tmp_path, fake_context):
    fake_context(None)
    _artifacts.record_artifact(tmp_path / "x.yaml")  # must not raise


def test_recording_is_a_noop_without_the_recipe_manager(tmp_path, monkeypatch):
    """The package must keep working with aa_recipe_manager not installed."""
    monkeypatch.setitem(sys.modules, "aa_recipe_manager", None)
    monkeypatch.setitem(sys.modules, "aa_recipe_manager.executor", None)
    monkeypatch.setitem(sys.modules, "aa_recipe_manager.executor.runtime_context", None)
    assert _artifacts._execution_context() is None
    _artifacts.record_artifact(tmp_path / "x.yaml")  # must not raise


# ---------------------------------------------------------------------------
# Console shim
# ---------------------------------------------------------------------------


def test_prompt_uses_builtin_input_without_the_recipe_manager(monkeypatch):
    """Scripts with only this package installed are unaffected."""
    monkeypatch.setitem(sys.modules, "aa_recipe_manager", None)
    monkeypatch.setitem(sys.modules, "aa_recipe_manager.executor", None)
    monkeypatch.setitem(sys.modules, "aa_recipe_manager.executor.console", None)
    seen = []
    monkeypatch.setattr("builtins.input", lambda message: seen.append(message) or "1")

    assert _console.prompt("pick: ") == "1"
    assert seen == ["pick: "]


def test_prompt_uses_builtin_input_in_a_notebook(monkeypatch):
    """A notebook can import the recipe manager but is not running a step.

    ipykernel leaves sys.stdin a non-tty, so gating on tty-ness would break
    full_pipeline.ipynb.
    """
    from aa_recipe_manager.executor import console as rm_console

    monkeypatch.setattr(rm_console, "under_executor", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _message: "2")

    assert _console.prompt("pick: ") == "2"


def test_prompt_reaches_the_console_inside_a_step(monkeypatch):
    from aa_recipe_manager.executor import console as rm_console

    calls = {}

    def _interactive_prompt(message, context="", remedy=""):
        calls.update(message=message, context=context, remedy=remedy)
        return "3"

    monkeypatch.setattr(rm_console, "interactive_prompt", _interactive_prompt)
    monkeypatch.setattr(
        "builtins.input", lambda _m: pytest.fail("must not fall back to input()")
    )

    assert _console.prompt("pick: ", context="[1] a") == "3"
    assert calls["context"] == "[1] a"
    # The error a headless run sees has to say what to do instead.
    assert "conflict_resolution" in calls["remedy"]
