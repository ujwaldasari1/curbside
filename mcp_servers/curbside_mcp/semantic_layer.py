"""Bridge to the dbt Semantic Layer (MetricFlow).

MetricFlow compiles a metric request to SQL (`mf query --explain`); the SQL then goes
through the same guard and read-only role as any agent query. Agents never write SQL for
certified metrics, and MetricFlow never runs with the ETL role's credentials.
"""

import json
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DBT_DIR = ROOT / "transform"
SEMANTIC_MANIFEST = DBT_DIR / "target" / "semantic_manifest.json"
NAME = re.compile(r"^[a-z][a-z0-9_]*(__[a-z0-9_]+)*$")


class SemanticLayerError(RuntimeError):
    pass


def _mf(*args: str) -> str:
    env = {**os.environ, "DBT_PROFILES_DIR": str(DBT_DIR)}
    result = subprocess.run(
        ["mf", *args], cwd=DBT_DIR, env=env, capture_output=True, text=True, timeout=120
    )
    output = result.stdout + result.stderr
    if result.returncode != 0 or "ERROR" in output[:2000]:
        raise SemanticLayerError(output.strip()[-1500:])
    return output


@lru_cache(maxsize=1)
def catalog() -> dict:
    """Certified metrics and the dimensions they can be grouped by."""
    if not SEMANTIC_MANIFEST.exists():
        _mf("validate-configs", "--skip-dw")
    manifest = json.loads(SEMANTIC_MANIFEST.read_text())
    metrics = [
        {"name": m["name"], "label": m.get("label"), "description": m.get("description"),
         "type": m["type"]}
        for m in manifest["metrics"]
    ]
    dimensions = {"metric_time__day", "metric_time__week", "metric_time__month",
                  "metric_time__quarter", "metric_time__year"}
    for model in manifest["semantic_models"]:
        primary = next((e["name"] for e in model["entities"] if e["type"] == "primary"), None)
        for dim in model.get("dimensions", []):
            if dim["type"] == "categorical" and primary:
                dimensions.add(f"{primary}__{dim['name']}")
        for entity in model["entities"]:
            dimensions.add(entity["name"])
    return {"metrics": metrics, "group_by_options": sorted(dimensions)}


def compile_metric_query(metrics: list[str], group_by: list[str], where: str | None,
                         order_by: list[str], limit: int) -> str:
    known = {m["name"] for m in catalog()["metrics"]}
    unknown = [m for m in metrics if m not in known]
    if unknown:
        raise SemanticLayerError(f"unknown metric(s) {unknown}; call list_metrics")
    for name in [*group_by, *[o.lstrip("-") for o in order_by]]:
        if not NAME.match(name):
            raise SemanticLayerError(f"invalid name: {name!r}")
    args = ["query", "--metrics", ",".join(metrics), "--explain", "--limit", str(limit)]
    if group_by:
        args += ["--group-by", ",".join(group_by)]
    if order_by:
        args += ["--order", ",".join(order_by)]
    if where:
        if ";" in where:
            raise SemanticLayerError("where filter may not contain ';'")
        args += ["--where", where]
    output = _mf(*args)
    match = re.search(r"^(SELECT|WITH)\b.*", output, flags=re.S | re.M)
    if not match:
        raise SemanticLayerError(f"MetricFlow did not return SQL:\n{output[-800:]}")
    return match.group(0).strip()
