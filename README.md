<!-- markdownlint-disable MD033 MD041 -->

<div align="center">

# AA-SI Calibration Library

**Calibration routines, standardized formats, and tools for reading and evaluating sonar calibration data**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

[Overview](#overview) •
[Installation](#installation) •
[Usage](#usage) •
[Project Structure](#project-structure)

</div>

---

## Overview

Calibration is a fundamental and critical component of ensuring acoustic data are of high quality and can be used for quantitative stock assessment, ecosystem science, and fisheries management. This repository provides functions, routines, and other information for reading and evaluating calibration data and calibration results.

Key capabilities:

- **Raw file reading** — Extract channel configurations from Simrad EK60/EK80 `.raw` files
- **Manufacturer calibration parsing** — Parse EK60 `.cal` and EK80 `.xml` calibration files
- **Standardized calibration format** — Validate, convert, and save calibration data against a JSON schema
- **Channel-to-calibration mapping** — Automatically match raw file channels to the correct calibration parameters
- **Manual calibration workflow** — Generate template files for user-provided calibration values

### Standardized Calibration File Format

The `standardized_file/` folder contains examples of our proposed standardized calibration file format and its JSON schema. Please note that this format is a work in progress and not a finalized convention or standard.

As part of the calibration effort, we've started documenting differences between the various formats and standards for storing calibration data:
- [Calibration Parameter Nomenclature and Structure](https://docs.google.com/document/d/1JcOW-rruu92jznbOPTHcbPeEvHDVz-Qx0toAXt6V3h8/edit?usp=sharing)
- [Questions and Feedback for ICES on SONAR-netCDF4 v2.0](https://docs.google.com/document/d/1Pq0om-HpDSQI-G8n6Lajo-POEZ5eTs_bauCjT7rhVU8/edit?usp=sharing)

---

## Installation

### Requirements

- Python 3.10 or higher
- pip

### Install from source

```bash
# Clone the repository
git clone https://github.com/nmfs-ost/AA-SI_calibration.git
cd AA-SI_calibration

# Install in development mode
pip install -e .

# With echopype support (for calibration.py)
pip install -e ".[echopype]"

# With development tools
pip install -e ".[dev]"

# With schema documentation generation
pip install -e ".[schema-docs]"
```

---

## Usage

Once installed, import directly — no `sys.path` manipulation needed:

```python
from calibration_library.raw_reader_api import process_raw_folder, save_yaml
from calibration_library.manufacturer_file_parsers import extract_and_convert_calibration_params
from calibration_library.standardized_file_lib import save_single_channel_files_from_params
from calibration_library.mapping_algorithm import (
    load_raw_configs,
    load_calibration_data_from_single_files,
    build_mapping,
    get_calibration,
)
```

---

### Development Setup

```bash
# Install in development mode with dev tools
pip install -e ".[dev]"

# Set up pre-commit hooks
pre-commit install
```

### Running Tests

```bash
pytest
pytest --cov=calibration_library
```

### Code Quality

```bash
black src/ tests/
pylint src/calibration_library
pre-commit run --all-files
```

### Building

```bash
pip install build
python -m build
```

---

## Project Structure

```
├── .gitignore
├── .pre-commit-config.yaml
├── .pylintrc
├── CHANGELOG.md
├── LICENSE
├── NOTICE
├── pyproject.toml
├── README.md
├── Roadmap/
├── src/
│   └── calibration_library/
│       ├── __init__.py
│       ├── calibration.py
│       ├── constants.py
│       ├── mapping_algorithm.py
│       ├── manufacturer_file_parsers.py
│       ├── raw_reader_api.py
│       ├── standardized_file_lib.py
│       ├── utils.py
│       ├── schema/
│       │   ├── schema_docs_generator.py
│       │   └── standardized_calibration_file_schema.json
│       └── simrad_reader/
│           ├── base_reader.py
│           ├── geometery_tools.py
│           ├── raw_reader.py
│           └── reader_errors.py
├── notebooks/
│   ├── full_pipeline.ipynb              # Full workflow: raw files + manufacturer cal files -> mapping
│   ├── manual_pipeline.ipynb            # Manual workflow: generate templates for user-provided values
│   ├── user_provided_cal_pipeline.ipynb # Quick workflow: pre-made single-channel files -> mapping
│   └── example_data/                    # Sample EK60/EK80 data for the notebooks
├── standardized_file/
│   ├── examples/
│   └── json_schema/
└── tests/
    ├── conftest.py
    └── test_package.py
```

---

## License

This project uses the Apache License 2.0. See [LICENSE](LICENSE) for details.

---

## Disclaimer

This repository is a scientific product and is not official communication of the National Oceanic and Atmospheric Administration, or the United States Department of Commerce. All NOAA GitHub project code is provided on an ‘as is’ basis and the user assumes responsibility for its use. Any claims against the Department of Commerce or Department of Commerce bureaus stemming from the use of this GitHub project will be governed by all applicable Federal law. Any reference to specific commercial products, processes, or services by service mark, trademark, manufacturer, or otherwise, does not constitute or imply their endorsement, recommendation or favoring by the Department of Commerce. The Department of Commerce seal and logo, or the seal and logo of a DOC bureau, shall not be used in any manner to imply endorsement of any commercial product or activity by DOC or the United States Government.
