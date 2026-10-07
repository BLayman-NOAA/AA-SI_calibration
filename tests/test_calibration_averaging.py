# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Tests for averaging several standardized calibration records into one."""

import pytest

from aa_si_calibration.averaging import (
    COMBINED_LIST_FIELDS,
    DECIBEL_FIELDS,
    GENERATED_FIELDS,
    LINEAR_FIELDS,
    MATCHED_FIELDS,
    TEXT_FIELDS,
    average_calibration_records,
    value_spread,
)
from aa_si_calibration.standardized_file_lib import load_standardized_calibration_schema


@pytest.fixture
def pre_and_post(calibration_record):
    """A pre-cruise and a post-cruise calibration of the same channel."""
    return [
        calibration_record("k1"),
        calibration_record(
            "k2",
            calibration_date=["2023-08-14"],
            source_filenames=["CalibrationDataFile-D20230814-T120000-38kHz.xml"],
            calibration_comments="Post-cruise calibration",
            gain_correction=[27.0],
            sa_correction=[-0.3],
            equivalent_beam_angle=-20.5,
            beamwidth_transmit_major=[7.2],
            echoangle_major=[-0.1],
            sound_speed_indicative=1500.0,
        ),
    ]


def test_every_schema_field_has_a_rule():
    """A field added to the schema must be given a rule, not silently dropped."""
    named = [
        f for group in (
            MATCHED_FIELDS, DECIBEL_FIELDS, LINEAR_FIELDS,
            COMBINED_LIST_FIELDS, TEXT_FIELDS, GENERATED_FIELDS,
        )
        for f in group
    ]
    assert len(named) == len(set(named))
    assert set(named) == set(load_standardized_calibration_schema()["properties"])


def test_gain_is_averaged_in_the_linear_domain(pre_and_post):
    """25 dB and 27 dB average to 26.11 dB, not the 26.0 an arithmetic mean gives."""
    record = average_calibration_records(pre_and_post)

    assert record["gain_correction"] == [26.11]
    assert record["sa_correction"] == [-0.2]
    assert record["equivalent_beam_angle"] == -20.6


def test_linear_quantities_are_averaged_as_they_are(pre_and_post):
    record = average_calibration_records(pre_and_post)

    assert record["beamwidth_transmit_major"] == [7.1]
    assert record["beamwidth_receive_major"] == [7.0]
    assert record["echoangle_major"] == [0.0]
    assert record["sound_speed_indicative"] == 1495.0


def test_a_null_is_skipped_rather_than_counted(calibration_record):
    record = average_calibration_records([
        calibration_record("k1", temperature=None),
        calibration_record("k2", temperature=14.0, calibration_date=["2023-08-14"]),
    ])

    assert record["temperature"] == 14.0


def test_a_field_every_source_omits_stays_out(pre_and_post):
    """transmit_bandwidth may be absent but not null, so it must not appear as null."""
    for record in pre_and_post:
        del record["transmit_bandwidth"]

    record = average_calibration_records(pre_and_post)

    assert "transmit_bandwidth" not in record
    assert "acidity" not in record


def test_dates_and_sources_are_combined_in_date_order(pre_and_post):
    """Handed over newest first, the record still lists the earlier one first."""
    record = average_calibration_records(list(reversed(pre_and_post)))

    assert record["calibration_date"] == ["2023-06-27", "2023-08-14"]
    assert record["source_filenames"] == [
        "CalibrationDataFile-D20230627-T181441-38kHz.xml",
        "CalibrationDataFile-D20230814-T120000-38kHz.xml",
    ]


def test_the_average_is_a_new_record(pre_and_post):
    record = average_calibration_records(pre_and_post, record_author="Reviewer")

    assert record["is_averaged"] is True
    assert record["record_author"] == "Reviewer"
    assert record["record_created"] != pre_and_post[0]["record_created"]
    assert "_calibration_file_key" not in record


def test_the_shared_author_is_kept_when_none_is_given(pre_and_post):
    assert average_calibration_records(pre_and_post)["record_author"] == "Calibrator"


def test_matched_fields_are_carried_over(pre_and_post):
    record = average_calibration_records(pre_and_post)

    for field in MATCHED_FIELDS:
        assert record.get(field) == pre_and_post[0].get(field), field


def test_text_that_differs_is_joined(pre_and_post):
    record = average_calibration_records(pre_and_post)

    assert record["calibration_comments"] == (
        "Pre-cruise calibration; Post-cruise calibration"
    )
    assert record["sonar_software_name"] == "EK80"


@pytest.mark.parametrize("field, value", [
    ("transmit_power", 1000.0),
    ("transmit_duration_nominal", 0.000512),
    ("sphere_diameter", 25.0),
    ("sphere_material", "copper"),
    ("transducer_serial_number", "338"),
    ("pulse_form", "1"),
    ("channel", "ES38-7 Serial No: 338"),
    ("frequency_start", 39000.0),
    ("frequency", [38500.0]),
])
def test_calibrations_that_differ_in_a_matched_field_are_refused(
    calibration_record, field, value
):
    records = [calibration_record("k1"), calibration_record("k2", **{field: value})]

    with pytest.raises(ValueError, match=f"{field} differs") as err:
        average_calibration_records(records)
    assert "k1" in str(err.value) and "k2" in str(err.value)


def test_a_difference_inside_the_match_tolerance_is_the_same_setting(calibration_record):
    """The matcher accepts 1 Hz either way, so averaging must too."""
    record = average_calibration_records([
        calibration_record("k1"),
        calibration_record("k2", frequency_end=38000.5, calibration_date=["2023-08-14"]),
    ])

    assert record["frequency_end"] == 38000.0


def test_an_average_is_not_averaged_again(calibration_record):
    """Its sources would be counted twice over."""
    with pytest.raises(ValueError, match="already an average"):
        average_calibration_records([
            calibration_record("k1"),
            calibration_record("avg", is_averaged=True),
        ])


def test_a_single_record_is_not_an_average(calibration_record):
    with pytest.raises(ValueError, match="at least two"):
        average_calibration_records([calibration_record("k1")])


def test_values_that_cannot_be_lined_up_are_refused(calibration_record):
    with pytest.raises(ValueError, match="different number of values"):
        average_calibration_records([
            calibration_record("k1"),
            calibration_record("k2", gain_correction=[25.0, 25.5]),
        ])


def _fm(calibration_record, key, frequency, gain, **overrides):
    return calibration_record(
        key,
        pulse_form="1",
        frequency_start=30000.0,
        frequency_end=45000.0,
        frequency=frequency,
        gain_correction=gain,
        **overrides,
    )


def test_fm_on_the_same_grid_averages_point_by_point(calibration_record):
    grid = [34000.0, 38000.0, 42000.0]
    record = average_calibration_records([
        _fm(calibration_record, "k1", grid, [24.0, 25.0, 26.0]),
        _fm(calibration_record, "k2", grid, [26.0, 27.0, 28.0],
            calibration_date=["2023-08-14"]),
    ])

    assert record["frequency"] == grid
    assert record["gain_correction"] == [25.11, 26.11, 27.11]


def test_fm_on_different_grids_uses_their_union_without_extrapolating(calibration_record):
    """Each point is averaged over the sources that cover it.

    k2 has no point at 35 kHz, so it is interpolated there. k1 stops at 40 kHz,
    so 45 kHz carries k2 alone rather than a value k1 never measured.
    """
    record = average_calibration_records([
        _fm(calibration_record, "k1", [30000.0, 35000.0, 40000.0], [20.0, 23.0, 22.0]),
        _fm(calibration_record, "k2", [30000.0, 40000.0, 45000.0], [20.0, 22.0, 24.0],
            calibration_date=["2023-08-14"]),
    ])

    assert record["frequency"] == [30000.0, 35000.0, 40000.0, 45000.0]
    assert record["gain_correction"] == [20.0, 22.11, 22.0, 24.0]


def test_value_spread_is_the_largest_disagreement(pre_and_post):
    assert value_spread(pre_and_post, "gain_correction") == 2.0
    assert value_spread(pre_and_post, "temperature") == 0.0
    assert value_spread(pre_and_post, "acidity") is None


def test_an_unrecorded_identity_field_takes_the_other_sources_value(calibration_record):
    """A null there means not recorded, as a missing serial does to the matcher."""
    record = average_calibration_records([
        calibration_record("k1", transducer_serial_number=None, multiplexing_found=None),
        calibration_record("k2", calibration_date=["2023-08-14"]),
    ])

    assert record["transducer_serial_number"] == "337"
    assert record["multiplexing_found"] is False


@pytest.mark.parametrize("field", ["sphere_diameter", "transmit_power", "sample_interval"])
def test_an_unrecorded_setting_is_a_difference(calibration_record, field):
    """A gain measured at an unknown setting or sphere cannot be vouched for."""
    with pytest.raises(ValueError, match=f"{field} differs"):
        average_calibration_records([
            calibration_record("k1"),
            calibration_record("k2", **{field: None}),
        ])


def test_an_fm_null_is_not_bridged_from_its_neighbours(calibration_record):
    """k1 has no beam width at 38 kHz, so that point and the gaps beside it are k2 alone."""
    record = average_calibration_records([
        _fm(calibration_record, "k1", [34000.0, 38000.0, 42000.0], [24.0, 25.0, 26.0],
            beamwidth_transmit_major=[7.0, None, 7.0]),
        _fm(calibration_record, "k2", [34000.0, 36000.0, 38000.0, 42000.0],
            [24.0, 24.5, 25.0, 26.0],
            beamwidth_transmit_major=[9.0, 9.0, 9.0, 9.0],
            calibration_date=["2023-08-14"]),
    ])

    assert record["frequency"] == [34000.0, 36000.0, 38000.0, 42000.0]
    assert record["beamwidth_transmit_major"] == [8.0, 9.0, 9.0, 8.0]
    assert record["gain_correction"] == [24.0, 24.5, 25.0, 26.0]


def test_an_invalid_result_is_refused_like_any_other(calibration_record):
    """Source files are not validated on load, so a bad value surfaces here."""
    records = [
        calibration_record("k1", sphere_diameter="38.1 mm"),
        calibration_record("k2", sphere_diameter="38.1 mm"),
    ]

    with pytest.raises(ValueError, match="not a valid standardized record"):
        average_calibration_records(records)
