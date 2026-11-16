"""Поиск выпусков на stat.gov.kz и сохранение оригинальных Excel-файлов."""

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import time

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = "https://stat.gov.kz"
ROOT = Path(__file__).resolve().parents[1]
MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def parse_date(text):
    match = re.search(r"(\d{2})[.](\d{2})[.](\d{4})", text)
    if match:
        day, month, year = match.groups()
        return date(int(year), int(month), int(day))
    match = re.search(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})", text.lower())
    if match:
        day, month, year = match.groups()
        return date(int(year), MONTHS[month], int(day))
    raise ValueError(f"No observation date: {text}")


def session():
    http = requests.Session()
    http.headers["User-Agent"] = "prices-etl/1.0 (public statistical research)"
    http.mount(
        "https://",
        HTTPAdapter(
            max_retries=Retry(total=4, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        ),
    )
    return http


def discover(start_year=2023, end_year=None):
    records = {}
    end_year = end_year or date.today().year
    catalog = ROOT / "data/catalog"
    catalog.mkdir(parents=True, exist_ok=True)
    with session() as http:
        for year in range(start_year, end_year + 1):
            year_ids = set()
            url = f"{BASE}/ru/industries/economy/prices/spreadsheets/"
            response = http.get(
                url, params={"year": year, "name": "19060", "period": "", "type": ""}, timeout=90
            )
            response.raise_for_status()
            (catalog / f"{year}.html").write_text(response.text, encoding="utf-8")
            soup = BeautifulSoup(response.text, "html.parser")
            for link in soup.select('a[href*="/api/iblock/element/"][href$="/file/ru/"]'):
                title = link.get_text(" ", strip=True)
                if "Индекс цен и средние цены" not in title:
                    continue
                observed = parse_date(title)
                if not start_year <= observed.year <= end_year:
                    continue
                element_id = re.search(r"/element/(\d+)/", link["href"])[1]
                year_ids.add(element_id)
                records[element_id] = dict(
                    element_id=element_id,
                    observation_date=observed.isoformat(),
                    title=title,
                    url=BASE + link["href"],
                    catalog_url=response.url,
                )
            # Сейчас год помещается на одной странице. Не пропускаем новые страницы молча.
            if soup.select('a[href*="PAGEN_"]'):
                raise ValueError(
                    "Catalog gained pagination; implement traversal before claiming completeness"
                )
            print(f"Каталог {year}: {len(year_ids)} выпусков", flush=True)
            time.sleep(0.25)
    if not records:
        raise ValueError("No publications discovered")
    return sorted(records.values(), key=release_order)


def release_order(record):
    return record["observation_date"], record["element_id"]


def download_one(record, http):
    directory = ROOT / "data/raw" / record["observation_date"][:4]
    directory.mkdir(parents=True, exist_ok=True)
    stem = f'{record["observation_date"]}_{record["element_id"]}'
    existing = [path for path in directory.glob(stem + ".*") if path.suffix in {".xls", ".xlsx"}]
    if existing:
        path = existing[0]
        content = path.read_bytes()
    else:
        response = http.get(record["url"], timeout=120)
        response.raise_for_status()
        content = response.content
        if content[:8] == bytes.fromhex("D0CF11E0A1B11AE1"):
            extension = ".xls"
        elif content[:2] == b"PK":
            extension = ".xlsx"
        else:
            raise ValueError(f'Not an Excel document: {record["url"]}, {content[:50]!r}')
        path = directory / (stem + extension)
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(content)
        temporary.replace(path)
    result = record.copy()
    result["path"] = path.relative_to(ROOT).as_posix()
    result["bytes"] = len(content)
    result["sha256"] = hashlib.sha256(content).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=2023)
    parser.add_argument("--end-year", type=int, default=2026)
    args = parser.parse_args()
    records = discover(args.start_year, args.end_year)
    results = []
    errors = []
    # Одна сессия переиспользует соединение. Скачанные файлы пропускаются.
    with session() as http:
        for i, record in enumerate(records, 1):
            try:
                results.append(download_one(record, http))
            except Exception as e:
                errors.append({"record": record, "error": str(e)})
            if i % 20 == 0 or i == len(records):
                print(f"Downloaded {i}/{len(records)}; errors={len(errors)}", flush=True)
    results.sort(key=release_order)
    (ROOT / "data/manifest.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "data/download_errors.json").write_text(
        json.dumps(errors, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if errors:
        raise SystemExit(f"{len(errors)} failed downloads. Re-run to resume.")
    total_bytes = 0
    for record in results:
        total_bytes += record["bytes"]
    print(f"Сохранено файлов: {len(results)}, байтов: {total_bytes:,}", flush=True)


if __name__ == "__main__":
    main()
