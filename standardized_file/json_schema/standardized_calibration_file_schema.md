# Standardized Calibration File

- [1. Property `Standardized Calibration File > source_filenames`](#source_filenames)
  - [1.1. Standardized Calibration File > source_filenames > source_filenames items](#source_filenames_items)
- [2. Property `Standardized Calibration File > record_created`](#record_created)
- [3. Property `Standardized Calibration File > record_author`](#record_author)
- [4. Property `Standardized Calibration File > channel`](#channel)
- [5. Property `Standardized Calibration File > transceiver_id`](#transceiver_id)
- [6. Property `Standardized Calibration File > transceiver_model`](#transceiver_model)
- [7. Property `Standardized Calibration File > transceiver_ethernet_address`](#transceiver_ethernet_address)
- [8. Property `Standardized Calibration File > transceiver_serial_number`](#transceiver_serial_number)
- [9. Property `Standardized Calibration File > transceiver_number`](#transceiver_number)
- [10. Property `Standardized Calibration File > transceiver_port`](#transceiver_port)
- [11. Property `Standardized Calibration File > channel_instance_number`](#channel_instance_number)
- [12. Property `Standardized Calibration File > transducer_model`](#transducer_model)
- [13. Property `Standardized Calibration File > transducer_serial_number`](#transducer_serial_number)
- [14. Property `Standardized Calibration File > pulse_form`](#pulse_form)
- [15. Property `Standardized Calibration File > frequency_start`](#frequency_start)
- [16. Property `Standardized Calibration File > frequency_end`](#frequency_end)
- [17. Property `Standardized Calibration File > nominal_transducer_frequency`](#nominal_transducer_frequency)
- [18. Property `Standardized Calibration File > transmit_power`](#transmit_power)
- [19. Property `Standardized Calibration File > transmit_duration_nominal`](#transmit_duration_nominal)
- [20. Property `Standardized Calibration File > multiplexing_found`](#multiplexing_found)
- [21. Property `Standardized Calibration File > calibration_date`](#calibration_date)
- [22. Property `Standardized Calibration File > calibration_comments`](#calibration_comments)
- [23. Property `Standardized Calibration File > calibration_version`](#calibration_version)
- [24. Property `Standardized Calibration File > absorption_indicative`](#absorption_indicative)
- [25. Property `Standardized Calibration File > sound_speed_indicative`](#sound_speed_indicative)
- [26. Property `Standardized Calibration File > temperature`](#temperature)
- [27. Property `Standardized Calibration File > salinity`](#salinity)
- [28. Property `Standardized Calibration File > acidity`](#acidity)
- [29. Property `Standardized Calibration File > pressure`](#pressure)
- [30. Property `Standardized Calibration File > sample_interval`](#sample_interval)
- [31. Property `Standardized Calibration File > transmit_bandwidth`](#transmit_bandwidth)
- [32. Property `Standardized Calibration File > beam_type`](#beam_type)
- [33. Property `Standardized Calibration File > calibration_acquisition_method`](#calibration_acquisition_method)
- [34. Property `Standardized Calibration File > sphere_diameter`](#sphere_diameter)
- [35. Property `Standardized Calibration File > sphere_material`](#sphere_material)
- [36. Property `Standardized Calibration File > source_file_type`](#source_file_type)
- [37. Property `Standardized Calibration File > source_file_location`](#source_file_location)
- [38. Property `Standardized Calibration File > sonar_software_version`](#sonar_software_version)
- [39. Property `Standardized Calibration File > sonar_software_name`](#sonar_software_name)
- [40. Property `Standardized Calibration File > equivalent_beam_angle`](#equivalent_beam_angle)
- [41. Property `Standardized Calibration File > gain_correction`](#gain_correction)
  - [41.1. Standardized Calibration File > gain_correction > gain_correction items](#gain_correction_items)
- [42. Property `Standardized Calibration File > sa_correction`](#sa_correction)
  - [42.1. Standardized Calibration File > sa_correction > sa_correction items](#sa_correction_items)
- [43. Property `Standardized Calibration File > frequency`](#frequency)
  - [43.1. Standardized Calibration File > frequency > frequency items](#frequency_items)
- [44. Property `Standardized Calibration File > beamwidth_transmit_major`](#beamwidth_transmit_major)
  - [44.1. Standardized Calibration File > beamwidth_transmit_major > beamwidth_transmit_major items](#beamwidth_transmit_major_items)
- [45. Property `Standardized Calibration File > beamwidth_receive_major`](#beamwidth_receive_major)
  - [45.1. Standardized Calibration File > beamwidth_receive_major > beamwidth_receive_major items](#beamwidth_receive_major_items)
- [46. Property `Standardized Calibration File > beamwidth_transmit_minor`](#beamwidth_transmit_minor)
  - [46.1. Standardized Calibration File > beamwidth_transmit_minor > beamwidth_transmit_minor items](#beamwidth_transmit_minor_items)
- [47. Property `Standardized Calibration File > beamwidth_receive_minor`](#beamwidth_receive_minor)
  - [47.1. Standardized Calibration File > beamwidth_receive_minor > beamwidth_receive_minor items](#beamwidth_receive_minor_items)
- [48. Property `Standardized Calibration File > echoangle_major`](#echoangle_major)
  - [48.1. Standardized Calibration File > echoangle_major > echoangle_major items](#echoangle_major_items)
- [49. Property `Standardized Calibration File > echoangle_minor`](#echoangle_minor)
  - [49.1. Standardized Calibration File > echoangle_minor > echoangle_minor items](#echoangle_minor_items)
- [50. Property `Standardized Calibration File > echoangle_major_sensitivity`](#echoangle_major_sensitivity)
  - [50.1. Standardized Calibration File > echoangle_major_sensitivity > echoangle_major_sensitivity items](#echoangle_major_sensitivity_items)
- [51. Property `Standardized Calibration File > echoangle_minor_sensitivity`](#echoangle_minor_sensitivity)
  - [51.1. Standardized Calibration File > echoangle_minor_sensitivity > echoangle_minor_sensitivity items](#echoangle_minor_sensitivity_items)
- [52. Property `Standardized Calibration File > source_file_paths`](#source_file_paths)
  - [52.1. Standardized Calibration File > source_file_paths > source_file_paths items](#source_file_paths_items)

**Title:** Standardized Calibration File

|                           |             |
| ------------------------- | ----------- |
| **Type**                  | `object`    |
| **Required**              | No          |
| **Additional properties** | Not allowed |

**Description:** Schema for a single-channel standardized sonar calibration file. Each file contains calibration parameters for one sonar channel. Note that many parameter definitions follow the SONAR-netCDF4 convention for sonar data (v2.0, ICES WGFAST Open Data subgroup, generated 2025-02-22 03:11:38 UTC). See https://htmlpreview.github.io/?https://github.com/ices-publications/SONAR-netCDF4/blob/master/Formatted_docs/crr341.html for the full reference.

**Example:**

```json
{
    "source_filenames": [
        "HBB_018kHz_18July2016.cal"
    ],
    "record_created": "2025-12-10T18:05:48.252383+00:00",
    "record_author": null,
    "channel": "GPT  18 kHz 009072056b0e 2-1 ES18-11",
    "transceiver_id": "009072056b0e",
    "transceiver_model": "GPT",
    "transceiver_ethernet_address": "009072056b0e",
    "transceiver_serial_number": null,
    "transceiver_number": 2,
    "transceiver_port": 1,
    "channel_instance_number": 1,
    "transducer_model": "ES18-11",
    "transducer_serial_number": null,
    "pulse_form": null,
    "frequency_start": 18000.0,
    "frequency_end": 18000.0,
    "nominal_transducer_frequency": 18000,
    "transmit_power": 1000.0,
    "transmit_duration_nominal": 0.001024,
    "multiplexing_found": false,
    "calibration_date": "7/18/2016",
    "calibration_comments": "HB Bigelow 18 kHz calibration, 38.1-mm WC sphere, Newport naval anchorage south of bridge, 18 July 2016",
    "calibration_version": null,
    "absorption_indicative": 0.0018,
    "sound_speed_indicative": 1522.6,
    "temperature": null,
    "salinity": null,
    "acidity": null,
    "pressure": null,
    "sample_interval": 0.000128,
    "transmit_bandwidth": 1570.0,
    "beam_type": null,
    "calibration_acquisition_method": null,
    "sphere_diameter": null,
    "sphere_material": null,
    "source_file_type": ".cal",
    "source_file_location": null,
    "sonar_software_version": "2.4.3",
    "sonar_software_name": null,
    "equivalent_beam_angle": -17.0,
    "gain_correction": [
        23.08
    ],
    "sa_correction": [
        -0.76
    ],
    "frequency": [
        18000.0
    ],
    "beamwidth_transmit_major": [
        11.06
    ],
    "beamwidth_receive_major": [
        11.06
    ],
    "beamwidth_transmit_minor": [
        10.56
    ],
    "beamwidth_receive_minor": [
        10.56
    ],
    "echoangle_major": [
        0.01
    ],
    "echoangle_minor": [
        -0.07
    ],
    "echoangle_major_sensitivity": [
        13.9
    ],
    "echoangle_minor_sensitivity": [
        13.9
    ],
    "source_file_paths": null
}
```

| Property                                                             | Pattern | Type                    | Deprecated | Definition | Title/Description                                       |
| -------------------------------------------------------------------- | ------- | ----------------------- | ---------- | ---------- | ------------------------------------------------------- |
| - [source_filenames](#source_filenames )                             | No      | array of string or null | No         | -          | Channel source filenames                                |
| - [record_created](#record_created )                                 | No      | string or null          | No         | -          | Record creation timestamp                               |
| - [record_author](#record_author )                                   | No      | string or null          | No         | -          | Record author                                           |
| + [channel](#channel )                                               | No      | string                  | No         | -          | Channel identifier                                      |
| - [transceiver_id](#transceiver_id )                                 | No      | string or null          | No         | -          | Transceiver identifier                                  |
| - [transceiver_model](#transceiver_model )                           | No      | string or null          | No         | -          | Transceiver model                                       |
| - [transceiver_ethernet_address](#transceiver_ethernet_address )     | No      | string or null          | No         | -          | Transceiver Ethernet address                            |
| - [transceiver_serial_number](#transceiver_serial_number )           | No      | string or null          | No         | -          | Transceiver serial number                               |
| - [transceiver_number](#transceiver_number )                         | No      | integer or null         | No         | -          | Transceiver number                                      |
| - [transceiver_port](#transceiver_port )                             | No      | integer or null         | No         | -          | Transceiver port                                        |
| - [channel_instance_number](#channel_instance_number )               | No      | integer or null         | No         | -          | Channel instance number                                 |
| - [transducer_model](#transducer_model )                             | No      | string or null          | No         | -          | Transducer model                                        |
| - [transducer_serial_number](#transducer_serial_number )             | No      | string or null          | No         | -          | Transducer serial number                                |
| - [pulse_form](#pulse_form )                                         | No      | string or null          | No         | -          | Pulse form                                              |
| - [frequency_start](#frequency_start )                               | No      | number or null          | No         | -          | Start frequency                                         |
| - [frequency_end](#frequency_end )                                   | No      | number or null          | No         | -          | End frequency                                           |
| - [nominal_transducer_frequency](#nominal_transducer_frequency )     | No      | number or null          | No         | -          | Nominal transducer frequency                            |
| - [transmit_power](#transmit_power )                                 | No      | number                  | No         | -          | Nominal transmit power                                  |
| - [transmit_duration_nominal](#transmit_duration_nominal )           | No      | number                  | No         | -          | Nominal duration of transmitted pulse                   |
| - [multiplexing_found](#multiplexing_found )                         | No      | boolean or null         | No         | -          | Multiplexing found                                      |
| - [calibration_date](#calibration_date )                             | No      | string or null          | No         | -          | Calibration date                                        |
| - [calibration_comments](#calibration_comments )                     | No      | string or null          | No         | -          | Calibration comments                                    |
| - [calibration_version](#calibration_version )                       | No      | string or null          | No         | -          | Calibration processing version                          |
| - [absorption_indicative](#absorption_indicative )                   | No      | number                  | No         | -          | Indicative acoustic absorption                          |
| - [sound_speed_indicative](#sound_speed_indicative )                 | No      | number                  | No         | -          | Indicative sound speed                                  |
| - [temperature](#temperature )                                       | No      | number or null          | No         | -          | Water temperature                                       |
| - [salinity](#salinity )                                             | No      | number or null          | No         | -          | Water salinity                                          |
| - [acidity](#acidity )                                               | No      | number or null          | No         | -          | Water acidity (pH)                                      |
| - [pressure](#pressure )                                             | No      | number or null          | No         | -          | Water pressure                                          |
| - [sample_interval](#sample_interval )                               | No      | number                  | No         | -          | Interval between recorded raw data samples              |
| - [transmit_bandwidth](#transmit_bandwidth )                         | No      | number                  | No         | -          | Nominal bandwidth of transmitted pulse                  |
| - [beam_type](#beam_type )                                           | No      | string or null          | No         | -          | Transducer beam type                                    |
| - [calibration_acquisition_method](#calibration_acquisition_method ) | No      | string or null          | No         | -          | Calibration acquisition method                          |
| - [sphere_diameter](#sphere_diameter )                               | No      | number or null          | No         | -          | Calibration sphere diameter                             |
| - [sphere_material](#sphere_material )                               | No      | string or null          | No         | -          | Calibration sphere material                             |
| - [source_file_type](#source_file_type )                             | No      | string or null          | No         | -          | Channel source file type                                |
| - [source_file_location](#source_file_location )                     | No      | string or null          | No         | -          | Channel source file location                            |
| - [sonar_software_version](#sonar_software_version )                 | No      | string or null          | No         | -          | Sonar software version                                  |
| - [sonar_software_name](#sonar_software_name )                       | No      | string or null          | No         | -          | Sonar software name                                     |
| - [equivalent_beam_angle](#equivalent_beam_angle )                   | No      | number                  | No         | -          | Equivalent beam angle                                   |
| - [gain_correction](#gain_correction )                               | No      | array of number or null | No         | -          | Gain correction                                         |
| - [sa_correction](#sa_correction )                                   | No      | array of number or null | No         | -          | Sa correction                                           |
| + [frequency](#frequency )                                           | No      | array of number or null | No         | -          | Acoustic frequency                                      |
| - [beamwidth_transmit_major](#beamwidth_transmit_major )             | No      | array or null           | No         | -          | Half power one-way transmit beam width along major axis |
| - [beamwidth_receive_major](#beamwidth_receive_major )               | No      | array or null           | No         | -          | Half power one-way receive beam width along major axis  |
| - [beamwidth_transmit_minor](#beamwidth_transmit_minor )             | No      | array or null           | No         | -          | Half power one-way transmit beam width along minor axis |
| - [beamwidth_receive_minor](#beamwidth_receive_minor )               | No      | array or null           | No         | -          | Half power one-way receive beam width along minor axis  |
| - [echoangle_major](#echoangle_major )                               | No      | array or null           | No         | -          | Echo arrival angle in the major beam coordinate         |
| - [echoangle_minor](#echoangle_minor )                               | No      | array or null           | No         | -          | Echo arrival angle in the minor beam coordinate         |
| - [echoangle_major_sensitivity](#echoangle_major_sensitivity )       | No      | array of number or null | No         | -          | Major angle scaling factor                              |
| - [echoangle_minor_sensitivity](#echoangle_minor_sensitivity )       | No      | array of number or null | No         | -          | Minor angle scaling factor                              |
| - [source_file_paths](#source_file_paths )                           | No      | array of string or null | No         | -          | Channel source file paths                               |

## <a name="source_filenames"></a>1. Property `Standardized Calibration File > source_filenames`

**Title:** Channel source filenames

|              |                           |
| ------------ | ------------------------- |
| **Type**     | `array of string or null` |
| **Required** | No                        |

**Description:** List of calibration source files that produced this channel's parameters.

**Example:**

```json
[
    "HBB_018kHz_18July2016.cal"
]
```

|                      | Array restrictions |
| -------------------- | ------------------ |
| **Min items**        | N/A                |
| **Max items**        | N/A                |
| **Items unicity**    | False              |
| **Additional items** | False              |
| **Tuple validation** | See below          |

| Each item of this array must be                   | Description |
| ------------------------------------------------- | ----------- |
| [source_filenames items](#source_filenames_items) | -           |

### <a name="source_filenames_items"></a>1.1. Standardized Calibration File > source_filenames > source_filenames items

|              |          |
| ------------ | -------- |
| **Type**     | `string` |
| **Required** | No       |

## <a name="record_created"></a>2. Property `Standardized Calibration File > record_created`

**Title:** Record creation timestamp

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |
| **Format**   | `date-time`      |

**Description:** ISO8601 timestamp indicating when this calibration record was created in the system. Auto-populated when derived from raw files or manufacturer calibration files; can be manually filled for user-created records.

**Example:**

```json
"2026-02-11T15:30:00.000000+00:00"
```

## <a name="record_author"></a>3. Property `Standardized Calibration File > record_author`

**Title:** Record author

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Name or identifier of the individual who generated this calibration record.

**Examples:**

```json
"Jane Smith"
```

```json
"jsmith@noaa.gov"
```

## <a name="channel"></a>4. Property `Standardized Calibration File > channel`

**Title:** Channel identifier

|              |          |
| ------------ | -------- |
| **Type**     | `string` |
| **Required** | Yes      |

**Description:** Identifier of the transceiver/channel.

## <a name="transceiver_id"></a>5. Property `Standardized Calibration File > transceiver_id`

**Title:** Transceiver identifier

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Unique identifier for the transceiver unit.

## <a name="transceiver_model"></a>6. Property `Standardized Calibration File > transceiver_model`

**Title:** Transceiver model

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Model or type designation of the transceiver.

## <a name="transceiver_ethernet_address"></a>7. Property `Standardized Calibration File > transceiver_ethernet_address`

**Title:** Transceiver Ethernet address

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Network MAC address or Ethernet identifier for the transceiver.

## <a name="transceiver_serial_number"></a>8. Property `Standardized Calibration File > transceiver_serial_number`

**Title:** Transceiver serial number

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Manufacturer serial number for the transceiver unit.

## <a name="transceiver_number"></a>9. Property `Standardized Calibration File > transceiver_number`

**Title:** Transceiver number

|              |                   |
| ------------ | ----------------- |
| **Type**     | `integer or null` |
| **Required** | No                |

**Description:** Numeric identifier or channel number for the transceiver.

Numeric constraints: >= 0

| Restrictions |        |
| ------------ | ------ |
| **Minimum**  | &ge; 0 |

## <a name="transceiver_port"></a>10. Property `Standardized Calibration File > transceiver_port`

**Title:** Transceiver port

|              |                   |
| ------------ | ----------------- |
| **Type**     | `integer or null` |
| **Required** | No                |

**Description:** Hardware port/channel on the transceiver. For EK60: from channel ID pattern (e.g., '3-1' -> port 1). For EK80: from HWChannelConfiguration attribute.

Numeric constraints: >= 0

| Restrictions |        |
| ------------ | ------ |
| **Minimum**  | &ge; 0 |

## <a name="channel_instance_number"></a>11. Property `Standardized Calibration File > channel_instance_number`

**Title:** Channel instance number

|              |                   |
| ------------ | ----------------- |
| **Type**     | `integer or null` |
| **Required** | No                |

**Description:** Software channel instance number. For EK80: extracted from ChannelID suffix (e.g., '_2'). For EK60: always 1.

Numeric constraints: >= 1

| Restrictions |        |
| ------------ | ------ |
| **Minimum**  | &ge; 1 |

## <a name="transducer_model"></a>12. Property `Standardized Calibration File > transducer_model`

**Title:** Transducer model

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Model or type designation of the transducer.

## <a name="transducer_serial_number"></a>13. Property `Standardized Calibration File > transducer_serial_number`

**Title:** Transducer serial number

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Manufacturer serial number for the transducer.

## <a name="pulse_form"></a>14. Property `Standardized Calibration File > pulse_form`

**Title:** Pulse form

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Type of transmitted pulse (e.g., CW, FM).

## <a name="frequency_start"></a>15. Property `Standardized Calibration File > frequency_start`

**Title:** Start frequency

|              |                  |
| ------------ | ---------------- |
| **Type**     | `number or null` |
| **Required** | No               |

**Description:** Start frequency for FM pulses or nominal frequency for CW pulses.

Precision: 10

Units: Hz

Numeric constraints: >= 0.0

## <a name="frequency_end"></a>16. Property `Standardized Calibration File > frequency_end`

**Title:** End frequency

|              |                  |
| ------------ | ---------------- |
| **Type**     | `number or null` |
| **Required** | No               |

**Description:** End frequency for FM pulses or nominal frequency for CW pulses.

Precision: 10

Units: Hz

Numeric constraints: >= 0.0

## <a name="nominal_transducer_frequency"></a>17. Property `Standardized Calibration File > nominal_transducer_frequency`

**Title:** Nominal transducer frequency

|              |                  |
| ------------ | ---------------- |
| **Type**     | `number or null` |
| **Required** | No               |

**Description:** Nominal CW operating frequency of the transducer in Hz. For EK60, this equals the channel frequency. For EK80 in FM mode, this provides the transducer's native CW operating frequency (e.g., 38000 Hz for an ES38-7 transducer) which is not otherwise directly available from the broadband frequency array.

Precision: 0

Units: Hz

Numeric constraints: >= 0.0

**Examples:**

```json
18000
```

```json
38000
```

```json
120000
```

```json
200000
```

## <a name="transmit_power"></a>18. Property `Standardized Calibration File > transmit_power`

**Title:** Nominal transmit power

|              |          |
| ------------ | -------- |
| **Type**     | `number` |
| **Required** | No       |

**Description:** Electrical transmit power used for the ping (required for type 1 conversion equations).

Precision: 10

Reference: SONAR-netCDF4 2.0 Sonar/Beam_group.transmit_power

Units: W

Numeric constraints: >= 0.0

**Examples:**

```json
1000.0
```

```json
300.0
```

## <a name="transmit_duration_nominal"></a>19. Property `Standardized Calibration File > transmit_duration_nominal`

**Title:** Nominal duration of transmitted pulse

|              |          |
| ------------ | -------- |
| **Type**     | `number` |
| **Required** | No       |

**Description:** Duration of the transmitted pulse prior to reception (not the effective duration).

Precision: 6

Reference: SONAR-netCDF4 2.0 Sonar/Beam_group.transmit_duration_nominal

Units: s

Numeric constraints: >= 0.0

**Example:**

```json
0.001024
```

## <a name="multiplexing_found"></a>20. Property `Standardized Calibration File > multiplexing_found`

**Title:** Multiplexing found

|              |                   |
| ------------ | ----------------- |
| **Type**     | `boolean or null` |
| **Required** | No                |

**Description:** Indicates if multiplexing is enabled for this channel. For EK60: derived from multiple ports on same transceiver. For EK80: from Multiplexing XML attribute.

## <a name="calibration_date"></a>21. Property `Standardized Calibration File > calibration_date`

**Title:** Calibration date

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Date associated with the calibration measurements. Derived from calibration report files, so format is free-form.

**Example:**

```json
"7/18/2016"
```

## <a name="calibration_comments"></a>22. Property `Standardized Calibration File > calibration_comments`

**Title:** Calibration comments

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Narrative notes captured during the calibration event.

## <a name="calibration_version"></a>23. Property `Standardized Calibration File > calibration_version`

**Title:** Calibration processing version

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Software or procedure version used when producing these calibration parameters. *add specifics

## <a name="absorption_indicative"></a>24. Property `Standardized Calibration File > absorption_indicative`

**Title:** Indicative acoustic absorption

|              |          |
| ------------ | -------- |
| **Type**     | `number` |
| **Required** | No       |

**Description:** Indicative absorption values used to calculate the time-varied gain (TVG) in the absence of detailed data.

Precision: 10

Reference: SONAR-netCDF4 2.0 Environment.absorption_indicative

Units: dB/m

Numeric constraints: >= 0.0

**Examples:**

```json
0.01
```

```json
0.02
```

## <a name="sound_speed_indicative"></a>25. Property `Standardized Calibration File > sound_speed_indicative`

**Title:** Indicative sound speed

|              |          |
| ------------ | -------- |
| **Type**     | `number` |
| **Required** | No       |

**Description:** Mean sound speed in water used to calculate echo range when detailed profiles are unavailable.

Precision: 2

Reference: SONAR-netCDF4 2.0 Environment.sound_speed_indicative

Units: m/s

Numeric constraints: >= 0.0

**Example:**

```json
1522.6
```

## <a name="temperature"></a>26. Property `Standardized Calibration File > temperature`

**Title:** Water temperature

|              |                  |
| ------------ | ---------------- |
| **Type**     | `number or null` |
| **Required** | No               |

**Description:** Ambient water temperature recorded during calibration.

Precision: 2

Units: degC

## <a name="salinity"></a>27. Property `Standardized Calibration File > salinity`

**Title:** Water salinity

|              |                  |
| ------------ | ---------------- |
| **Type**     | `number or null` |
| **Required** | No               |

**Description:** Water salinity during calibration.

Precision: 10

Units: psu

Numeric constraints: >= 0.0

## <a name="acidity"></a>28. Property `Standardized Calibration File > acidity`

**Title:** Water acidity (pH)

|              |                  |
| ------------ | ---------------- |
| **Type**     | `number or null` |
| **Required** | No               |

**Description:** Water pH (acidity) during calibration, used to calculate absorption. Typical ocean values range from 7.5 to 8.5.

Precision: 2

## <a name="pressure"></a>29. Property `Standardized Calibration File > pressure`

**Title:** Water pressure

|              |                  |
| ------------ | ---------------- |
| **Type**     | `number or null` |
| **Required** | No               |

**Description:** Water pressure during calibration, used to calculate sound speed and absorption.

Precision: 2

Units: dbar

Numeric constraints: >= 0.0

## <a name="sample_interval"></a>30. Property `Standardized Calibration File > sample_interval`

**Title:** Interval between recorded raw data samples

|              |          |
| ------------ | -------- |
| **Type**     | `number` |
| **Required** | No       |

**Description:** Time between individual samples along a beam (common for all beams in a ping).

Precision: 6

Reference: SONAR-netCDF4 2.0 Sonar/Beam_group.sample_interval

Units: s

Numeric constraints: >= 0.0

**Example:**

```json
0.000128
```

## <a name="transmit_bandwidth"></a>31. Property `Standardized Calibration File > transmit_bandwidth`

**Title:** Nominal bandwidth of transmitted pulse

|              |          |
| ------------ | -------- |
| **Type**     | `number` |
| **Required** | No       |

**Description:** Estimated bandwidth of the transmitted pulse.

Precision: 10

Reference: SONAR-netCDF4 2.0 Sonar/Beam_group.transmit_bandwidth

Units: Hz

Numeric constraints: >= 0.0

**Examples:**

```json
1570.0
```

```json
3030.0
```

## <a name="beam_type"></a>32. Property `Standardized Calibration File > beam_type`

**Title:** Transducer beam type

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Describes the physical beam type of the transducer (e.g., split-beam, single).

Reference: SONAR-netCDF4 2.0 Sonar/Beam_group.beam_type

## <a name="calibration_acquisition_method"></a>33. Property `Standardized Calibration File > calibration_acquisition_method`

**Title:** Calibration acquisition method

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Brief description of the calibration workflow or platform used.

## <a name="sphere_diameter"></a>34. Property `Standardized Calibration File > sphere_diameter`

**Title:** Calibration sphere diameter

|              |                  |
| ------------ | ---------------- |
| **Type**     | `number or null` |
| **Required** | No               |

**Description:** Diameter of the calibration sphere.

Precision: 10

Units: mm

Numeric constraints: >= 0.0

## <a name="sphere_material"></a>35. Property `Standardized Calibration File > sphere_material`

**Title:** Calibration sphere material

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Material of the calibration sphere.

**Example:**

```json
"tungsten carbide"
```

## <a name="source_file_type"></a>36. Property `Standardized Calibration File > source_file_type`

**Title:** Channel source file type

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** File extension or descriptor describing the calibration source files linked to this channel.

**Examples:**

```json
".raw"
```

```json
".cal"
```

## <a name="source_file_location"></a>37. Property `Standardized Calibration File > source_file_location`

**Title:** Channel source file location

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Human-readable location of the calibration source files that contributed to this channel.

**Examples:**

```json
"NCEI"
```

```json
"OMAO"
```

```json
"HDD"
```

## <a name="sonar_software_version"></a>38. Property `Standardized Calibration File > sonar_software_version`

**Title:** Sonar software version

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Version string of the sonar software controlling this channel.

Reference: SONAR-netCDF4 2.0 Sonar.sonar_software_version

**Example:**

```json
"2.4.3"
```

## <a name="sonar_software_name"></a>39. Property `Standardized Calibration File > sonar_software_name`

**Title:** Sonar software name

|              |                  |
| ------------ | ---------------- |
| **Type**     | `string or null` |
| **Required** | No               |

**Description:** Name of the sonar control or acquisition software.

Reference: SONAR-netCDF4 2.0 Sonar.sonar_software_name

## <a name="equivalent_beam_angle"></a>40. Property `Standardized Calibration File > equivalent_beam_angle`

**Title:** Equivalent beam angle

|              |          |
| ------------ | -------- |
| **Type**     | `number` |
| **Required** | No       |

**Description:** Equivalent beam angle of the receive beam.

Precision: 2

Reference: SONAR-netCDF4 2.0 Sonar/Beam_group.equivalent_beam_angle

Units: dB re sr

**Example:**

```json
-17.0
```

## <a name="gain_correction"></a>41. Property `Standardized Calibration File > gain_correction`

**Title:** Gain correction

|              |                           |
| ------------ | ------------------------- |
| **Type**     | `array of number or null` |
| **Required** | No                        |

**Description:** Gain correction set from a calibration exercise (required for type 2 conversion equations). Array format supports multiple values for broadband systems.

Precision: 2

Reference: SONAR-netCDF4 2.0 Sonar/Beam_group.gain_correction

Units: dB

**Examples:**

```json
[
    24.06
]
```

```json
[
    25.41
]
```

|                      | Array restrictions |
| -------------------- | ------------------ |
| **Min items**        | N/A                |
| **Max items**        | N/A                |
| **Items unicity**    | False              |
| **Additional items** | False              |
| **Tuple validation** | See below          |

| Each item of this array must be                 | Description |
| ----------------------------------------------- | ----------- |
| [gain_correction items](#gain_correction_items) | -           |

### <a name="gain_correction_items"></a>41.1. Standardized Calibration File > gain_correction > gain_correction items

|              |          |
| ------------ | -------- |
| **Type**     | `number` |
| **Required** | No       |

## <a name="sa_correction"></a>42. Property `Standardized Calibration File > sa_correction`

**Title:** Sa correction

|              |                           |
| ------------ | ------------------------- |
| **Type**     | `array of number or null` |
| **Required** | No                        |

**Description:** Nautical area scattering coefficient correction derived from calibration. Array format supports multiple values for broadband systems.

Precision: 2

Units: dB

**Examples:**

```json
[
    -0.68
]
```

```json
[
    -0.32
]
```

|                      | Array restrictions |
| -------------------- | ------------------ |
| **Min items**        | N/A                |
| **Max items**        | N/A                |
| **Items unicity**    | False              |
| **Additional items** | False              |
| **Tuple validation** | See below          |

| Each item of this array must be             | Description |
| ------------------------------------------- | ----------- |
| [sa_correction items](#sa_correction_items) | -           |

### <a name="sa_correction_items"></a>42.1. Standardized Calibration File > sa_correction > sa_correction items

|              |          |
| ------------ | -------- |
| **Type**     | `number` |
| **Required** | No       |

## <a name="frequency"></a>43. Property `Standardized Calibration File > frequency`

**Title:** Acoustic frequency

|              |                           |
| ------------ | ------------------------- |
| **Type**     | `array of number or null` |
| **Required** | Yes                       |

**Description:** Frequency of the receive echo from spectral analysis of the FM pulse or frequency of the CW pulse. Array format supports multiple frequencies for broadband systems.

Precision: 10

Reference: SONAR-netCDF4 2.0 Sonar/Beam_group.frequency

Units: Hz

**Examples:**

```json
[
    18000.0
]
```

```json
[
    38000.0
]
```

```json
[
    70000.0
]
```

|                      | Array restrictions |
| -------------------- | ------------------ |
| **Min items**        | N/A                |
| **Max items**        | N/A                |
| **Items unicity**    | False              |
| **Additional items** | False              |
| **Tuple validation** | See below          |

| Each item of this array must be     | Description                 |
| ----------------------------------- | --------------------------- |
| [frequency items](#frequency_items) | Numeric constraints: >= 0.0 |

### <a name="frequency_items"></a>43.1. Standardized Calibration File > frequency > frequency items

|              |          |
| ------------ | -------- |
| **Type**     | `number` |
| **Required** | No       |

**Description:** Numeric constraints: >= 0.0

## <a name="beamwidth_transmit_major"></a>44. Property `Standardized Calibration File > beamwidth_transmit_major`

**Title:** Half power one-way transmit beam width along major axis

|              |                 |
| ------------ | --------------- |
| **Type**     | `array or null` |
| **Required** | No              |

**Description:** One-way beam width at half-power down in the horizontal (major) direction of the transmit beam. Array format supports multiple values for broadband systems.

Precision: 2

Reference: SONAR-netCDF4 2.0 Sonar/Beam_group.beamwidth_transmit_major

Units: arc_degree

**Examples:**

```json
[
    11.06
]
```

```json
[
    6.97
]
```

|                      | Array restrictions |
| -------------------- | ------------------ |
| **Min items**        | N/A                |
| **Max items**        | N/A                |
| **Items unicity**    | False              |
| **Additional items** | False              |
| **Tuple validation** | See below          |

| Each item of this array must be                                   | Description                           |
| ----------------------------------------------------------------- | ------------------------------------- |
| [beamwidth_transmit_major items](#beamwidth_transmit_major_items) | Numeric constraints: >= 0.0, <= 360.0 |

### <a name="beamwidth_transmit_major_items"></a>44.1. Standardized Calibration File > beamwidth_transmit_major > beamwidth_transmit_major items

|              |                  |
| ------------ | ---------------- |
| **Type**     | `number or null` |
| **Required** | No               |

**Description:** Numeric constraints: >= 0.0, <= 360.0

## <a name="beamwidth_receive_major"></a>45. Property `Standardized Calibration File > beamwidth_receive_major`

**Title:** Half power one-way receive beam width along major axis

|              |                 |
| ------------ | --------------- |
| **Type**     | `array or null` |
| **Required** | No              |

**Description:** One-way beam width at half-power down in the horizontal (major) direction of the receive beam. Array format supports multiple values for broadband systems.

Precision: 2

Reference: SONAR-netCDF4 2.0 Sonar/Beam_group.beamwidth_receive_major

Units: arc_degree

**Examples:**

```json
[
    11.06
]
```

```json
[
    6.97
]
```

|                      | Array restrictions |
| -------------------- | ------------------ |
| **Min items**        | N/A                |
| **Max items**        | N/A                |
| **Items unicity**    | False              |
| **Additional items** | False              |
| **Tuple validation** | See below          |

| Each item of this array must be                                 | Description                           |
| --------------------------------------------------------------- | ------------------------------------- |
| [beamwidth_receive_major items](#beamwidth_receive_major_items) | Numeric constraints: >= 0.0, <= 360.0 |

### <a name="beamwidth_receive_major_items"></a>45.1. Standardized Calibration File > beamwidth_receive_major > beamwidth_receive_major items

|              |                  |
| ------------ | ---------------- |
| **Type**     | `number or null` |
| **Required** | No               |

**Description:** Numeric constraints: >= 0.0, <= 360.0

## <a name="beamwidth_transmit_minor"></a>46. Property `Standardized Calibration File > beamwidth_transmit_minor`

**Title:** Half power one-way transmit beam width along minor axis

|              |                 |
| ------------ | --------------- |
| **Type**     | `array or null` |
| **Required** | No              |

**Description:** One-way beam width at half-power down in the vertical (minor) direction of the transmit beam. Array format supports multiple values for broadband systems.

Precision: 2

Reference: SONAR-netCDF4 2.0 Sonar/Beam_group.beamwidth_transmit_minor

Units: arc_degree

**Examples:**

```json
[
    10.56
]
```

```json
[
    6.87
]
```

|                      | Array restrictions |
| -------------------- | ------------------ |
| **Min items**        | N/A                |
| **Max items**        | N/A                |
| **Items unicity**    | False              |
| **Additional items** | False              |
| **Tuple validation** | See below          |

| Each item of this array must be                                   | Description                           |
| ----------------------------------------------------------------- | ------------------------------------- |
| [beamwidth_transmit_minor items](#beamwidth_transmit_minor_items) | Numeric constraints: >= 0.0, <= 360.0 |

### <a name="beamwidth_transmit_minor_items"></a>46.1. Standardized Calibration File > beamwidth_transmit_minor > beamwidth_transmit_minor items

|              |                  |
| ------------ | ---------------- |
| **Type**     | `number or null` |
| **Required** | No               |

**Description:** Numeric constraints: >= 0.0, <= 360.0

## <a name="beamwidth_receive_minor"></a>47. Property `Standardized Calibration File > beamwidth_receive_minor`

**Title:** Half power one-way receive beam width along minor axis

|              |                 |
| ------------ | --------------- |
| **Type**     | `array or null` |
| **Required** | No              |

**Description:** One-way beam width at half-power down in the vertical (minor) direction of the receive beam. Array format supports multiple values for broadband systems.

Precision: 2

Reference: SONAR-netCDF4 2.0 Sonar/Beam_group.beamwidth_receive_minor

Units: arc_degree

**Examples:**

```json
[
    10.56
]
```

```json
[
    6.87
]
```

|                      | Array restrictions |
| -------------------- | ------------------ |
| **Min items**        | N/A                |
| **Max items**        | N/A                |
| **Items unicity**    | False              |
| **Additional items** | False              |
| **Tuple validation** | See below          |

| Each item of this array must be                                 | Description                           |
| --------------------------------------------------------------- | ------------------------------------- |
| [beamwidth_receive_minor items](#beamwidth_receive_minor_items) | Numeric constraints: >= 0.0, <= 360.0 |

### <a name="beamwidth_receive_minor_items"></a>47.1. Standardized Calibration File > beamwidth_receive_minor > beamwidth_receive_minor items

|              |                  |
| ------------ | ---------------- |
| **Type**     | `number or null` |
| **Required** | No               |

**Description:** Numeric constraints: >= 0.0, <= 360.0

## <a name="echoangle_major"></a>48. Property `Standardized Calibration File > echoangle_major`

**Title:** Echo arrival angle in the major beam coordinate

|              |                 |
| ------------ | --------------- |
| **Type**     | `array or null` |
| **Required** | No              |

**Description:** Electrical phase-derived arrival angle relative to the major beam coordinate. Array format supports multiple values for broadband systems.

Precision: 2

Reference: SONAR-netCDF4 2.0 Sonar/Beam_group.echoangle_major

Units: arc_degree

**Examples:**

```json
[
    0.01
]
```

```json
[
    -0.12
]
```

|                      | Array restrictions |
| -------------------- | ------------------ |
| **Min items**        | N/A                |
| **Max items**        | N/A                |
| **Items unicity**    | False              |
| **Additional items** | False              |
| **Tuple validation** | See below          |

| Each item of this array must be                 | Description                              |
| ----------------------------------------------- | ---------------------------------------- |
| [echoangle_major items](#echoangle_major_items) | Numeric constraints: >= -180.0, <= 180.0 |

### <a name="echoangle_major_items"></a>48.1. Standardized Calibration File > echoangle_major > echoangle_major items

|              |                  |
| ------------ | ---------------- |
| **Type**     | `number or null` |
| **Required** | No               |

**Description:** Numeric constraints: >= -180.0, <= 180.0

## <a name="echoangle_minor"></a>49. Property `Standardized Calibration File > echoangle_minor`

**Title:** Echo arrival angle in the minor beam coordinate

|              |                 |
| ------------ | --------------- |
| **Type**     | `array or null` |
| **Required** | No              |

**Description:** Electrical phase-derived arrival angle relative to the minor beam coordinate. Array format supports multiple values for broadband systems.

Precision: 2

Reference: SONAR-netCDF4 2.0 Sonar/Beam_group.echoangle_minor

Units: arc_degree

**Examples:**

```json
[
    -0.07
]
```

```json
[
    -0.09
]
```

|                      | Array restrictions |
| -------------------- | ------------------ |
| **Min items**        | N/A                |
| **Max items**        | N/A                |
| **Items unicity**    | False              |
| **Additional items** | False              |
| **Tuple validation** | See below          |

| Each item of this array must be                 | Description                              |
| ----------------------------------------------- | ---------------------------------------- |
| [echoangle_minor items](#echoangle_minor_items) | Numeric constraints: >= -180.0, <= 180.0 |

### <a name="echoangle_minor_items"></a>49.1. Standardized Calibration File > echoangle_minor > echoangle_minor items

|              |                  |
| ------------ | ---------------- |
| **Type**     | `number or null` |
| **Required** | No               |

**Description:** Numeric constraints: >= -180.0, <= 180.0

## <a name="echoangle_major_sensitivity"></a>50. Property `Standardized Calibration File > echoangle_major_sensitivity`

**Title:** Major angle scaling factor

|              |                           |
| ------------ | ------------------------- |
| **Type**     | `array of number or null` |
| **Required** | No                        |

**Description:** Scaling factor converting electrical phase differences to physical echo arrival angles (major axis). Array format supports multiple values for broadband systems.

Precision: 10

Reference: SONAR-netCDF4 2.0 Sonar/Beam_group.echoangle_major_sensitivity

Units: 1

**Examples:**

```json
[
    13.9
]
```

```json
[
    23.0
]
```

|                      | Array restrictions |
| -------------------- | ------------------ |
| **Min items**        | N/A                |
| **Max items**        | N/A                |
| **Items unicity**    | False              |
| **Additional items** | False              |
| **Tuple validation** | See below          |

| Each item of this array must be                                         | Description                 |
| ----------------------------------------------------------------------- | --------------------------- |
| [echoangle_major_sensitivity items](#echoangle_major_sensitivity_items) | Numeric constraints: >= 0.0 |

### <a name="echoangle_major_sensitivity_items"></a>50.1. Standardized Calibration File > echoangle_major_sensitivity > echoangle_major_sensitivity items

|              |          |
| ------------ | -------- |
| **Type**     | `number` |
| **Required** | No       |

**Description:** Numeric constraints: >= 0.0

## <a name="echoangle_minor_sensitivity"></a>51. Property `Standardized Calibration File > echoangle_minor_sensitivity`

**Title:** Minor angle scaling factor

|              |                           |
| ------------ | ------------------------- |
| **Type**     | `array of number or null` |
| **Required** | No                        |

**Description:** Scaling factor converting electrical phase differences to physical echo arrival angles (minor axis). Array format supports multiple values for broadband systems.

Precision: 10

Reference: SONAR-netCDF4 2.0 Sonar/Beam_group.echoangle_minor_sensitivity

Units: 1

**Examples:**

```json
[
    13.9
]
```

```json
[
    23.0
]
```

|                      | Array restrictions |
| -------------------- | ------------------ |
| **Min items**        | N/A                |
| **Max items**        | N/A                |
| **Items unicity**    | False              |
| **Additional items** | False              |
| **Tuple validation** | See below          |

| Each item of this array must be                                         | Description                 |
| ----------------------------------------------------------------------- | --------------------------- |
| [echoangle_minor_sensitivity items](#echoangle_minor_sensitivity_items) | Numeric constraints: >= 0.0 |

### <a name="echoangle_minor_sensitivity_items"></a>51.1. Standardized Calibration File > echoangle_minor_sensitivity > echoangle_minor_sensitivity items

|              |          |
| ------------ | -------- |
| **Type**     | `number` |
| **Required** | No       |

**Description:** Numeric constraints: >= 0.0

## <a name="source_file_paths"></a>52. Property `Standardized Calibration File > source_file_paths`

**Title:** Channel source file paths

|              |                           |
| ------------ | ------------------------- |
| **Type**     | `array of string or null` |
| **Required** | No                        |

**Description:** Absolute or relative paths to the calibration source files for this channel.

|                      | Array restrictions |
| -------------------- | ------------------ |
| **Min items**        | N/A                |
| **Max items**        | N/A                |
| **Items unicity**    | False              |
| **Additional items** | False              |
| **Tuple validation** | See below          |

| Each item of this array must be                     | Description |
| --------------------------------------------------- | ----------- |
| [source_file_paths items](#source_file_paths_items) | -           |

### <a name="source_file_paths_items"></a>52.1. Standardized Calibration File > source_file_paths > source_file_paths items

|              |          |
| ------------ | -------- |
| **Type**     | `string` |
| **Required** | No       |

----------------------------------------------------------------------------------------------------------------------------
Generated using [json-schema-for-humans](https://github.com/coveooss/json-schema-for-humans) on 2026-04-14 at 11:09:26 -0600