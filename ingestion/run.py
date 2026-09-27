"""Run the ingestion pipelines outside Dagster: `python -m ingestion.run [name ...]`."""

import sys
from collections.abc import Callable

import dlt

from ingestion.config import postgres_destination
from ingestion.sources.nyc_open_data import dsny_source, nyc311_source, reference_source
from ingestion.sources.open_meteo import weather_source

# pipeline name -> (source factory, target schema)
PIPELINES: dict[str, tuple[Callable, str]] = {
    "nyc311": (nyc311_source, "raw_nyc311"),
    "dsny": (dsny_source, "raw_dsny"),
    "reference": (reference_source, "raw_reference"),
    "weather": (weather_source, "raw_weather"),
}


def make_pipeline(name: str) -> dlt.Pipeline:
    _, dataset = PIPELINES[name]
    return dlt.pipeline(
        pipeline_name=f"curbside_{name}",
        destination=postgres_destination(),
        dataset_name=dataset,
    )


def run(names: list[str] | None = None) -> None:
    for name in names or list(PIPELINES):
        source_factory, _ = PIPELINES[name]
        info = make_pipeline(name).run(source_factory())
        print(f"[{name}] {info}")


if __name__ == "__main__":
    run(sys.argv[1:] or None)
