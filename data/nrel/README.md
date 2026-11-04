# NREL typical meteorological year (TMY3) sample

File: `723170TYA.CSV` (Greensboro, NC), distributed by pvlib-python at https://github.com/pvlib/pvlib-python/blob/main/pvlib/data/723170TYA.CSV. Download: https://raw.githubusercontent.com/pvlib/pvlib-python/main/pvlib/data/723170TYA.CSV. Source distribution and attribution/terms should be checked before redistribution. Pilot settings record SHA-256.

This is a typical meteorological year constructed from selected months, not a consecutive measured year; the sampled variable is hourly global horizontal irradiance (W/m^2), not electrical energy. Each scheduling slot is one hour and the active radio duration is one second; harvest is the irradiance multiplied by an assumed 0.005 J/(W/m^2*slot). This is a scenario proxy, not a validated photovoltaic conversion. Do not compare throughput in bits/s directly to the one-minute scenarios without accounting for the different slot lengths.

To download from the upstream distribution:

```bash
mkdir -p data/nrel
curl -L --fail 'https://raw.githubusercontent.com/pvlib/pvlib-python/main/pvlib/data/723170TYA.CSV' -o data/nrel/723170TYA.CSV
shasum -a 256 data/nrel/723170TYA.CSV
```

The source URL follows its `main` branch; check the resulting hash against `results/course_project_v1/settings.json` before reproducing the saved study.
