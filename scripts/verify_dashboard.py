"""Проверка запросов всех графиков через HTTP API Superset."""

import json
from pathlib import Path
import sys

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://localhost:18088"
CONFIG = ROOT / "superset/config"


def login(http):
    env = dotenv_values(ROOT / ".env")
    response = http.post(
        BASE_URL + "/api/v1/security/login",
        json={
            "username": "admin",
            "password": env["SUPERSET_ADMIN_PASSWORD"],
            "provider": "db",
            "refresh": True,
        },
        timeout=30,
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    http.headers["Authorization"] = "Bearer " + token

    response = http.get(BASE_URL + "/api/v1/security/csrf_token/", timeout=30)
    response.raise_for_status()
    http.headers["X-CSRFToken"] = response.json()["result"]


def get_filters(spec, filter_settings):
    filters = []
    for item in spec["params"].get("adhoc_filters", []):
        filters.append(
            {
                "col": item["subject"],
                "op": item["operator"],
                "val": item["comparator"],
            }
        )

    # Используем те же настройки, что и при создании дашборда.
    for setting in filter_settings:
        if setting["key"] != "time" and spec["key"] in setting["charts"]:
            filters.append(
                {
                    "col": setting["column"],
                    "op": "IN",
                    "val": setting["default"],
                }
            )
    return filters


def build_request(spec, filter_settings):
    params = spec["params"]
    columns = list(params.get("groupby", []))
    is_timeseries = params.get("x_axis") == "observation_date"
    if params.get("x_axis") and not is_timeseries:
        columns.insert(0, params["x_axis"])

    if params.get("metrics"):
        metrics = params["metrics"]
    elif params.get("metric"):
        metrics = [params["metric"]]
    else:
        metrics = []

    if params.get("query_mode") == "raw":
        columns = params["all_columns"]
        metrics = []

    query = {
        "columns": columns,
        "metrics": metrics,
        "filters": get_filters(spec, filter_settings),
        "time_range": "No filter",
        "granularity": "observation_date",
        "is_timeseries": is_timeseries,
        "extras": {"time_grain_sqla": "P1D"},
        "row_limit": params["row_limit"],
        "orderby": [],
        "annotation_layers": [],
        "applied_time_extras": {},
    }
    dataset_id = int(params["datasource"].split("__")[0])
    return {
        "datasource": {"id": dataset_id, "type": "table"},
        "force": True,
        "queries": [query],
        "form_data": params,
        "result_format": "json",
        "result_type": "full",
    }


def check_chart(http, spec, filter_settings):
    response = http.post(
        BASE_URL + "/api/v1/chart/data",
        json=build_request(spec, filter_settings),
        timeout=90,
    )
    data = response.json()
    items = data.get("result", [])
    passed = response.status_code == 200 and bool(items)
    row_counts = []
    for item in items:
        row_counts.append(item.get("rowcount"))
        if item.get("status") != "success" or item.get("rowcount", 0) == 0:
            passed = False

    result = {
        "key": spec["key"],
        "ok": passed,
        "http": response.status_code,
        "rows": row_counts,
    }
    if not passed:
        result["error"] = data
    return result


def main():
    specs = json.loads((ROOT / "outputs/chart_specs.json").read_text(encoding="utf-8"))
    filters = json.loads((CONFIG / "filters.json").read_text(encoding="utf-8"))
    results = []
    with requests.Session() as http:
        login(http)
        for spec in specs:
            result = check_chart(http, spec, filters)
            results.append(result)
            status = "PASS" if result["ok"] else "FAIL"
            print(spec["key"], status, result["rows"], flush=True)

    (ROOT / "outputs/dashboard_verification.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for result in results:
        if not result["ok"]:
            sys.exit(1)


if __name__ == "__main__":
    main()
