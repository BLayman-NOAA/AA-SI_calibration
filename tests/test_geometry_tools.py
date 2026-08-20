# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: NOAA Fisheries
"""Tests for trackline simplification geometry.

The ``rdp`` package computes point-to-line distance with ``numpy.cross`` on
2-element vectors, which NumPy 2.5 no longer supports. ``geometery_tools``
supplies its own planar distance instead, so these tests pin that replacement
to the behaviour ``rdp.pldist`` had before the removal.
"""

from __future__ import annotations

import numpy as np
import pytest

from aa_si_calibration.simrad_reader.geometery_tools import (
    planar_point_line_distance,
    rdp_line_simplify,
)


def test_distance_to_horizontal_line():
    assert planar_point_line_distance([1.0, 3.0], [0.0, 0.0], [5.0, 0.0]) == pytest.approx(3.0)


def test_distance_to_diagonal_line():
    expected = 1.0 / np.sqrt(2.0)
    assert planar_point_line_distance([0.0, 1.0], [0.0, 0.0], [1.0, 1.0]) == pytest.approx(expected)


def test_distance_on_the_line_is_zero():
    assert planar_point_line_distance([2.0, 2.0], [0.0, 0.0], [5.0, 5.0]) == pytest.approx(0.0)


def test_degenerate_segment_falls_back_to_point_distance():
    assert planar_point_line_distance([3.0, 4.0], [0.0, 0.0], [0.0, 0.0]) == pytest.approx(5.0)


def test_distance_accepts_numpy_rows():
    points = np.array([[0.0, 0.0], [1.0, 1.0], [1.0, 0.0]])
    distance = planar_point_line_distance(points[2], points[0], points[1])
    assert distance == pytest.approx(1.0 / np.sqrt(2.0))


def test_simplify_drops_collinear_points():
    positions = [[-70.0, 42.0], [-70.1, 42.1], [-70.2, 42.2], [-70.3, 42.3]]
    assert rdp_line_simplify(positions) == [[-70.0, 42.0], [-70.3, 42.3]]


def test_simplify_keeps_a_corner():
    positions = [[-70.0, 42.0], [-70.1, 42.0], [-70.1, 42.1]]
    assert rdp_line_simplify(positions) == positions


def test_simplify_tolerates_repeated_positions():
    positions = [[-70.0, 42.0], [-70.1, 42.1], [-70.1, 42.1], [-70.2, 42.2]]
    assert rdp_line_simplify(positions) == [[-70.0, 42.0], [-70.2, 42.2]]
