"""
Geometry utility functions.

"""
import math
from rdp import rdp

PI = math.pi


def convert_to_wkt(raw_points, dataset=False):
    """
    Convert list of position lists (or one list) into WKT.

    Args:
        raw_points (list): List of lists of position lists. [[[...]]]
        dataset(bool): Flag to control whether is a dataset or file conversion

    Returns:
        wkt (str): WKT representation of geometry.
    """

    multi = False
    if len(raw_points) == 2 and not dataset:
        wkt_str = 'LINESTRING'
    elif len(raw_points[0]) == 1 and dataset:
        # This is a dataset geometry that will be a single line.
        wkt_str = 'LINESTRING'
        multi = False
    else:
        wkt_str = 'MULTILINESTRING('
        multi = True

    # If this calculation is for single file need to enclose raw points
    # in a higher level list to iterate properly.
    if not dataset:
        raw_points = [raw_points]

    for positions in raw_points:
        wkt_str = wkt_str + '('
        # Test whether the first and last longitudes are exactly 180 and
        # negative -180 and whether lats are 0 and -0 because the following
        # position comparison will not recognize those values as being equal.
        # Then test if positions are the same. If so, offset the second point
        # at the resolution of our rounding.
        first_lon = f'{positions[0][0]:.5f}'
        last_lon = f'{positions[-1][0]:.5f}'
        if first_lon == '180.00000' or first_lon == '-180.00000':
            if last_lon == '180.00000' or last_lon == '-180.00000':
                # We are right on the anti-meridian but rounding has one lon
                # 180 and the other -180. Set the last lon = to the first so
                # the points test as the same if lats match.
                positions[-1][0] = positions[0][0]
        first_lat = f'{positions[0][1]:.5f}'
        last_lat = f'{positions[-1][1]:.5f}'
        if first_lat == '0.00000' or first_lat == '-0.00000':
            if last_lat == '0.00000' or last_lat == '-0.00000':
                # We are right on the equator but rounding has one lat
                # 0 and the other -0. Set the last lat = to the first so
                # the points test as the same if lons match.
                positions[-1][1] = positions[0][1]
        first_point = f'{positions[0][0]:.5f} {positions[0][1]:.5f}'
        last_point = f'{positions[-1][0]:.5f} {positions[-1][1]:.5f}'
        if first_point == last_point:
            new_lon = positions[-1][0] + 0.00001
            new_lat = positions[-1][1] + 0.00001
            positions[-1] = [new_lon, new_lat]
        for entry in positions:
            wkt_str = wkt_str + f'{entry[0]:.5f} {entry[1]:.5f}, '
        # Remove trailing space and comma and add closing '), '
        wkt_str = wkt_str[:-2] + '), '

    # Remove trailing space and comma from whole shape.
    wkt_str = wkt_str[:-2]
    if multi:
        #  Add closing ) for multistring.
        wkt_str = wkt_str + ')'
    return wkt_str




def trackline(raw_points, time_interval, method='rdp'):
    size = len(raw_points)

    # Split raw position information into components.
    time, lon, lat = separate_tuple(raw_points)

    # Get a list of flagged points -- True = good acceleration,
    # False = bad acceleration.
    flagged_list = quality_control_acceleration(size, time, time_interval, lon, lat)
    # Get the good navigation points.
    #flagged_list = [True for i in range(size)]

    good_positions = get_positions_from_flagged_list(size, lon, lat, flagged_list)
    # print(f'GOOD POSITIONS {len(good_positions)}')
    # Simplify to a single line using designated algorithm.
    if method == "rdp":
        simple_line = rdp_line_simplify(good_positions)
    else:
        print('Improper line simplification algorithm designated')
        simple_line = []

    # Convert to well known text.
    wkt = convert_to_wkt(simple_line)

    return simple_line, wkt


def quality_control_acceleration(size, time, time_interval, lon, lat):
    """
    Simplifies the list of points by removing accelerations
    that are unreasonable given a time
    threshold and acceleration limit

    Returns:
        boolean list: false for bad points and true for points to return
    """
    flag_list = [True for i in range(size)]
    acceleration_limit = 1


    time0 = time[0]
    # Loop trough finding one position per time interval.
    for t in range(1, size):
        time_diff = time[t].timestamp() - time0.timestamp()
        if time_diff >= time_interval:
            time0 = time[t]
        else:
            flag_list[t] = False
    # Always include the last point from the raw points.
    flag_list[size-1] = True

    # Calculating velocities. Needs to be a list of the velocity and the
    # index in flag_list.
    horizontal_speeds = []
    tvel = []
    # Need to be looping over flag list.
    for flag_idx, value in enumerate(flag_list):
        # check velocities only at True flags
        if value:
            # find next true flag
            next_good_idx = None
            for i in range(flag_idx+1, len(flag_list)):
                if flag_list[i]:
                    next_good_idx = i
                    break
            if next_good_idx is not None:
                # Append a tuple with the speed and the
                # index of the time of the good speed
                horizontal_speeds.append((calculate_horizontal_speed(
                    time[flag_idx], lon[flag_idx],
                    lat[flag_idx], time[next_good_idx],
                    lon[next_good_idx], lat[next_good_idx]),
                    next_good_idx))

                tvel.append((0.5 * (time[flag_idx].timestamp() +
                                    time[next_good_idx].timestamp()),
                                    next_good_idx))
            else:
                pass

    # Calculate accelerations.
    horizontal_accels = []
    tacc = []
    for j in range(len(horizontal_speeds)):
        if j+1 < len(horizontal_speeds):
            # Keep index of j+1 because the acceleration is being
            # calculated for the next position.
            horizontal_accels.append(
                (calculate_horizontal_acceleration(tvel[j][0],
                 horizontal_speeds[j][0], tvel[j+1][0],
                 horizontal_speeds[j+1][0]), tvel[j+1][1]))
            tacc.append((0.5 * (tvel[j][0] + tvel[j+1][0]), tvel[j+1][1]))

    # Flag bad accelerations.
    for a in range(len(horizontal_accels)):
        if horizontal_accels[a][0]:
            if math.fabs(horizontal_accels[a][0]) > acceleration_limit:
                flag_list[horizontal_accels[a][1]] = False
        else:
            # value is None and is a bad acceleration
            flag_list[horizontal_accels[a][1]] = False
    return flag_list


def vincenty(lon1, lat1, lon2, lat2):
        """
        Code logic from NavManager's navtools.inc.php
        Compute distance [m] and direction angles (forward and reverse) on
        an ellipsoidal earth using Vincenty's algorithm.

        Args:
            lon1: starting longitude
            lat1: starting latitude
            lon2: ending longitude
            lat2: ending latitude

        Returns:
            Returns distance [m],
            forward azimuth [degrees CW from N],
            and reverse azimuth [degrees CW from N]
        """
        deg_to_rad = PI / 180
        # W GS parameters:
        a = 6378137.0  # ellipsoid major axis[m]
        b = 6356752.314  # ellipsoid minor axis[m]
        f = 1 / 298.257223563  # ellipsoid flattening
        p1_lat = lat1 * deg_to_rad
        p2_lat = lat2 * deg_to_rad
        p1_lon = lon1 * deg_to_rad
        p2_lon = lon2 * deg_to_rad

        l = p2_lon - p1_lon

        u1 = math.atan((1 - f) * math.tan(p1_lat))
        u2 = math.atan((1 - f) * math.tan(p2_lat))

        sin_u1 = math.sin(u1)
        cos_u1 = math.cos(u1)
        sin_u2 = math.sin(u2)
        cos_u2 = math.cos(u2)

        lamb = l  # lambda
        lambdaP = 2 * PI
        if lamb == lambdaP:
            # Longitudes are exactly 180 and -180. Set lamb
            # to 0 so test in while is true.
            lamb = 0
        iter_limit = 20

        while math.fabs(lamb - lambdaP) > 1e-12 and iter_limit > 0:
            sin_lambda = math.sin(lamb)
            cos_lambda = math.cos(lamb)
            sin_sigma = math.sqrt(
                (cos_u2 * sin_lambda) * (cos_u2 * sin_lambda) +
                (cos_u1 * sin_u2 - sin_u1 * cos_u2 * cos_lambda) * (
                 cos_u1 * sin_u2 - sin_u1 * cos_u2 * cos_lambda))
            if sin_sigma == 0:
                # co-incident points
                return [0, 0, 180]
            cos_sigma = sin_u1 * sin_u2 + cos_u1 * cos_u2 * cos_lambda
            sigma = math.atan2(sin_sigma, cos_sigma)
            sin_alpha = cos_u1 * cos_u2 * sin_lambda / sin_sigma
            cos_sq_alpha = 1 - sin_alpha * sin_alpha
            cos_2_sigma_m = cos_sigma - 2 * sin_u1 * sin_u2 / cos_sq_alpha
            if sin_sigma is None:
                cos_2_sigma_m = 0
            c = f / 16 * cos_sq_alpha * (4 + f * (4 - 3 *
                                                  cos_sq_alpha))
            lambdaP = lamb
            lamb = (l + (1 - c) * f * sin_alpha * (sigma + c * sin_sigma *
                    (cos_2_sigma_m + c * cos_sigma * (-1 + 2 *
                     cos_2_sigma_m * cos_2_sigma_m))))

        u_sq = cos_sq_alpha * (a * a - b * b) / (b * b)
        a1 = 1 + u_sq / 16384 * (4096 + u_sq * (-768 + u_sq *
                                                (320 - 175 * u_sq)))
        b1 = u_sq / 1024 * (256 + u_sq * (-128 + u_sq * (74 - 47 * u_sq)))
        delta_sigma = (b1 * sin_sigma * (cos_2_sigma_m + b1 / 4 *
                       (cos_sigma * (-1 + 2 * cos_2_sigma_m *
                        cos_2_sigma_m) - b1 / 6 * cos_2_sigma_m *
                        (-3 + 4 * sin_sigma * sin_sigma) *
                        (-3 + 4 * cos_2_sigma_m * cos_2_sigma_m))))
        s = b * a1 * (sigma - delta_sigma)

        # initial and final bearings [radians]
        fwd_az = math.atan2(cos_u2 * sin_lambda, cos_u1 * sin_u2 -
                            sin_u1 * cos_u2 * cos_lambda)
        rev_az = math.atan2(cos_u1 * sin_lambda, -sin_u1 * cos_u2 +
                            cos_u1 * sin_u2 * cos_lambda)

        # convert to radians
        fwd_az = fwd_az / deg_to_rad
        rev_az = rev_az / deg_to_rad

        while fwd_az < 0.0:
            fwd_az += 360.0  # bearing should be [0,360)
        while rev_az < 0.0:
            rev_az += 360.0  # [degrees CW from N]

        return [s, fwd_az, rev_az]


def calculate_horizontal_speed(time_from, lon_from, lat_from,
                               time_to, lon_to, lat_to):
    """
    Code logic from NavManager's navtools.inc.php
    Calculate horizontal component of speed [m/s]
    Args:
        time_from: start datetime
        lon_from: start longitude
        lat_from: start latitude
        time_to: end datetime
        lon_to: end longitude
        lat_to: end latitude

    Returns:
        float: horizontal component of speed [m/s]
    """
    delta = time_to.timestamp() - time_from.timestamp()

    if (lon_from is None or lat_from is None or lon_to is None
                                                        or lat_to is None):
        horizontal_speed = None
        return horizontal_speed
    if delta != 0:
        distance, fwd_az, rev_az = vincenty(lon_from, lat_from,
                                                 lon_to, lat_to)
        horizontal_speed = distance / delta
    else:
        horizontal_speed = None

    return horizontal_speed


def calculate_horizontal_acceleration(time_from, velocity_from,
                                      time_to, velocity_to):
    """
          Code logic from NavManager's navtools.inc.php
          Calculate horizontal component of acceleration [m/s^2]
          Args:
              time_from: start datetime
              velocity_from: starting velocity [m/s]
              time_to: end datetime
              velocity_to: ending velocity [m/s]

          Returns:
              float: horizontal component of acceleration [m/s^2]
          """
    horizontal_acceleration = None

    if velocity_from is None or velocity_to is None:
        return horizontal_acceleration
    else:
        delta_velocity = velocity_to - velocity_from
        # print("delta velocity", delta_velocity)

    if time_to is None or time_from is None:
        return horizontal_acceleration
    else:
        delta = time_to - time_from
        # print("delta", delta)

    if delta != 0:
        horizontal_acceleration = delta_velocity / delta
    else:
        horizontal_acceleration = None

    return horizontal_acceleration


def separate_tuple(raw_points):
    """
    Separate the tuple into corresponding independent list
    Args:
        raw_points: list of (datetime, lon, lat) tuples

    """
    times = []
    lons = []
    lats = []
    for entry in raw_points:
        times.append(entry[0])
        lons.append(round(entry[1], 5))
        lats.append(round(entry[2], 5))
    return times, lons, lats


def get_positions_from_flagged_list(size, lon, lat, flagged_list):
    """
    Get all the good positions by comparing to the flagged list.
    Args:
        flagged_list: booleans of good and bad positions.

    """
    good_positions = []
    for i in range(size):
        if flagged_list[i]:
            good_positions.append([lon[i], lat[i]])
    return good_positions


def rdp_line_simplify(good_positions, epsilon=0.004):  #default was 0.5
    """
    Simplify the lon/lat list using Ramer-Douglas-Peucker algorithm
    Args:
        epsilon (int): Control of tolerance in RDP function.

    Returns:
        simplified line
    """
    return rdp(good_positions, epsilon=epsilon)

