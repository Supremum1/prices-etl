"""Загрузка JSONL в ClickHouse пакетами по 20 000 строк."""

from datetime import date
import json
import os

import clickhouse_connect
from dotenv import load_dotenv

from .download import ROOT

BATCH_SIZE = 20_000
TABLE_ENGINE = "ENGINE = MergeTree ORDER BY (metric, product_id, city, observation_date)"
DDL = """
observation_date Date, city LowCardinality(String), product_id LowCardinality(String),
product String, product_group LowCardinality(String), unit LowCardinality(String),
metric LowCardinality(String), value Nullable(Float64), value_status LowCardinality(String),
raw_label String, raw_value String, source_file String, source_sheet String,
source_row UInt16, source_column UInt16, source_url String, release_id String,
comparison_label String, catalog_date Date
"""


def client():
    load_dotenv(ROOT / ".env")
    return clickhouse_connect.get_client(
        host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        port=int(os.getenv("CLICKHOUSE_PORT", "18123")),
        username="etl",
        password=os.environ["CLICKHOUSE_PASSWORD"],
        settings={"max_threads": 2},
    )


def insert_records(connection, path):
    batch = []
    columns = None
    total = 0

    with path.open(encoding="utf-8") as file:
        for line in file:
            record = json.loads(line)
            if columns is None:
                columns = list(record)

            record["observation_date"] = date.fromisoformat(record["observation_date"])
            record["catalog_date"] = date.fromisoformat(record["catalog_date"])
            batch.append([record[column] for column in columns])
            total += 1

            if len(batch) == BATCH_SIZE:
                connection.insert("prices.observations_incoming", batch, column_names=columns)
                batch = []

    if batch:
        connection.insert("prices.observations_incoming", batch, column_names=columns)
    if total == 0:
        raise ValueError("Файл наблюдений пуст. Публикация отменена.")
    return total


def check_incoming(connection, expected_count):
    row_count, unique_count = connection.query("""
        SELECT count(), uniqExact(tuple(observation_date, city, product_id, metric))
        FROM prices.observations_incoming
    """).first_row
    if row_count != expected_count or unique_count != expected_count:
        raise ValueError(f"Не совпало число строк или ключей: {row_count}, {unique_count}")

    invalid_count = connection.query("""
        SELECT count() FROM prices.observations_incoming
        WHERE value <= 0 OR (value IS NULL AND value_status = 'observed')
    """).first_row[0]
    if invalid_count:
        raise ValueError(f"Некорректных значений: {invalid_count}")


def create_views(connection):
    sql = (ROOT / "sql/views.sql").read_text(encoding="utf-8")
    for statement in sql.split(";"):
        if statement.strip():
            connection.command(statement)


def create_dashboard_user(connection):
    password = os.environ["DASHBOARD_PASSWORD"]
    password = password.replace("\\", "\\\\").replace("'", "\\'")
    connection.command(
        "CREATE USER IF NOT EXISTS dashboard IDENTIFIED WITH sha256_password " f"BY '{password}'"
    )
    connection.command("GRANT SELECT ON prices.* TO dashboard")


def main():
    connection = client()
    try:
        connection.command("CREATE DATABASE IF NOT EXISTS prices ENGINE = Atomic")
        connection.command("DROP TABLE IF EXISTS prices.observations_incoming")
        connection.command(f"CREATE TABLE prices.observations_incoming ({DDL}) {TABLE_ENGINE}")

        total = insert_records(connection, ROOT / "data/processed/observations.jsonl")
        check_incoming(connection, total)

        # Активную таблицу заменяем только после проверки всей загрузки.
        connection.command(f"CREATE TABLE IF NOT EXISTS prices.observations ({DDL}) {TABLE_ENGINE}")
        connection.command("EXCHANGE TABLES prices.observations AND prices.observations_incoming")
        connection.command("DROP TABLE prices.observations_incoming")
        create_views(connection)
        create_dashboard_user(connection)
        print(f"Опубликовано наблюдений: {total:,}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
