# Calibration endpoints in AA_SI_UI: next steps

The calibration endpoints are built into the AA_SI_UI backend and tested
locally. This document lists what is left before they can be deployed and used
from the UI.

For what each endpoint accepts and returns, see
[calibration_service_api.md](calibration_service_api.md).

## What exists today

The code is on the `calibration-endpoints` branch of AA_SI_UI, under
`src/backend`. It is committed and pushed but not yet merged.

| Endpoint | What it does |
| --- | --- |
| `POST /calibration/standardize` | Parses the manufacturer calibration files into channels for review. Scans every raw file, so it can take minutes. |
| `POST /calibration/mapping` | Matches raw channels to calibrations and reports conflicts. Called repeatedly until no conflicts remain. |
| `POST /calibration/archive` | Writes the finished calibration to the survey's archive folder. |

All three require a logged in user. From the frontend they are reached as
`/api/calibration/...`.

Files:

- `routers/calibration.py`: the endpoints
- `routers/calibration_service.py`: settings, recipe runner, error handling
- `routers/models/calibration.py`: request and response models
- `recipes/calibration/`: the three recipes the endpoints run, adapted from
  the ones in this folder with the survey specific defaults removed
- `test/test_calibration.py`: tests

It has been tested with the backend test suite and with a full run of all three
endpoints on local example data. It has not been run against cloud storage or
built into a Docker image.

## Packages the backend installs

The backend's `requirements.txt` installs three packages from GitHub:

```
aa-recipe-manager[gcs,dask] @ git+https://github.com/BLayman-NOAA/AA-SI_recipe_manager.git
aa-si-utils @ git+https://github.com/BLayman-NOAA/AA-SI_Utils.git
aa-si-calibration[echopype,gcs] @ git+https://github.com/BLayman-NOAA/AA-SI_calibration.git
```

The work these endpoints depend on is pushed to `main` in all three. The
Docker build pulls whatever is on `main` at build time, so a later push to
any of them reaches the backend on its next build.

## Step 1: Set the environment variables

Set these on the backend, in `.env` locally and on the Cloud Run service.

| Variable | Required | Value |
| --- | --- | --- |
| `CALIBRATION_CACHE_DIR` | yes | The root of the shared survey cache, `gs://ggn-nmfs-aa-prod-1-data/derived_products/Shared_Cache` in production. Each cruise gets a `<ship>/<cruise_id>` subfolder, shared with recipe manager users. |
| `CALIBRATION_ARCHIVE_ROOT` | yes, for archive | The `gs://` folder that ship folders sit under, `gs://ggn-nmfs-aa-prod-1-data/HDD` in production. The calibration is saved to `<ship>/<cruise_id>/<sonar_model>/Calibration` under it. |
| `CALIBRATION_EXECUTOR` | no | `sequential` (default) or `dask`. Use `dask` to scan raw files in parallel. |
| `CALIBRATION_DASK_WORKERS` | no | Number of workers when using `dask`. Defaults to the CPU count. |
| `CALIBRATION_WORK_DIR` | no | Local scratch folder. Defaults to the system temp folder. |

Until the two required values are set, the calibration endpoints return 503.
The rest of the API is unaffected.

## Step 2: Grant storage access

The backend's service account needs:

- read access to the raw data and manufacturer calibration folders
- read and write on the cache folder
- read and write on the archive folders

A missing permission on the archive folder only shows up at the last step of
the workflow, so check it up front.

## Step 3: Raise the request timeouts and size limit

Standardize is one long HTTP request. A full survey can take 10 to 15 minutes
or more. Mapping and archive requests carry the reviewed channels and the
whole mapping, which runs to a few megabytes for a survey of several thousand
raw files.

**nginx**, in `src/frontend/metadata_ui/nginx.conf`. Calibration requests go
through the general `location /api/` block, not the cached block above it
that serves tugboat, utils and table names. Add these inside the general
block. The default timeout is 60 seconds and the default request size limit
is 1 MB, which a full survey's mapping or archive request will exceed.

```nginx
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;
client_max_body_size 32m;
```

**Cloud Run**, in the `Makefile` deploy commands. The default is 300 seconds.
Add to the backend service:

```
--timeout=3600 \
--no-cpu-throttling \
```

Add `--timeout=3600` to the frontend service as well, because the request
passes through it.

The backend image is also much larger now and needs more memory and CPU than
the defaults. Sizing has not been measured in Cloud Run yet. See
[cloud_run_deployment.md](cloud_run_deployment.md) for guidance.

A timeout on standardize loses no work. Each scanned file is saved to the
cache as it goes, so sending the same request again resumes where it stopped.

The cache is kept on purpose, as a foundation for later runs by anyone. Do not
put a delete lifecycle rule on it.

## Step 4: Build and smoke test

Build the image to confirm the new requirements install:

```bash
docker compose build backend
```

Then run the workflow against a small time window. Log in through the UI
first and copy the `session_token` cookie.

1. Standardize, with a two day window of about four files:

   ```bash
   curl -X POST http://localhost:8080/calibration/standardize \
     -b "session_token=<token>" -H "Content-Type: application/json" \
     -d '{
       "ship": "Reuben_Lasker",
       "cruise_id": "RL2307_smoke",
       "sonar_model": "EK80",
       "raw_input_folder": "gs://ggn-nmfs-aa-prod-1-data/HDD/Reuben_Lasker/RL2307/EK80/data/raw",
       "cal_input_folder": "gs://ggn-nmfs-aa-prod-1-data/HDD/Reuben_Lasker/RL2307/EK80/Calibration/RESULTS",
       "file_time_start": "2023-07-17T16:30:46",
       "file_time_end": "2023-07-18T19:50:19"
     }'
   ```

2. Mapping, with the same body plus `"override_channels"` set to the
   `single_channel_data` from step 1. It should return in seconds, which
   confirms the cached scan was reused. If `conflicts` is not empty, resend
   with `calibration_choices` until it is.
3. Archive, with the three survey fields plus `mapping_dict`, `provenance` and
   `single_channel_data` from the last mapping response. Check that the
   returned `archive_dir` holds `channel_mapping.yaml`,
   `calibration_provenance.yaml` and `Standardized_Reports/`.
4. Archive again with the same body. Expect a 409, because the folder now
   holds an archive.
5. Check that `<CALIBRATION_CACHE_DIR>/Reuben_Lasker/RL2307_smoke` now exists.
   Nothing removes it, so delete that folder by hand once the test is done.

Leave the time window out to process every raw file in the folder.

## Step 5: Wire up the frontend

The flow the UI needs:

1. Call standardize with the survey's raw and calibration folders. Show the
   returned channels for review and editing.
2. Call mapping with the reviewed channels as `override_channels`.
3. If `conflicts` is not empty, let the user pick one candidate, several to
   average, or several FM calibrations made with different spheres to merge in
   an order they choose, and call mapping again with `calibration_choices`.
   Repeat until `conflicts` is empty. For a merge, show the `holes_hz` its
   provenance entry reports, the frequencies no chosen calibration covers.
4. Show the `provenance` summary so the user can check the result.
5. Call archive. Put the returned `archive_dir` into `calFileURI` on the
   submission form.

Points to watch:

- Resend `override_channels` unchanged on every mapping call, and keep adding
  to `calibration_choices`. See "Resolving conflicts" in the API document.
- `ship` must be the folder name used in the bucket, such as `Reuben_Lasker`.
  It is not the display name used in the Tugboat form.
- Use the same `ship`, `cruise_id` and `sonar_model` on every call for a
  survey. `ship` and `cruise_id` decide which cache is used, so changing one
  between standardize and mapping forces a full rescan.
- Error messages are in `detail.message`. The existing Tugboat error handling
  in `CruiseForm.jsx` reads a different shape and will not pick them up.
- On a standardize timeout, send the same request again.

## Running the backend tests

```bash
cd src/backend
python -m pytest test/ -m "not live"
```

The backend needs Python 3.13, which aalibrary requires. Two sets of tests
need the recipe manager and the calibration package installed, and are
skipped without them: one loads each bundled recipe, and one checks that the
standardize and mapping recipes share a cache.

The recipe files in `src/backend/recipes/calibration/` were adapted from the
ones in this folder. If a step changes here, make the same change there.
