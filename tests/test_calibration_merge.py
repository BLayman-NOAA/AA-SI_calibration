# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Tests for merging calibrations EK80 style, and for coverage-aware combining.

A merge takes calibrations in priority order: the first is used wherever it is
valid, later ones fill only what the earlier ones leave, and what none covers
stays uncovered. Coverage is where a record has values: its valid frequency
bands, within the span of its points.
"""

import jsonschema
import pytest
import yaml

from aa_si_calibration.averaging import (
    average_calibration_records,
    calibration_coverage,
    merge_calibration_records,
    merge_coverage,
    value_spread,
)
from aa_si_calibration.calibration import standardize_calibration_files
from aa_si_calibration.calibration_keys import (
    build_average_calibration_key,
    build_merge_calibration_key,
)
from aa_si_calibration.manufacturer_file_parsers import parse_frequency_bands
from aa_si_calibration.standardized_file_lib import load_standardized_calibration_schema


@pytest.fixture
def two_spheres(fm_calibration_record):
    """A large sphere valid at both ends of 30-45 kHz, a small one in between.

    Between them they leave 39.2-39.5 kHz uncovered.
    """
    large = fm_calibration_record(
        "large",
        [30000.0, 31000.0, 32000.0, 40000.0, 41000.0, 45000.0],
        [20.0, 21.0, 22.0, 30.0, 31.0, 35.0],
        valid_frequency_bands=[[29000.0, 32500.0], [39500.0, 46000.0]],
        equivalent_beam_angle=-20.7,
        calibration_comments="38.1 mm sphere",
    )
    small = fm_calibration_record(
        "small",
        [31500.0, 33000.0, 36000.0, 39000.0, 41500.0],
        [50.0, 51.0, 52.0, 53.0, 54.0],
        valid_frequency_bands=[[31000.0, 39200.0], [41000.0, 42000.0]],
        calibration_date=["2023-07-21"],
        sphere_diameter=22.0,
        equivalent_beam_angle=-21.0,
        sound_speed_indicative=1500.0,
        calibration_comments="22 mm sphere",
    )
    return large, small


def test_frequency_bands_are_parsed_in_order():
    assert parse_frequency_bands("10000,86000;100000,110000") == [
        [10000.0, 86000.0], [100000.0, 110000.0],
    ]


def test_malformed_frequency_bands_are_skipped():
    assert parse_frequency_bands("10000,86000;bad;5,1;7;20000, 30000") == [
        [10000.0, 86000.0], [20000.0, 30000.0],
    ]
    assert parse_frequency_bands(" ; ") is None


def test_the_schema_accepts_bands_and_refuses_a_single_edge(fm_calibration_record):
    schema = load_standardized_calibration_schema()
    record = fm_calibration_record(
        "k1", [30000.0, 31000.0], [20.0, 21.0],
        valid_frequency_bands=[[29000.0, 32500.0]], is_merged=True,
    )
    record.pop("_calibration_file_key")
    jsonschema.validate(instance=record, schema=schema)

    record["valid_frequency_bands"] = [[1.0]]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=record, schema=schema)


def test_coverage_is_each_band_with_points_within_their_span(fm_calibration_record):
    record = fm_calibration_record(
        "k1", [30000.0, 31000.0, 40000.0, 41000.0], [20.0] * 4,
        valid_frequency_bands=[[10000.0, 31500.0], [33000.0, 35000.0], [39500.0, 50000.0]],
    )

    assert calibration_coverage(record) == [[30000.0, 31500.0], [39500.0, 41000.0]]


def test_coverage_without_bands_is_the_span_of_the_points(fm_calibration_record):
    record = fm_calibration_record("k1", [30000.0, 35000.0, 40000.0], [20.0] * 3)

    assert calibration_coverage(record) == [[30000.0, 40000.0]]


def test_the_first_calibration_wins_where_it_is_valid(two_spheres):
    large, small = two_spheres

    record = merge_calibration_records([small, large])

    assert record["frequency"] == [
        30000.0, 31000.0, 31500.0, 33000.0, 36000.0, 39000.0, 40000.0, 41500.0, 45000.0,
    ]
    assert record["gain_correction"] == [20.0, 21.0, 50.0, 51.0, 52.0, 53.0, 30.0, 54.0, 35.0]
    assert record["valid_frequency_bands"] == [[30000.0, 39200.0], [39500.0, 45000.0]]


def test_the_order_decides_which_calibration_supplies_each_point(two_spheres):
    large, small = two_spheres

    record = merge_calibration_records([large, small])

    assert record["frequency"] == [
        30000.0, 31000.0, 32000.0, 33000.0, 36000.0, 39000.0, 40000.0, 41000.0, 45000.0,
    ]
    assert record["gain_correction"] == [20.0, 21.0, 22.0, 51.0, 52.0, 53.0, 30.0, 31.0, 35.0]


def test_a_merge_holds_only_measured_points(two_spheres):
    large, small = two_spheres

    record = merge_calibration_records([small, large])

    measured = dict(zip(large["frequency"], large["gain_correction"]))
    measured.update(zip(small["frequency"], small["gain_correction"]))
    assert all(measured[f] == g for f, g in zip(record["frequency"], record["gain_correction"]))


def test_merge_coverage_names_each_band_and_the_holes(two_spheres):
    large, small = two_spheres

    coverage = merge_coverage([small, large])

    assert coverage["holes_hz"] == [[39200.0, 39500.0]]
    assert coverage["coverage"] == [
        {"band_hz": [30000.0, 31500.0], "source": "large"},
        {"band_hz": [31500.0, 39200.0], "source": "small"},
        {"band_hz": [39500.0, 41000.0], "source": "large"},
        {"band_hz": [41000.0, 41500.0], "source": "small"},
        {"band_hz": [41500.0, 45000.0], "source": "large"},
    ]


def test_a_merge_takes_single_values_from_the_first_calibration(two_spheres):
    large, small = two_spheres

    record = merge_calibration_records([small, large])

    assert record["equivalent_beam_angle"] == -21.0
    assert record["sound_speed_indicative"] == 1500.0
    assert record["calibration_comments"] == "22 mm sphere; 38.1 mm sphere"
    assert record["calibration_date"] == ["2023-07-21", "2023-06-27"]


def test_a_merge_lets_the_sphere_differ(two_spheres):
    large, small = two_spheres

    record = merge_calibration_records([small, large])

    assert record["is_merged"] is True
    assert record["is_averaged"] is False
    assert record["sphere_diameter"] is None
    assert record["sphere_material"] == "tungsten carbide"


def test_an_average_still_refuses_different_spheres(two_spheres):
    with pytest.raises(ValueError, match="Cannot average these calibrations: sphere_diameter differs"):
        average_calibration_records(list(two_spheres))


def test_a_merge_refuses_a_different_setting(two_spheres):
    large, small = two_spheres
    small["frequency_start"] = 31000.0

    with pytest.raises(ValueError, match="Cannot merge these calibrations: frequency_start differs"):
        merge_calibration_records([small, large])


def test_a_merge_refuses_cw_calibrations(calibration_record):
    with pytest.raises(ValueError, match="Select one of them instead"):
        merge_calibration_records([
            calibration_record("k1"),
            calibration_record("k2", sphere_diameter=22.0),
        ])


def test_a_merge_refuses_a_record_that_is_already_merged(two_spheres):
    large, small = two_spheres
    merged = {**merge_calibration_records([small, large]), "_calibration_file_key": "m"}

    with pytest.raises(ValueError, match="m: it is already a merge"):
        merge_calibration_records([merged, large])


def test_an_average_can_be_merged(fm_calibration_record, two_spheres):
    large, small = two_spheres
    post = fm_calibration_record(
        "post", large["frequency"], [g + 2.0 for g in large["gain_correction"]],
        valid_frequency_bands=large["valid_frequency_bands"],
        calibration_date=["2023-08-14"],
    )
    average = {**average_calibration_records([large, post]), "_calibration_file_key": "avg"}

    record = merge_calibration_records([average, small])

    assert record["is_merged"] is True
    assert record["is_averaged"] is True
    assert record["gain_correction"][0] == 21.11


def test_a_null_in_the_supplying_calibration_stays_null(two_spheres):
    """The small sphere has no beam width at 36 kHz; the large one is not used there."""
    large, small = two_spheres
    large["beamwidth_transmit_major"] = [9.0] * 6
    small["beamwidth_transmit_major"] = [7.0, 7.0, None, 7.0, 7.0]

    record = merge_calibration_records([small, large])

    beamwidth = dict(zip(record["frequency"], record["beamwidth_transmit_major"]))
    assert beamwidth[36000.0] is None
    assert beamwidth[33000.0] == 7.0 and beamwidth[30000.0] == 9.0


def test_a_field_the_supplier_lacks_is_not_filled_from_another(two_spheres):
    large, small = two_spheres
    large["echoangle_major"] = [0.5] * 6
    small.pop("echoangle_major")

    record = merge_calibration_records([small, large])

    echoangle = dict(zip(record["frequency"], record["echoangle_major"]))
    assert echoangle[33000.0] is None
    assert echoangle[30000.0] == 0.5


def test_a_record_with_no_point_in_its_bands_is_refused(fm_calibration_record):
    outside = fm_calibration_record(
        "k1", [30000.0, 35000.0], [20.0, 21.0], valid_frequency_bands=[[50000.0, 60000.0]],
    )

    with pytest.raises(ValueError, match="no frequency point of k1 lies inside"):
        average_calibration_records([
            outside,
            fm_calibration_record("k2", [30000.0, 35000.0], [22.0, 23.0],
                                  calibration_date=["2023-08-14"]),
        ])


def test_an_average_does_not_bridge_a_gap(fm_calibration_record):
    """k1 has nothing between 33 and 39 kHz, so 36 kHz is k2 alone.

    32.5 kHz is inside k1's first band but past its last point there, so it is
    not extrapolated either.
    """
    record = average_calibration_records([
        fm_calibration_record(
            "k1", [30000.0, 32000.0, 40000.0, 42000.0], [20.0, 20.0, 30.0, 30.0],
            valid_frequency_bands=[[29000.0, 33000.0], [39000.0, 43000.0]],
        ),
        fm_calibration_record(
            "k2", [30000.0, 32500.0, 36000.0, 42000.0], [24.0] * 4,
            valid_frequency_bands=[[29000.0, 43000.0]],
            calibration_date=["2023-08-14"],
        ),
    ])

    gain = dict(zip(record["frequency"], record["gain_correction"]))
    assert gain[32500.0] == 24.0
    assert gain[36000.0] == 24.0
    assert 20.0 < gain[30000.0] < 24.0
    assert record["valid_frequency_bands"] == [[30000.0, 42000.0]]


def test_records_without_bands_do_not_gain_the_field(fm_calibration_record):
    record = average_calibration_records([
        fm_calibration_record("k1", [30000.0, 40000.0], [20.0, 21.0]),
        fm_calibration_record("k2", [30000.0, 40000.0], [22.0, 23.0],
                              calibration_date=["2023-08-14"]),
    ])

    assert "valid_frequency_bands" not in record
    assert "is_merged" not in record


def test_the_overlap_spread_of_a_merge(two_spheres):
    """Largest where both cover: at 31.5 kHz the small sphere measured 50 dB
    and the large one, between its 21 and 22 dB points, gives 21.5 dB."""
    large, small = two_spheres

    assert value_spread([small, large], "gain_correction") == 28.5


def test_a_merge_key_depends_on_the_order(two_spheres):
    large, small = two_spheres
    record = merge_calibration_records([small, large])

    forward = build_merge_calibration_key(record, ["small", "large"])
    backward = build_merge_calibration_key(record, ["large", "small"])

    assert forward.startswith("2023-07-21+2023-06-27__38000__merge-")
    assert forward != backward
    assert build_average_calibration_key(record, ["small", "large"]) == (
        build_average_calibration_key(record, ["large", "small"])
    )


@pytest.fixture(scope="module")
def standardized_fm(tmp_path_factory, request):
    """The EK80 FM example folder, standardized once for these tests."""
    cal_dir = request.config.rootpath / "notebooks/example_data/ek80_FM_cal_file_input_folder"
    out = tmp_path_factory.mktemp("standardized_fm")
    standardize_calibration_files(
        cal_dir, out, frequencies=[], cruise_id="TEST", record_author="Tester", verbose=False,
    )
    folder = out / "single_channel_calibration_files"

    def load(stem):
        record = yaml.safe_load((folder / f"{stem}.yaml").read_text())
        record["_calibration_file_key"] = stem
        return record

    return load


def test_fm_records_carry_their_bands_and_cw_records_do_not(standardized_fm):
    fm = standardized_fm("2023-07-20__200000__config-2")
    cw = standardized_fm("2023-07-20__200000__config-1")

    assert fm["valid_frequency_bands"][3:6] == [
        [140000.0, 163000.0], [180000.0, 205000.0], [214000.0, 240000.0],
    ]
    assert "valid_frequency_bands" not in cw
    assert "is_merged" not in fm and "is_merged" not in cw


def test_the_two_200_khz_spheres_merge_with_two_holes(standardized_fm):
    """The 22 mm sphere (2023-07-21) over the 38.1 mm sphere (2023-07-20)."""
    large = standardized_fm("2023-07-20__200000__config-2")
    small = standardized_fm("2023-07-21__200000__config-1")

    record = merge_calibration_records([small, large])
    coverage = merge_coverage([small, large])

    assert coverage["holes_hz"] == [[163000.0, 170010.0], [240000.0, 245000.0]]

    def covers(rec, frequency):
        return any(low <= frequency <= high for low, high in calibration_coverage(rec))

    assert covers(record, 210000.0)
    assert not covers(large, 210000.0)
    assert record["sphere_diameter"] is None
