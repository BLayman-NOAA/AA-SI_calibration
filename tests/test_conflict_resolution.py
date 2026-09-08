# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Tests for resolving multiple-match calibration conflicts.

The interactive prompt, the raising "error" mode and a non-interactive caller
supplying decisions all run through :func:`apply_conflict_choices`, so these
cover that one implementation and the two front ends over it. Two of the tests
are regressions for bugs the pre-refactor code carried: replacements keyed on
``channel_id`` alone, and a globally shared removal set.
"""

import json

import pytest

from aa_si_calibration.mapping_algorithm import (
    MappingResult,
    MultipleMatchChannel,
    apply_conflict_choices,
    conflict_group_id,
    describe_conflicts,
    group_conflicts,
)


def _result(mapping_dict, multiple_matches, calibration_dict=None):
    """A MappingResult carrying just the fields conflict handling reads."""
    keys = {k for mm in multiple_matches for k in mm.matching_cal_keys}
    return MappingResult(
        mapping_dict=mapping_dict,
        calibration_dict=calibration_dict
        or {
            k: {"calibration_date": "2023-06-27", "source_filenames": [f"{k}.xml"]}
            for k in keys
        },
        multiple_matches=list(multiple_matches),
    )


def test_conflict_group_id_is_stable_and_order_independent():
    """The id depends on the candidate set, not on how it was ordered."""
    assert conflict_group_id(["b", "a"]) == conflict_group_id(["a", "b"])
    assert conflict_group_id(["a", "b"]) != conflict_group_id(["a", "c"])
    assert conflict_group_id(["a", "b"]).startswith("conflict-")


def test_conflicts_group_by_candidate_set():
    """Channels sharing candidates collapse into one conflict."""
    result = _result(
        {"a.raw": {"ch-1": "k1"}, "b.raw": {"ch-1": "k1"}},
        [
            MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"]),
            MultipleMatchChannel("b.raw", "ch-1", 2, ["k2", "k1"]),
        ],
    )
    groups = group_conflicts(result)
    assert len(groups) == 1
    assert len(next(iter(groups.values()))) == 2


def test_describe_conflicts_is_json_safe_and_complete():
    """The payload carries what a caller needs to present a choice."""
    result = _result(
        {"a.raw": {"ch-1": "k1"}},
        [MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"])],
    )
    described = describe_conflicts(result)
    json.dumps(described)

    (conflict,) = described.values()
    assert conflict["candidate_keys"] == ["k1", "k2"]
    assert conflict["affected_channel_ids"] == ["ch-1"]
    assert conflict["affected_filenames"] == ["a.raw"]
    assert conflict["affected_channel_count"] == 1
    assert {c["cal_key"] for c in conflict["candidates"]} == {"k1", "k2"}
    assert conflict["candidates"][0]["calibration_date"] == "2023-06-27"
    assert conflict["candidates"][0]["source_filenames"] == ["k1.xml"]


def _pair(**overrides):
    """Two candidates differing only in the fields given."""
    base = {
        "calibration_date": "2023-06-27",
        "source_filenames": ["a.xml"],
        "record_created": "2026-01-01T00:00:00+00:00",
        "channel": "ES120-7C",
        "transmit_power": 50.0,
        "sphere_diameter": 38.1,
    }
    other = dict(base, source_filenames=["b.xml"],
                 record_created="2026-02-02T00:00:00+00:00", **overrides)
    return {"k1": base, "k2": other}


def test_distinguishing_fields_names_what_actually_differs():
    """The field a reviewer has to weigh, not the ones that always differ."""
    result = MappingResult(
        mapping_dict={"a.raw": {"ch-1": "k1"}},
        calibration_dict=_pair(sphere_diameter=25.0),
        multiple_matches=[MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"])],
    )
    (conflict,) = describe_conflicts(result).values()
    assert conflict["distinguishing_fields"] == ["sphere_diameter"]


def test_distinguishing_fields_excludes_the_always_different_ones():
    """source_filenames and record_created differ by construction.

    Two calibration records are separate files, so those always differ; naming
    them buries the field that matters.
    """
    result = MappingResult(
        mapping_dict={"a.raw": {"ch-1": "k1"}},
        calibration_dict=_pair(),
        multiple_matches=[MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"])],
    )
    (conflict,) = describe_conflicts(result).values()
    assert conflict["distinguishing_fields"] == []
    assert conflict["candidates"][0]["source_filenames"] == ["a.xml"]


def test_distinguishing_fields_is_empty_when_a_record_is_missing():
    """Every field differs from an absent record, which reads as false detail."""
    result = MappingResult(
        mapping_dict={"a.raw": {"ch-1": "k1"}},
        calibration_dict={"k1": {"channel": "ES120-7C", "sphere_diameter": 38.1}},
        multiple_matches=[MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"])],
    )
    (conflict,) = describe_conflicts(result).values()
    assert conflict["distinguishing_fields"] == []


def test_describe_conflicts_is_empty_when_resolved():
    assert describe_conflicts(_result({}, [])) == {}


def test_applying_a_choice_rewrites_the_mapping_and_drops_the_loser():
    result = _result(
        {"a.raw": {"ch-1": "k1"}},
        [MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"])],
    )
    conflict_id = next(iter(group_conflicts(result)))

    removed = apply_conflict_choices(result, {conflict_id: "k2"})

    assert removed == {"k1"}
    assert result.mapping_dict["a.raw"]["ch-1"] == "k2"
    assert "k1" not in result.calibration_dict
    assert result.multiple_matches == []


def test_partial_choices_leave_the_rest_unresolved():
    """A caller may resolve one conflict and report the others."""
    result = _result(
        {"a.raw": {"ch-1": "k1"}, "b.raw": {"ch-2": "k3"}},
        [
            MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"]),
            MultipleMatchChannel("b.raw", "ch-2", 2, ["k3", "k4"]),
        ],
    )
    groups = group_conflicts(result)
    first = conflict_group_id(["k1", "k2"])

    apply_conflict_choices(result, {first: "k1"})

    assert len(result.multiple_matches) == 1
    assert result.multiple_matches[0].channel_id == "ch-2"
    assert set(describe_conflicts(result)) == set(groups) - {first}


def test_unknown_conflict_id_is_rejected():
    result = _result(
        {"a.raw": {"ch-1": "k1"}},
        [MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"])],
    )
    with pytest.raises(ValueError, match="Unknown conflict id"):
        apply_conflict_choices(result, {"conflict-deadbeef": "k1"})


def test_a_choice_outside_the_candidates_is_rejected():
    result = _result(
        {"a.raw": {"ch-1": "k1"}},
        [MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"])],
    )
    conflict_id = next(iter(group_conflicts(result)))
    with pytest.raises(ValueError, match="is not a candidate"):
        apply_conflict_choices(result, {conflict_id: "k9"})


def test_a_shared_channel_id_resolves_per_conflict():
    """Regression: replacements are keyed on (filename, channel_id).

    Two raw files can carry the same channel id with different configurations,
    which puts that id in two conflicts. Matching on the id alone sent both to
    the first conflict's winner.
    """
    result = _result(
        {"a.raw": {"ch-1": "k1"}, "b.raw": {"ch-1": "k3"}},
        [
            MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"]),
            MultipleMatchChannel("b.raw", "ch-1", 2, ["k3", "k4"]),
        ],
    )
    apply_conflict_choices(
        result,
        {
            conflict_group_id(["k1", "k2"]): "k2",
            conflict_group_id(["k3", "k4"]): "k4",
        },
    )

    assert result.mapping_dict["a.raw"]["ch-1"] == "k2"
    assert result.mapping_dict["b.raw"]["ch-1"] == "k4"


def test_a_key_kept_by_another_conflict_survives():
    """Regression: removals are per key, not a single global set.

    ``k2`` loses conflict one but wins conflict two, so it must stay in the
    calibration dict and keep its file.
    """
    result = _result(
        {"a.raw": {"ch-1": "k1"}, "b.raw": {"ch-2": "k2"}},
        [
            MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"]),
            MultipleMatchChannel("b.raw", "ch-2", 2, ["k2", "k3"]),
        ],
    )
    removed = apply_conflict_choices(
        result,
        {
            conflict_group_id(["k1", "k2"]): "k1",
            conflict_group_id(["k2", "k3"]): "k2",
        },
    )

    assert "k2" not in removed
    assert "k2" in result.calibration_dict
    assert removed == {"k3"}
    assert result.mapping_dict["b.raw"]["ch-2"] == "k2"


def test_a_candidate_of_an_undecided_conflict_survives(tmp_path):
    """Regression: a partial choice set must not strip what is still in play.

    ``k2`` loses the conflict being resolved but is still a candidate in one
    nobody has decided. Removing it would hand the next report a candidate with
    no date and no source file to choose by, and a choice naming a file that is
    no longer in the folder.
    """
    cal_dir = tmp_path / "single_channel_calibration_files"
    unused = tmp_path / "unused_calibration_files"
    cal_dir.mkdir()
    for key in ("k1", "k2", "k3"):
        (cal_dir / f"{key}.yaml").write_text(f"channel: {key}")

    result = _result(
        {"a.raw": {"ch-1": "k1"}, "b.raw": {"ch-2": "k2"}},
        [
            MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"]),
            MultipleMatchChannel("b.raw", "ch-2", 2, ["k2", "k3"]),
        ],
    )
    removed = apply_conflict_choices(
        result,
        {conflict_group_id(["k1", "k2"]): "k1"},
        cal_files_dir=cal_dir,
        keep_unused=True,
        unused_dir=unused,
    )

    assert removed == set()
    assert (cal_dir / "k2.yaml").exists()
    assert not (unused / "k2.yaml").exists()
    assert "k2" in result.calibration_dict

    # The conflict left over can still be presented.
    (remaining,) = describe_conflicts(result).values()
    assert remaining["candidate_keys"] == ["k2", "k3"]
    assert all(c["calibration_date"] for c in remaining["candidates"])


def test_deciding_the_rest_then_removes_it(tmp_path):
    """The deferred removal happens once nothing needs the key any more."""
    result = _result(
        {"a.raw": {"ch-1": "k1"}, "b.raw": {"ch-2": "k2"}},
        [
            MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"]),
            MultipleMatchChannel("b.raw", "ch-2", 2, ["k2", "k3"]),
        ],
    )
    apply_conflict_choices(result, {conflict_group_id(["k1", "k2"]): "k1"})
    removed = apply_conflict_choices(result, {conflict_group_id(["k2", "k3"]): "k3"})

    assert removed == {"k2"}
    assert "k2" not in result.calibration_dict
    assert result.multiple_matches == []


def test_no_choices_is_a_no_op():
    result = _result(
        {"a.raw": {"ch-1": "k1"}},
        [MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"])],
    )
    assert apply_conflict_choices(result, {}) == set()
    assert len(result.multiple_matches) == 1


def test_resolution_without_a_directory_touches_no_file(tmp_path):
    """Choices can be applied where the folder is absent or not writable."""
    result = _result(
        {"a.raw": {"ch-1": "k1"}},
        [MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"])],
    )
    conflict_id = next(iter(group_conflicts(result)))
    (tmp_path / "k1.yaml").write_text("stays: true")

    apply_conflict_choices(result, {conflict_id: "k2"}, cal_files_dir=None)

    assert (tmp_path / "k1.yaml").exists()
    assert result.mapping_dict["a.raw"]["ch-1"] == "k2"


def test_rejected_file_is_moved_to_the_unused_folder(tmp_path):
    """The web path leaves the folder exactly as interactive mode does."""
    cal_dir = tmp_path / "single_channel_calibration_files"
    unused = tmp_path / "unused_calibration_files"
    cal_dir.mkdir()
    (cal_dir / "k1.yaml").write_text("a: 1")
    (cal_dir / "k2.yaml").write_text("b: 2")

    result = _result(
        {"a.raw": {"ch-1": "k1"}},
        [MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"])],
    )
    conflict_id = next(iter(group_conflicts(result)))

    apply_conflict_choices(
        result,
        {conflict_id: "k2"},
        cal_files_dir=cal_dir,
        keep_unused=True,
        unused_dir=unused,
    )

    assert not (cal_dir / "k1.yaml").exists()
    assert (unused / "k1.yaml").exists()
    assert (cal_dir / "k2.yaml").exists()


def _mapping_step_result(monkeypatch, tmp_path, moved_aside=(), **kwargs):
    """Run build_calibration_mapping over a stubbed matcher with one conflict."""
    from aa_si_calibration import calibration as calibration_module

    result = _result(
        {"a.raw": {"ch-1": "k1"}},
        [MultipleMatchChannel("a.raw", "ch-1", 2, ["k1", "k2"])],
    )
    monkeypatch.setattr(
        calibration_module, "load_calibration_data_from_single_files",
        lambda *_a, **_k: {"channels": ["ch-1"]},
    )
    monkeypatch.setattr(
        calibration_module, "build_mapping", lambda *_a, **_k: result
    )
    monkeypatch.setattr(result, "print_summary", lambda: None, raising=False)
    monkeypatch.setattr(calibration_module, "print_mapping_preview", lambda *_a, **_k: None)
    # Returns the files it moved aside, which the report mode passes on.
    monkeypatch.setattr(
        calibration_module, "handle_unused_calibration_files",
        lambda *_a, **_k: list(moved_aside),
    )
    monkeypatch.setattr(
        calibration_module, "save_mapping_files",
        lambda *_a, **_k: (tmp_path / "mapping.yaml", tmp_path / "calibration.yaml"),
    )
    monkeypatch.setattr(
        calibration_module, "check_required_calibration_params", lambda *_a, **_k: {}
    )
    monkeypatch.setattr(
        calibration_module, "verify_calibration_file_usage", lambda *_a, **_k: []
    )

    out = calibration_module.build_calibration_mapping(
        tmp_path, raw_file_configs=[{"filename": "a.raw", "channels": []}],
        verbose=False, **kwargs,
    )
    return out, result


def test_report_mode_returns_conflicts_without_raising(monkeypatch, tmp_path):
    """The mode a caller with no terminal uses: no raise, no mapping file."""
    out, _ = _mapping_step_result(
        monkeypatch, tmp_path, conflict_resolution="report"
    )

    assert out["conflicts"], "expected the conflict to be reported"
    assert out["mapping_dict"] == {}
    assert not (tmp_path / "mapping_files" / "channel_mapping.yaml").exists()
    json.dumps(out["conflicts"])


def test_report_mode_reports_the_files_it_moved_aside(monkeypatch, tmp_path):
    """Regression: an empty list here is an all-clear the run has not earned.

    Unused files are moved before conflicts are handled, so reporting none
    would tell a caller every calibration file was used while the mapping does
    not exist yet.
    """
    out, _ = _mapping_step_result(
        monkeypatch, tmp_path,
        moved_aside=[tmp_path / "unused_calibration_files" / "k9.yaml"],
        conflict_resolution="report",
    )

    assert out["unused_file_names"] == ["k9.yaml"]
    json.dumps(out["unused_file_names"])


def test_error_mode_still_raises(monkeypatch, tmp_path):
    """The local default is unchanged."""
    with pytest.raises(ValueError, match="multiple calibration matches"):
        _mapping_step_result(monkeypatch, tmp_path, conflict_resolution="error")


def test_choices_complete_the_mapping(monkeypatch, tmp_path):
    """Feeding the reported decision back finishes the run."""
    conflict_id = conflict_group_id(["k1", "k2"])
    out, result = _mapping_step_result(
        monkeypatch, tmp_path,
        conflict_resolution="report",
        calibration_choices={conflict_id: "k2"},
        # The returned dictionaries are remapped to short keys by default, which
        # would hide which candidate won; the on-result mapping is the subject.
        short_filenames=False,
    )

    assert out["conflicts"] == {}
    assert out["mapping_dict"]["a.raw"]["ch-1"] == "k2"
    assert result.mapping_dict["a.raw"]["ch-1"] == "k2"
    assert result.multiple_matches == []


def test_unknown_conflict_mode_is_rejected(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="Unknown conflict_resolution"):
        _mapping_step_result(monkeypatch, tmp_path, conflict_resolution="nonsense")
