# About vueprom.py

The [Emporia Vue](https://emporiaenergy.com "Emporia's Homepage") energy monitoring kit allows homeowners to monitor their electrical usage. It monitors the main feed consumption and up to 8 (or 16 in the newer version) individual branch circuits, and feeds that data back to the Emporia API server.

Using the [PyEmVue](https://github.com/magico13/PyEmVue) library, this small exporter grabs usage data from Emporia and makes it available to
Prometheus as a Gauge called `per_min_usage_total_watt`. If you want historical data and/or want to use InfluxDB to store data
locally, [vuegraf](https://github.com/magico13/vuegraf) was both the inspiration and starting point for this exporter and is a great solution.

This project is not affiliated with _emporia energy_ company.

# Dependencies

## Required
* [Emporia Vue](https://emporiaenergy.com "Emporia Energy") Account - Username and password for the Emporia Vue system are required.
* [Python 3](https://python.org "Python") - With Pip.
* [Prometheus](https://prometheus.io "Prometheus") - configured to scrape your vueprom instance.

## Recommended
* [Grafana](https://grafana.com "Grafana")

# License

This code is distributed under the MIT license.

See [LICENSE](https://github.com/thebaron/vueprom/blob/master/LICENSE) for more information.
