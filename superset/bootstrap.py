"""Создание подключения, графиков и дашборда из файлов config/."""

import json
import os
from html import escape
from pathlib import Path

from superset.app import create_app

# Модели Superset можно импортировать только после создания приложения.
app = create_app()
from superset import db, security_manager
from superset.models.core import Database
from superset.models.dashboard import Dashboard
from superset.models.slice import Slice
from superset.connectors.sqla.models import SqlaTable

CONFIG = Path(__file__).parent / "config"
DATASETS = [
    "price_history",
    "prices_latest",
    "index_history",
    "indices_latest",
    "indices_movers_latest",
    "basket_history",
    "basket_latest",
    "dispersion_latest",
    "coverage",
]
COLUMN_LABELS = {
    "city": "Город",
    "product": "Продукт",
    "unit": "Единица",
    "price": "Цена, ₸",
    "national_price": "По стране, ₸",
    "premium_pct": "Отклонение, %",
    "source_url": "Исходный выпуск",
    "products_available": "Цен в наборе",
    "products_required": "Требуется",
    "basket_cost": "Стоимость, ₸",
    "coverage_pct": "Покрытие, %",
    "basket_premium_pct": "Отклонение, %",
}


def read_config(name):
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


def get_admin():
    admin = security_manager.find_user(username="admin")
    if admin is None:
        admin = security_manager.add_user(
            "admin",
            "Price",
            "Analyst",
            "admin@localhost",
            security_manager.find_role("Admin"),
            os.environ["SUPERSET_ADMIN_PASSWORD"],
        )
    return admin


def get_database():
    database = (
        db.session.query(Database)
        .filter_by(
            database_name="Food Prices • ClickHouse",
        )
        .one_or_none()
    )
    if database is None:
        database = Database(database_name="Food Prices • ClickHouse")
        db.session.add(database)

    password = os.environ["DASHBOARD_PASSWORD"]
    database.sqlalchemy_uri = f"clickhousedb://dashboard:{password}@clickhouse:8123/prices"
    database.allow_dml = False
    database.expose_in_sqllab = True
    db.session.commit()
    return database


def create_datasets(database, admin):
    datasets = {}
    for name in DATASETS:
        dataset = (
            db.session.query(SqlaTable)
            .filter_by(
                database_id=database.id,
                schema="prices",
                table_name=name,
            )
            .one_or_none()
        )
        if dataset is None:
            dataset = SqlaTable(
                table_name=name,
                schema="prices",
                database_id=database.id,
                owners=[admin],
            )
            db.session.add(dataset)
            db.session.flush()

        if name in ("basket_history", "basket_latest"):
            dataset.sql = (CONFIG / "basket.sql").read_text(encoding="utf-8")
            if name == "basket_latest":
                dataset.sql += " WHERE a.observation_date=(SELECT max(observation_date) FROM prices.observations)"
        dataset.fetch_metadata()
        dataset.main_dttm_col = "observation_date"
        for column in dataset.columns:
            if column.column_name == "observation_date":
                column.is_dttm = True
            column.verbose_name = COLUMN_LABELS.get(column.column_name)
        datasets[name] = dataset

    db.session.commit()
    return datasets


def create_charts(datasets, admin):
    charts = {}
    specs = []
    defaults = read_config("chart_defaults.json")
    active_keys = set()
    for tab in read_config("tabs.json"):
        for items, height in tab["rows"]:
            for key, width in items:
                active_keys.add(key)
    for config in read_config("charts.json"):
        if config["key"] not in active_keys:
            continue
        dataset = datasets[config["table"]]
        chart = (
            db.session.query(Slice)
            .filter_by(
                slice_name=config["title"],
            )
            .one_or_none()
        )
        if chart is None:
            old_title = config.get("previous_title")
            if old_title:
                chart = db.session.query(Slice).filter_by(slice_name=old_title).one_or_none()
            if chart is None:
                chart = Slice(slice_name=config["title"], owners=[admin])
                db.session.add(chart)
        chart.slice_name = config["title"]

        params = defaults.copy()
        params.update(config["params"])
        params["datasource"] = f"{dataset.id}__table"
        chart.datasource_id = dataset.id
        chart.datasource_type = "table"
        chart.viz_type = params["viz_type"]
        chart.params = json.dumps(params, ensure_ascii=False)
        chart.description = params.get("description", "")
        db.session.flush()

        params["slice_id"] = chart.id
        chart.params = json.dumps(params, ensure_ascii=False)
        charts[config["key"]] = chart
        specs.append(
            {
                "key": config["key"],
                "id": chart.id,
                "table": config["table"],
                "params": params,
            }
        )
    return charts, specs


def create_layout(charts):
    layout = read_config("layout.json")
    for config in read_config("tabs.json"):
        key = config["key"]
        tab_id = "TAB_" + key
        parents = ["ROOT_ID", "GRID_ID", "TABS"]
        note_id = "NOTE_" + key

        layout["TABS"]["children"].append(tab_id)
        layout[tab_id] = {
            "id": tab_id,
            "type": "TAB",
            "children": [],
            "parents": parents,
            "meta": {"text": config["title"]},
        }
        hint = config.get("hint")
        if hint:
            label = escape(hint["label"])
            text = escape(hint["text"], quote=True)
            layout[tab_id]["children"].append(note_id)
            layout[note_id] = {
                "id": note_id,
                "type": "MARKDOWN",
                "children": [],
                "parents": parents + [tab_id],
                "meta": {"width": 12, "height": 5, "code": f'<p><abbr title="{text}" tabindex="0">{label}</abbr></p>'},
            }
        for number, (items, height) in enumerate(config["rows"]):
            row_id = f"ROW_{key}_{number}"
            layout[tab_id]["children"].append(row_id)
            layout[row_id] = {
                "id": row_id,
                "type": "ROW",
                "children": [],
                "parents": parents + [tab_id],
                "meta": {"background": "BACKGROUND_TRANSPARENT"},
            }
            for chart_key, width in items:
                chart = charts[chart_key]
                chart_id = "CHART_" + chart_key
                layout[row_id]["children"].append(chart_id)
                layout[chart_id] = {
                    "id": chart_id,
                    "type": "CHART",
                    "children": [],
                    "parents": parents + [tab_id, row_id],
                    "meta": {
                        "chartId": chart.id,
                        "uuid": str(chart.uuid),
                        "sliceName": chart.slice_name,
                        "width": width,
                        "height": height,
                    },
                }
    return layout


def create_filters(datasets, charts):
    filters = []
    for config in read_config("filters.json"):
        excluded = []
        for key, chart in charts.items():
            if key not in config["charts"]:
                excluded.append(chart.id)

        item = {
            "id": "NATIVE_FILTER-" + config["key"],
            "name": config["name"],
            "cascadeParentIds": [],
            "scope": {"rootPath": ["ROOT_ID"], "excluded": excluded},
            "type": "NATIVE_FILTER",
        }
        if config["key"] == "time":
            item.update(
                {
                    "filterType": "filter_time",
                    "targets": [{}],
                    "controlValues": {},
                    "defaultDataMask": {
                        "extraFormData": {"time_range": "No filter"},
                        "filterState": {"value": "No filter"},
                    },
                }
            )
        else:
            column = config["column"]
            values = config["default"]
            item.update(
                {
                    "filterType": "filter_select",
                    "targets": [
                        {"datasetId": datasets["price_history"].id, "column": {"name": column}}
                    ],
                    "controlValues": {
                        "enableEmptyFilter": column == "product",
                        "defaultToFirstItem": False,
                        "multiSelect": config["multi"],
                        "searchAllOptions": True,
                        "inverseSelection": False,
                    },
                    "defaultDataMask": {
                        "extraFormData": {"filters": [{"col": column, "op": "IN", "val": values}]},
                        "filterState": {"value": values, "label": ", ".join(values)},
                    },
                    "description": config["description"],
                }
            )
        filters.append(item)
    return filters


def save_dashboard(admin, datasets, charts):
    dashboard = (
        db.session.query(Dashboard)
        .filter_by(
            slug="food-price-observatory",
        )
        .one_or_none()
    )
    if dashboard is None:
        dashboard = Dashboard(slug="food-price-observatory", owners=[admin])
        db.session.add(dashboard)

    chart_settings = {}
    for chart in charts.values():
        chart_settings[str(chart.id)] = {
            "id": chart.id,
            "crossFilters": {"scope": "global", "chartsInScope": []},
        }
    # Superset дописывает сюда свои настройки цветов. Сохраняем их при пересборке.
    metadata = json.loads(dashboard.json_metadata or "{}")
    metadata.update(
        {
            "native_filter_configuration": create_filters(datasets, charts),
            "color_scheme": "food_observatory",
            "refresh_frequency": 0,
            "expanded_slices": {},
            "timed_refresh_immune_slices": [],
            "cross_filters_enabled": False,
            "label_colors": {"Казахстан": "#64748b", "Астана": "#14b8a6", "Кызылорда": "#818cf8"},
            "chart_configuration": chart_settings,
        }
    )
    dashboard.dashboard_title = "Цены на продукты"
    dashboard.created_by = admin
    dashboard.changed_by = admin
    dashboard.published = True
    dashboard.slices = list(charts.values())
    dashboard.position_json = json.dumps(create_layout(charts), ensure_ascii=False)
    dashboard.json_metadata = json.dumps(metadata, ensure_ascii=False)
    dashboard.css = (CONFIG / "dashboard.css").read_text(encoding="utf-8")
    db.session.commit()
    return dashboard


def main():
    with app.app_context():
        admin = get_admin()
        database = get_database()
        datasets = create_datasets(database, admin)
        charts, specs = create_charts(datasets, admin)
        dashboard = save_dashboard(admin, datasets, charts)
        Path("/app/superset_home/chart_specs.json").write_text(
            json.dumps(specs, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Дашборд {dashboard.id}: графиков {len(charts)}, датасетов {len(datasets)}")


if __name__ == "__main__":
    main()
