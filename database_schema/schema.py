"""Table definitions for the calibration database.

Mirrors ``schema.md``. Each table has a dataclass giving a typed row along with
its table name and primary key, and ``SCHEMA_SQL`` holds the DDL that creates
the tables in SQLite or PostgreSQL.

Calibration values live in ``channel_calibrations`` alongside its primary key,
one row per standardized calibration file. The arrays that file carries against
its frequency axis are split into ``calibration_frequency_points``, one row per
frequency, so the axis stays aligned with the values sampled on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Optional


@dataclass
class RawFile:
    """A raw data file, identified by collection time and cruise.

    Attributes:
        collection_time: File start time, parsed from the ``D20230721-T174615``
            stem. UTC.
        cruise_id: Cruise identifier, for example ``HB1603``.
    """

    TABLE_NAME: ClassVar[str] = "raw_files"
    PRIMARY_KEY: ClassVar[tuple[str, ...]] = ("collection_time", "cruise_id")

    collection_time: datetime
    cruise_id: str


@dataclass
class RawFileChannel:
    """One channel within a raw file.

    Carries the configuration fields ``find_matching_calibration`` compares, so
    a match can be expressed as a join against ``channel_calibrations`` and
    re-derived later rather than only asserted.

    Attributes:
        collection_time: Owning file.
        cruise_id: Owning file.
        raw_channel_id: Channel name as written in the raw file, for example
            ``WBT 400479-15 ES18_ES``. Any instance suffix is part of the name,
            so the name stays unique within a file.
        transceiver_id: Transceiver identifier, the most selective match field.
        transducer_model: Transducer model, for example ``ES18-11``.
        transducer_serial_number: Skipped in matching when either side is unset.
        pulse_form: ``0`` for CW, ``1`` for FM.
        frequency_start: Start of the transmitted sweep, Hz.
        frequency_end: End of the transmitted sweep, Hz.
        transmit_power: Transmit power, W.
        transmit_duration_nominal: Nominal pulse duration, s.
        multiplexing_found: True when the channel multiplexes configurations,
            which invalidates a match.
    """

    TABLE_NAME: ClassVar[str] = "raw_file_channels"
    PRIMARY_KEY: ClassVar[tuple[str, ...]] = (
        "collection_time",
        "cruise_id",
        "raw_channel_id",
    )

    collection_time: datetime
    cruise_id: str
    raw_channel_id: str
    transceiver_id: Optional[str] = None
    transducer_model: Optional[str] = None
    transducer_serial_number: Optional[str] = None
    pulse_form: Optional[str] = None
    frequency_start: Optional[float] = None
    frequency_end: Optional[float] = None
    transmit_power: Optional[float] = None
    transmit_duration_nominal: Optional[float] = None
    multiplexing_found: Optional[bool] = None

    @property
    def raw_file_key(self) -> tuple[datetime, str]:
        """Foreign key into :class:`RawFile`."""
        return (self.collection_time, self.cruise_id)


@dataclass
class ChannelCalibration:
    """A calibrated channel configuration and its calibration values.

    The relational form of one standardized calibration file. Fields not
    described below carry the standardized field of the same name unchanged.
    Values sampled against the frequency axis are not here; they are rows of
    :class:`CalibrationFrequencyPoint`.

    Attributes:
        cal_time: Calibration date, the standardized ``calibration_date``.
        cal_channel_id: The standardized ``channel``, for example
            ``ES18 Serial No: 0``.
        config_id: Configuration label, for example ``config-1``. Assigned by
            position within a (calibration date, nominal frequency) group, so
            a channel with several configurations may draw non-consecutive
            numbers from a pool it shares with other channels at that
            frequency. See the open points in ``schema.md``.
        source_filenames: Manufacturer files the record was built from.
        source_file_paths: Full paths of those files.
        multiplexing_found: Whether multiplexing was detected on the channel.
        absorption_indicative: Absorption coefficient at calibration, dB/m.
        sound_speed_indicative: Sound speed at calibration, m/s.
        equivalent_beam_angle: Equivalent two-way beam angle, dB.
    """

    TABLE_NAME: ClassVar[str] = "channel_calibrations"
    PRIMARY_KEY: ClassVar[tuple[str, ...]] = (
        "cal_time",
        "cal_channel_id",
        "config_id",
    )

    cal_time: datetime
    cal_channel_id: str
    config_id: str

    # Required by the standardized file schema, so NOT NULL here.
    transmit_power: float
    transmit_duration_nominal: float
    absorption_indicative: float
    sound_speed_indicative: float
    sample_interval: float
    transmit_bandwidth: float
    equivalent_beam_angle: float

    record_created: Optional[datetime] = None
    record_author: Optional[str] = None
    source_filenames: list[str] = field(default_factory=list)
    source_file_paths: list[str] = field(default_factory=list)
    source_file_type: Optional[str] = None
    source_file_location: Optional[str] = None

    transceiver_id: Optional[str] = None
    transceiver_model: Optional[str] = None
    transceiver_ethernet_address: Optional[str] = None
    transceiver_serial_number: Optional[str] = None
    transceiver_number: Optional[int] = None
    transceiver_port: Optional[int] = None
    channel_instance_number: Optional[int] = None
    transducer_model: Optional[str] = None
    transducer_serial_number: Optional[str] = None

    pulse_form: Optional[str] = None
    frequency_start: Optional[float] = None
    frequency_end: Optional[float] = None
    nominal_transducer_frequency: Optional[float] = None
    multiplexing_found: Optional[bool] = None

    calibration_comments: Optional[str] = None
    calibration_version: Optional[str] = None
    calibration_acquisition_method: Optional[str] = None
    beam_type: Optional[str] = None
    sphere_diameter: Optional[float] = None
    sphere_material: Optional[str] = None

    temperature: Optional[float] = None
    salinity: Optional[float] = None
    acidity: Optional[float] = None
    pressure: Optional[float] = None

    sonar_software_name: Optional[str] = None
    sonar_software_version: Optional[str] = None

    @property
    def calibration_key(self) -> tuple[datetime, str, str]:
        """This record as a foreign key value."""
        return (self.cal_time, self.cal_channel_id, self.config_id)


@dataclass
class CalibrationFrequencyPoint:
    """One frequency of a calibration and every value sampled at it.

    The standardized file holds ``frequency`` and its companion arrays as
    parallel lists. Splitting them into rows keyed by frequency keeps them
    aligned by construction and makes them queryable, which matters for FM
    calibrations where the arrays are long.

    A CW calibration has a single row. Values absent from the source file stay
    None rather than being filled.

    Attributes:
        cal_time: Owning calibration.
        cal_channel_id: Owning calibration.
        config_id: Owning calibration.
        frequency: The frequency this row describes, Hz.
        gain_correction: Gain at this frequency, dB.
        sa_correction: Sa correction at this frequency, dB.
    """

    TABLE_NAME: ClassVar[str] = "calibration_frequency_points"
    PRIMARY_KEY: ClassVar[tuple[str, ...]] = (
        "cal_time",
        "cal_channel_id",
        "config_id",
        "frequency",
    )

    cal_time: datetime
    cal_channel_id: str
    config_id: str
    frequency: float
    gain_correction: Optional[float] = None
    sa_correction: Optional[float] = None
    beamwidth_transmit_major: Optional[float] = None
    beamwidth_receive_major: Optional[float] = None
    beamwidth_transmit_minor: Optional[float] = None
    beamwidth_receive_minor: Optional[float] = None
    echoangle_major: Optional[float] = None
    echoangle_minor: Optional[float] = None
    echoangle_major_sensitivity: Optional[float] = None
    echoangle_minor_sensitivity: Optional[float] = None

    @property
    def calibration_key(self) -> tuple[datetime, str, str]:
        """Foreign key into :class:`ChannelCalibration`."""
        return (self.cal_time, self.cal_channel_id, self.config_id)


@dataclass
class Mapping:
    """One execution of the matching algorithm.

    Attributes:
        mapping_id: Identifier for the mapping run.
        mapping_metadata: Algorithm version, field tolerances, author, run time,
            and the counts reported in the mapping summary.
    """

    TABLE_NAME: ClassVar[str] = "mapping"
    PRIMARY_KEY: ClassVar[tuple[str, ...]] = ("mapping_id",)

    mapping_id: str
    mapping_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawToCalMap:
    """The calibration a mapping run assigned to a raw file channel.

    The three calibration fields are set or unset as a group. All three unset
    records a channel the run considered and could not match.

    Attributes:
        collection_time: Raw channel being mapped.
        cruise_id: Raw channel being mapped.
        raw_channel_id: Raw channel being mapped.
        mapping_id: Mapping run that produced the row.
        cal_time: Assigned calibration, or None when unmatched.
        cal_channel_id: Assigned calibration, or None when unmatched.
        config_id: Assigned calibration, or None when unmatched.

    Raises:
        ValueError: If only some of the three calibration fields are set.
    """

    TABLE_NAME: ClassVar[str] = "raw_to_cal_map"
    PRIMARY_KEY: ClassVar[tuple[str, ...]] = (
        "collection_time",
        "cruise_id",
        "raw_channel_id",
        "mapping_id",
    )

    collection_time: datetime
    cruise_id: str
    raw_channel_id: str
    mapping_id: str
    cal_time: Optional[datetime] = None
    cal_channel_id: Optional[str] = None
    config_id: Optional[str] = None

    def __post_init__(self) -> None:
        parts = (self.cal_time, self.cal_channel_id, self.config_id)
        if any(part is not None for part in parts) and None in parts:
            raise ValueError(
                "cal_time, cal_channel_id, and config_id must all be set or "
                "all be None"
            )

    @property
    def is_matched(self) -> bool:
        """Whether the run assigned a calibration to this channel."""
        return self.cal_time is not None

    @property
    def raw_channel_key(self) -> tuple[datetime, str, str]:
        """Foreign key into :class:`RawFileChannel`."""
        return (self.collection_time, self.cruise_id, self.raw_channel_id)

    @property
    def calibration_key(self) -> Optional[tuple[datetime, str, str]]:
        """Foreign key into :class:`ChannelCalibration`, None when unmatched."""
        if not self.is_matched:
            return None
        return (self.cal_time, self.cal_channel_id, self.config_id)


TABLES = (
    RawFile,
    RawFileChannel,
    ChannelCalibration,
    CalibrationFrequencyPoint,
    Mapping,
    RawToCalMap,
)


SCHEMA_SQL = (
    """
    CREATE TABLE raw_files (
        collection_time TIMESTAMP NOT NULL,
        cruise_id       TEXT      NOT NULL,
        PRIMARY KEY (collection_time, cruise_id)
    )
    """,
    """
    CREATE TABLE raw_file_channels (
        collection_time           TIMESTAMP NOT NULL,
        cruise_id                 TEXT      NOT NULL,
        raw_channel_id            TEXT      NOT NULL,
        transceiver_id            TEXT,
        transducer_model          TEXT,
        transducer_serial_number  TEXT,
        pulse_form                TEXT,
        frequency_start           DOUBLE PRECISION,
        frequency_end             DOUBLE PRECISION,
        transmit_power            DOUBLE PRECISION,
        transmit_duration_nominal DOUBLE PRECISION,
        multiplexing_found        BOOLEAN,
        PRIMARY KEY (collection_time, cruise_id, raw_channel_id),
        FOREIGN KEY (collection_time, cruise_id)
            REFERENCES raw_files (collection_time, cruise_id)
            ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE channel_calibrations (
        cal_time       TIMESTAMP NOT NULL,
        cal_channel_id TEXT      NOT NULL,
        config_id      TEXT      NOT NULL,

        transmit_power            DOUBLE PRECISION NOT NULL,
        transmit_duration_nominal DOUBLE PRECISION NOT NULL,
        absorption_indicative     DOUBLE PRECISION NOT NULL,
        sound_speed_indicative    DOUBLE PRECISION NOT NULL,
        sample_interval           DOUBLE PRECISION NOT NULL,
        transmit_bandwidth        DOUBLE PRECISION NOT NULL,
        equivalent_beam_angle     DOUBLE PRECISION NOT NULL,

        record_created       TIMESTAMP,
        record_author        TEXT,
        source_filenames     JSON,
        source_file_paths    JSON,
        source_file_type     TEXT,
        source_file_location TEXT,

        transceiver_id               TEXT,
        transceiver_model            TEXT,
        transceiver_ethernet_address TEXT,
        transceiver_serial_number    TEXT,
        transceiver_number           INTEGER,
        transceiver_port             INTEGER,
        channel_instance_number      INTEGER,
        transducer_model             TEXT,
        transducer_serial_number     TEXT,

        pulse_form                   TEXT,
        frequency_start              DOUBLE PRECISION,
        frequency_end                DOUBLE PRECISION,
        nominal_transducer_frequency DOUBLE PRECISION,
        multiplexing_found           BOOLEAN,

        calibration_comments           TEXT,
        calibration_version            TEXT,
        calibration_acquisition_method TEXT,
        beam_type                      TEXT,
        sphere_diameter                DOUBLE PRECISION,
        sphere_material                TEXT,

        temperature DOUBLE PRECISION,
        salinity    DOUBLE PRECISION,
        acidity     DOUBLE PRECISION,
        pressure    DOUBLE PRECISION,

        sonar_software_name    TEXT,
        sonar_software_version TEXT,

        PRIMARY KEY (cal_time, cal_channel_id, config_id)
    )
    """,
    """
    CREATE TABLE calibration_frequency_points (
        cal_time       TIMESTAMP        NOT NULL,
        cal_channel_id TEXT             NOT NULL,
        config_id      TEXT             NOT NULL,
        frequency      DOUBLE PRECISION NOT NULL,

        gain_correction DOUBLE PRECISION,
        sa_correction   DOUBLE PRECISION,

        beamwidth_transmit_major DOUBLE PRECISION,
        beamwidth_receive_major  DOUBLE PRECISION,
        beamwidth_transmit_minor DOUBLE PRECISION,
        beamwidth_receive_minor  DOUBLE PRECISION,

        echoangle_major             DOUBLE PRECISION,
        echoangle_minor             DOUBLE PRECISION,
        echoangle_major_sensitivity DOUBLE PRECISION,
        echoangle_minor_sensitivity DOUBLE PRECISION,

        PRIMARY KEY (cal_time, cal_channel_id, config_id, frequency),
        FOREIGN KEY (cal_time, cal_channel_id, config_id)
            REFERENCES channel_calibrations (cal_time, cal_channel_id, config_id)
            ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE mapping (
        mapping_id       TEXT NOT NULL,
        mapping_metadata JSON,
        PRIMARY KEY (mapping_id)
    )
    """,
    """
    CREATE TABLE raw_to_cal_map (
        collection_time TIMESTAMP NOT NULL,
        cruise_id       TEXT      NOT NULL,
        raw_channel_id  TEXT      NOT NULL,
        mapping_id      TEXT      NOT NULL,
        cal_time        TIMESTAMP,
        cal_channel_id  TEXT,
        config_id       TEXT,
        PRIMARY KEY (collection_time, cruise_id, raw_channel_id, mapping_id),
        FOREIGN KEY (collection_time, cruise_id, raw_channel_id)
            REFERENCES raw_file_channels
                (collection_time, cruise_id, raw_channel_id)
            ON DELETE CASCADE,
        FOREIGN KEY (cal_time, cal_channel_id, config_id)
            REFERENCES channel_calibrations
                (cal_time, cal_channel_id, config_id),
        FOREIGN KEY (mapping_id)
            REFERENCES mapping (mapping_id)
            ON DELETE CASCADE,
        CHECK (
            (cal_time IS NULL AND cal_channel_id IS NULL AND config_id IS NULL)
            OR (cal_time IS NOT NULL AND cal_channel_id IS NOT NULL
                AND config_id IS NOT NULL)
        )
    )
    """,
    """
    CREATE INDEX raw_to_cal_map_calibration_idx
        ON raw_to_cal_map (cal_time, cal_channel_id, config_id)
    """,
    """
    CREATE INDEX raw_to_cal_map_mapping_idx
        ON raw_to_cal_map (mapping_id)
    """,
    # The first fields find_matching_calibration compares, on both sides, so
    # the match can be driven as a join rather than a scan.
    """
    CREATE INDEX raw_file_channels_match_idx
        ON raw_file_channels (transceiver_id, transducer_model, pulse_form)
    """,
    """
    CREATE INDEX channel_calibrations_match_idx
        ON channel_calibrations (transceiver_id, transducer_model, pulse_form)
    """,
)


def create_schema(connection) -> None:
    """Create the tables and indexes on an open DB-API connection.

    Args:
        connection: DB-API connection, for example from ``sqlite3.connect``.
            SQLite callers should run ``PRAGMA foreign_keys = ON`` on the
            connection first, otherwise the foreign keys are not enforced.
    """
    cursor = connection.cursor()
    for statement in SCHEMA_SQL:
        cursor.execute(statement)
    connection.commit()
