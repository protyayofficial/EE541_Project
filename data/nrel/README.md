# NREL typical meteorological year (TMY3) sample

File: `723170TYA.CSV` (Greensboro, NC), distributed by pvlib-python at https://github.com/pvlib/pvlib-python/blob/main/pvlib/data/723170TYA.CSV. Download: https://raw.githubusercontent.com/pvlib/pvlib-python/main/pvlib/data/723170TYA.CSV. The sample is included in this repository with the [pvlib BSD 3-Clause license](PVLIB_LICENSE.txt). Its SHA-256 is `1e96f84638ce98e6b29002bc45a27aa69bb29b0ed0368d3b52b7b1f81610c6c9`. Pilot settings also record the hash.

This is a typical meteorological year constructed from selected months, not a consecutive measured year; the sampled variable is hourly global horizontal irradiance (W/m^2), not electrical energy. Each scheduling slot is one hour and the active radio duration is one second; harvest is the irradiance multiplied by an assumed 0.005 J/(W/m^2*slot). This is a scenario proxy, not a validated photovoltaic conversion. Do not compare throughput in bits/s directly to the one-minute scenarios without accounting for the different slot lengths.

To download from the upstream distribution:

```bash
mkdir -p data/nrel
curl -L --fail 'https://raw.githubusercontent.com/pvlib/pvlib-python/main/pvlib/data/723170TYA.CSV' -o data/nrel/723170TYA.CSV
shasum -a 256 data/nrel/723170TYA.CSV
```

The source URL follows its `main` branch; check the resulting hash against `results/course_project_v1/settings.json` before reproducing the saved study.
