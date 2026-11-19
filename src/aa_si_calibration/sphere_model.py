"""Theoretical target strength of a solid elastic calibration sphere.

The exact modal series solution for a solid elastic sphere in water
(Faran 1951, in the form of MacLennan 1981, The theory of solid spheres as
sonar calibration targets, Scottish Fisheries Research 22). It is what the
EK80 software and the ICES calibration reports compute a sphere's target
strength from.
"""

import numpy as np
from scipy.special import spherical_jn, spherical_yn


#: Density (kg m-3), longitudinal and transverse sound speeds (m s-1) of the
#: common calibration sphere materials (ICES CRR 326, Table 3.1).
SPHERE_MATERIALS = {
    "tungsten carbide": (14900.0, 6853.0, 4171.0),
    "copper": (8947.0, 4760.0, 2288.5),
}

#: Seawater density used when none is given, in kg m-3.
WATER_DENSITY = 1025.0


def sphere_ka(frequency, diameter, sound_speed):
    """Wavenumber times sphere radius.

    Args:
        frequency: Frequency in Hz, a number or array.
        diameter: Sphere diameter in mm.
        sound_speed: Water sound speed in m s-1.

    Returns:
        np.ndarray: ka at each frequency.
    """
    frequency = np.asarray(frequency, dtype=float)
    return np.pi * frequency * diameter / 1000.0 / sound_speed


def sphere_target_strength(
    frequency, diameter, sound_speed, material="tungsten carbide",
    water_density=WATER_DENSITY,
):
    """Theoretical target strength of a calibration sphere.

    Args:
        frequency: Frequency in Hz, a number or array; every value above zero.
        diameter: Sphere diameter in mm.
        sound_speed: Water sound speed in m s-1.
        material: A key of SPHERE_MATERIALS.
        water_density: Water density in kg m-3.

    Returns:
        np.ndarray: Target strength in dB re 1 m2 at each frequency.

    Raises:
        ValueError: If the material is not in SPHERE_MATERIALS.
    """
    if material not in SPHERE_MATERIALS:
        raise ValueError(
            f"Unknown sphere material {material!r}. "
            f"Known: {', '.join(SPHERE_MATERIALS)}."
        )
    density, longitudinal, transverse = SPHERE_MATERIALS[material]
    radius = diameter / 2000.0
    q = np.atleast_1d(sphere_ka(frequency, diameter, sound_speed))[:, None]
    q1 = q * sound_speed / longitudinal
    q2 = q * sound_speed / transverse
    order = np.arange(int(q.max()) + 21)[None, :]
    alpha = 2.0 * (density / water_density) * (transverse / sound_speed) ** 2
    beta = (density / water_density) * (longitudinal / sound_speed) ** 2 - alpha

    # Orders far above a frequency's ka add nothing to its sum but overflow
    # the Bessel functions, so they are left out frequency by frequency.
    with np.errstate(all="ignore"):
        jq, djq = spherical_jn(order, q), spherical_jn(order, q, derivative=True)
        yq, dyq = spherical_yn(order, q), spherical_yn(order, q, derivative=True)
        j1, dj1, ddj1 = _bessel_j(order, q1)
        j2, dj2, ddj2 = _bessel_j(order, q2)

        a2 = (order ** 2 + order - 2) * j2 + q2 ** 2 * ddj2
        a1 = 2 * order * (order + 1) * (q1 * dj1 - j1)
        b2 = a2 * q1 ** 2 * (beta * j1 - alpha * ddj1) - a1 * alpha * (j2 - q2 * dj2)
        b1 = q * (a2 * q1 * dj1 - a1 * j2)
        eta = np.arctan2(-(b2 * djq - b1 * jq), b2 * dyq - b1 * yq)
        terms = (-1.0) ** order * (2 * order + 1) * np.sin(eta) * np.exp(1j * eta)
    terms = np.where(order <= q + 20, terms, 0.0)
    form = -2.0 / q[:, 0] * np.sum(terms, axis=1)
    return 10 * np.log10(radius ** 2 * np.abs(form) ** 2 / 4)


def _bessel_j(order, x):
    """Spherical Bessel j and its first and second derivatives."""
    value = spherical_jn(order, x)
    first = spherical_jn(order, x, derivative=True)
    second = -2.0 / x * first - (1.0 - order * (order + 1) / x ** 2) * value
    return value, first, second
