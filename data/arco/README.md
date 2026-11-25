# UCLM-ARCO energy-harvesting testbed data

Original dataset: https://github.com/UCLM-ARCO/energy-harvesting-dataset (commit `fefa973a4bcbebce75276d325046c206edde012a`); original SHA-256 of `dataset.csv`: `9c9d66ef8d9d6507623186067d8f7e3e06dc1029c9e2f2f02f4e55a32418e2a8`. The original CSV is included, with its byte sequence preserved. The source repository did not visibly declare a data license when inspected; check the original authors' terms before redistributing it.

Associated work: A. Caruso et al., “Experimenting Forecasting Models for Solar Energy Harvesting Devices for Large Smart Cities Deployments,” 2019, https://uclm-arco.github.io/curricula/2019-ISCC.pdf. The data records approximately one-minute observations in Ciudad Real, Spain, from July 31 to October 4, 2018. `PV sc Current` is solar-panel short-circuit current in mA, a proxy for production, **not** measured stored energy. The experiment clips negative sensor readings to zero, groups timestamps by minute, and rejects windows with missing minutes. The presumed coefficient `0.01 J / (mA·slot)` is an arbitrary modeling scenario, not an empirical PV conversion; results use a 60-second slot and 1-second transmission period. Channel and arrivals are synthetic. Consult the paper for device details and cite it and the dataset.

Reproduce the download from the pinned revision:

```bash
curl -L --fail 'https://raw.githubusercontent.com/UCLM-ARCO/energy-harvesting-dataset/fefa973a4bcbebce75276d325046c206edde012a/dataset.csv' -o data/arco/dataset.csv
shasum -a 256 data/arco/dataset.csv
```
