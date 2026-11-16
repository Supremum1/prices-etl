"""Проверки возобновления скачивания и пакетной загрузки."""

from datetime import date
import json
from unittest.mock import Mock

import pytest

from etl import download, load


def test_download_skips_cache_and_ignores_unfinished_file(tmp_path, monkeypatch):
    monkeypatch.setattr(download, "ROOT", tmp_path)
    record = {
        "observation_date": "2023-01-04",
        "element_id": "8151",
        "url": "https://example.test/file",
    }
    directory = tmp_path / "data/raw/2023"
    directory.mkdir(parents=True)
    (directory / "2023-01-04_8151.xls.part").write_bytes(b"unfinished")
    http = Mock()
    http.get.return_value.content = bytes.fromhex("D0CF11E0A1B11AE1") + b"test"

    first = download.download_one(record, http)
    second = download.download_one(record, http)

    assert first == second
    assert (tmp_path / first["path"]).suffix == ".xls"
    assert http.get.call_count == 1
    assert first["sha256"] == second["sha256"]


def test_loader_flushes_last_incomplete_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(load, "BATCH_SIZE", 2)
    path = tmp_path / "observations.jsonl"
    with path.open("w", encoding="utf-8") as file:
        for number in range(3):
            row = {
                "observation_date": "2023-01-04",
                "catalog_date": "2023-01-05",
                "value": number + 100,
            }
            file.write(json.dumps(row) + "\n")
    connection = Mock()

    assert load.insert_records(connection, path) == 3
    first, last = connection.insert.call_args_list
    assert len(first.args[1]) == 2
    assert len(last.args[1]) == 1
    assert last.args[1][0] == [date(2023, 1, 4), date(2023, 1, 5), 102]


def test_loader_rejects_empty_input(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    connection = Mock()
    with pytest.raises(ValueError, match="пуст"):
        load.insert_records(connection, path)
    connection.insert.assert_not_called()
