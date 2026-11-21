# UMass Smart* Home C dataset

Source: https://traces.cs.umass.edu/docs/traces/smartstar/ (2013 Home C generation dataset). Download: https://lass.cs.umass.edu/smarttraces/homeC-generation.tar.gz. License: CC BY 4.0 according to the dataset page; cite the dataset and its publication, Barker et al., “Smart*: An Open Data Set and Tools for Enabling Research in Sustainable Homes,” SustKDD 2012.

The archive FORMAT specifies timestamp UTC, two turbine currents in mA, three solar panel currents in mA, battery voltage. The pilot averages the sum of the three nonnegative solar panel currents at one-minute resolution and multiplies by an assumed 0.1 J/(mA*slot). This is an arbitrary proxy, not measured harvested energy at our transmitter. Home C is a household energy system, not our simulated IoT device. The source files are downloaded locally, and the benchmark settings record their SHA-256.

To download from the source:

```bash
mkdir -p data/umass
curl -L --fail 'https://lass.cs.umass.edu/smarttraces/homeC-generation.tar.gz' -o data/umass/homeC-generation.tar.gz
shasum -a 256 data/umass/homeC-generation.tar.gz
```
