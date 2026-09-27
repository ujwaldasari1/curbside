"""dlt source for daily NYC weather from the Open-Meteo historical archive (no API key).

The whole window is ~700 rows, so each run is a full refresh. That also picks up the
archive's back-filled corrections for recent days without any look-back bookkeeping.
"""

from collections.abc import Iterator
from datetime import date, timedelta

import dlt
from dlt.sources.helpers import requests

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
NYC_LAT, NYC_LON = 40.7128, -74.0060
START_DATE = date(2024, 12, 1)
DAILY_VARS = [
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "snowfall_sum",
    "wind_speed_10m_max",
]


@dlt.resource(name="weather_daily", primary_key="date", write_disposition="replace")
def weather_daily() -> Iterator[list[dict]]:
    end = date.today() - timedelta(days=2)  # the archive lags real time by ~2 days
    response = requests.get(
        ARCHIVE_URL,
        params={
            "latitude": NYC_LAT,
            "longitude": NYC_LON,
            "start_date": START_DATE.isoformat(),
            "end_date": end.isoformat(),
            "daily": ",".join(DAILY_VARS),
            "timezone": "America/New_York",
        },
        timeout=60,
    )
    response.raise_for_status()
    daily = response.json()["daily"]
    yield [
        {"date": d, **{var: daily[var][i] for var in DAILY_VARS}}
        for i, d in enumerate(daily["time"])
    ]


@dlt.source(name="weather")
def weather_source():
    return weather_daily
