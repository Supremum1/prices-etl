"""Разбор недельных Excel-файлов БНС."""

from datetime import date
import hashlib
import json
import math
import re
import unicodedata

import openpyxl
import xlrd

from .download import ROOT, parse_date

STABLE = {
    "Мука пшеничная первого сорта": ("flour", "Мука пшеничная, 1 сорт"),
    "Хлеб пшеничный из муки первого сорта": ("bread", "Хлеб пшеничный, 1 сорт"),
    "Рожки": ("pasta", "Рожки"),
    "Рис шлифованный": ("rice", "Рис шлифованный"),
    "Крупа гречневая": ("buckwheat", "Гречневая крупа"),
    "Масло подсолнечное": ("sunflower_oil", "Масло подсолнечное"),
    "Картофель": ("potato", "Картофель"),
    "Морковь": ("carrot", "Морковь"),
    "Лук репчатый": ("onion", "Лук репчатый"),
    "Капуста белокочанная": ("cabbage", "Капуста белокочанная"),
    "Сахар-песок": ("sugar", "Сахар-песок"),
    "Яйца, 1 категории": ("eggs", "Яйца, I категории"),
}


def clean(value):
    text = str(value or "")
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def product_group(name, product_id):
    words = name.lower()
    groups = {
        "Овощи и фрукты": ["картофель", "морковь", "лук ", "капуста", "яблок", "огурц", "помидор"],
        "Молочные продукты": ["молок", "кефир", "творог", "сыр ", "сметан", "сливоч"],
        "Мясо и рыба": ["говядин", "мяс", "кур", "конин", "баранин", "рыба"],
    }
    for group, keywords in groups.items():
        for keyword in keywords:
            if keyword in words:
                return group

    if product_id in {"flour", "bread", "rice", "buckwheat", "pasta"}:
        return "Крупы, хлеб и мука"
    return "Другие продукты"


def product(label):
    name = clean(label)
    name = re.sub(r"\s*\d+\)", "", name)

    if "десяток" in name.lower():
        unit = "десяток"
    elif "литр" in name.lower():
        unit = "л"
    else:
        unit = "кг"

    name = re.sub(r",?\s*(литр|десяток)\b", "", name, flags=re.I)
    name = re.sub(r"\s*\(весов(?:ые|ой|ая)\)", "", name)
    name = name.replace("Рис шлифованный, полированный", "Рис шлифованный")
    name = re.sub(r"Яйца,\s*[I1]\s*категори[яи]", "Яйца, 1 категории", name)
    name = clean(name).rstrip(" ,*")
    if name == "Рис":
        name = "Рис шлифованный"

    if name.startswith(("Социально-значимые", "Социально значимые")):
        return "all_food", "Все СЗПТ", "индекс", "Сводный индекс"

    if name in STABLE:
        product_id, display_name = STABLE[name]
    else:
        # ID остаётся одинаковым при повторном разборе файла.
        digest = hashlib.sha1(name.lower().encode()).hexdigest()
        product_id = "p_" + digest[:12]
        display_name = name

    return product_id, display_name, unit, product_group(name, product_id)


def city(label):
    name = re.sub(r"\s*[1-9]\)\s*$", "", clean(label)).strip()
    if name.lower().startswith(("по обследованным", "республика казахстан", "казахстан")):
        return "Казахстан"

    name = re.sub(r"^(г\.?\s*)", "", name)
    aliases = {
        "Петропавлск": "Петропавловск",
        "Нур-Султан": "Астана",
        "Нұр-Сұлтан": "Астана",
        "Нур–Султан": "Астана",
    }
    return aliases.get(name, name)


def numeric(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if math.isfinite(value):
            return float(value), "observed"

    text = clean(value)
    if text in {"", "…", "...", ".."} or text.startswith(("…", "...")):
        return None, "missing"
    if text.lower() in {"x", "х"}:
        return None, "confidential"
    if text in {"-", "–", "—"}:
        return None, "not_applicable"

    # В исходниках встречаются "2823)", "100,01)" и "100,0*".
    text = re.sub(r"\s*[1-9]\)\s*$", "", text).rstrip("*").strip()
    text = text.replace(" ", "").replace(",", ".")
    try:
        return float(text), "observed"
    except ValueError:
        raise ValueError(f"Неизвестное значение ячейки: {value!r}") from None


def read_book(path):
    with path.open("rb") as file:
        signature = file.read(8)

    sheets = []
    if signature == bytes.fromhex("D0CF11E0A1B11AE1"):
        book = xlrd.open_workbook(path)
        try:
            for sheet in book.sheets():
                rows = []
                for row_number in range(sheet.nrows):
                    rows.append(sheet.row_values(row_number))
                sheets.append((sheet.name, rows))
        finally:
            book.release_resources()
    else:
        book = openpyxl.load_workbook(path, data_only=True, read_only=True)
        try:
            for sheet in book:
                sheets.append((sheet.title, list(sheet.values)))
        finally:
            book.close()
    return sheets


def get_title(rows):
    parts = []
    for row in rows[:2]:
        for value in row:
            if value:
                parts.append(clean(value))
    return clean(" ".join(parts))


def find_header(rows, text, limit):
    for row_number, row in enumerate(rows[:limit]):
        for value in row:
            if text in clean(value):
                return row_number
    return None


def get_metric(title):
    title = title.lower()
    if "средние цены" in title and "индекс" not in title:
        return "price"
    if "индекс" in title:
        if "за год" in title:
            return "yoy"
        if "за неделю" in title:
            return "wow"
        if "с начала года" in title:
            return "ytd"
    return None


def has_numbers(values):
    for value in values:
        if isinstance(value, (int, float)) or re.match(r"^\d", clean(value)):
            return True
    return False


def make_observation(
    record, observed, geography, label, product_info, kind, raw, sheet, row, column, title
):
    product_id, name, unit, group = product_info
    value, status = numeric(raw)
    if value is not None and value <= 0:
        raise ValueError(f"Цена или индекс должны быть положительными: {value}")
    if kind != "price":
        unit = "индекс"
    elif product_id == "all_food":
        raise ValueError("В таблице цен неожиданно появился сводный индекс")

    return {
        "observation_date": observed,
        "city": geography,
        "product_id": product_id,
        "product": name,
        "product_group": group,
        "unit": unit,
        "metric": kind,
        "value": value,
        "value_status": status,
        "raw_label": clean(label),
        "raw_value": clean(raw),
        "source_file": record["path"],
        "source_sheet": sheet,
        "source_row": row,
        "source_column": column,
        "source_url": record["url"],
        "release_id": record["element_id"],
        "comparison_label": title,
        "catalog_date": record["observation_date"],
    }


def parse_table(record, observed, sheet, rows, kind):
    title = get_title(rows)
    dates = re.findall(r"(\d{1,2}\s+[а-я]+\s+\d{4})", title.lower())
    if dates and parse_date(dates[-1]).isoformat() != observed:
        raise ValueError(f"Разные даты внутри файла: {record['path']}, лист {sheet}")

    header = find_header(rows, "По обследованным", 10)
    if header is None:
        raise ValueError(f"Нет заголовка городов: {record['path']}, лист {sheet}")

    geographies = {}
    for column, label in enumerate(rows[header]):
        if column > 0 and clean(label):
            geographies[column] = city(label)

    result = []
    product_count = 0
    for row_number, row in enumerate(rows[header + 1 :], header + 2):
        label = clean(row[0]) if row else ""
        if product_count >= 19 and (not label or re.match(r"^\d+\)", label)):
            break
        if not label:
            continue

        values = []
        for column in geographies:
            values.append(row[column] if column < len(row) else None)
        if not has_numbers(values):
            continue

        product_info = product(label)
        for column, geography in geographies.items():
            raw = row[column] if column < len(row) else None
            observation = make_observation(
                record=record,
                observed=observed,
                geography=geography,
                label=label,
                product_info=product_info,
                kind=kind,
                raw=raw,
                sheet=sheet,
                row=row_number,
                column=column + 1,
                title=title,
            )
            result.append(observation)
        product_count += 1

    if product_count < 19:
        raise ValueError(f"Слишком мало товаров: {record['path']}, лист {sheet}")
    return result


def add_combined_indices(observations):
    extra = []
    for observation in observations:
        title = observation["comparison_label"].lower()
        weekly_and_ytd = observation["metric"] == "wow" and "за неделю, с начала года" in title
        annual_and_ytd = observation["metric"] == "yoy" and "за год и с начала года" in title
        if weekly_and_ytd or annual_and_ytd:
            copy = observation.copy()
            copy["metric"] = "ytd"
            extra.append(copy)
    observations.extend(extra)


def parse_summary(record, observed, rows, observations):
    known = set()
    for observation in observations:
        if observation["city"] == "Казахстан":
            known.add((observation["product_id"], observation["metric"]))

    header = find_header(rows, "с начала месяца", 8)
    if header is None:
        raise ValueError(f"Нет заголовка сводной таблицы: {record['path']}")

    result = []
    metrics = {1: "yoy", 2: "ytd", 3: "mtd", 4: "wow"}
    for row_number, row in enumerate(rows[header + 1 :], header + 2):
        if not clean(row[0]) or not has_numbers(row[1:5]):
            break
        product_info = product(row[0])
        product_id = product_info[0]
        for column, kind in metrics.items():
            key = (product_id, kind)
            if key in known:
                continue
            result.append(
                make_observation(
                    record=record,
                    observed=observed,
                    geography="Казахстан",
                    label=row[0],
                    product_info=product_info,
                    kind=kind,
                    raw=row[column],
                    sheet="1",
                    row=row_number,
                    column=column + 1,
                    title=clean(rows[header][column]),
                )
            )
            known.add(key)
    return result


def parse_release(record):
    sheets = read_book(ROOT / record["path"])
    observed = None
    for sheet, rows in sheets:
        if sheet.strip().isdigit() and get_metric(get_title(rows)) == "price":
            observed = parse_date(get_title(rows)).isoformat()
            break
    if observed is None:
        raise ValueError(f"Нет таблицы цен: {record['path']}")

    # Каталог иногда указывает дату публикации, а не дату наблюдения.
    observations = []
    for sheet, rows in sheets:
        if not sheet.strip().isdigit():
            continue
        kind = get_metric(get_title(rows))
        if kind is not None:
            observations.extend(parse_table(record, observed, sheet, rows, kind))

    add_combined_indices(observations)
    for sheet, rows in sheets:
        if sheet.strip() == "1":
            observations.extend(parse_summary(record, observed, rows, observations))
    return observations


def check_duplicates(observations):
    seen = set()
    for row in observations:
        key = (row["observation_date"], row["city"], row["product_id"], row["metric"])
        if key in seen:
            raise ValueError(f"Повторяющийся ключ: {key}")
        seen.add(key)


def create_report(manifest, observations):
    prices = 0
    missing = 0
    cities = set()
    products = set()
    dates = set()
    date_differences = set()
    for row in observations:
        dates.add(row["observation_date"])
        cities.add(row["city"])
        if row["metric"] == "price":
            prices += 1
            products.add(row["product"])
        if row["value"] is None:
            missing += 1
        if row["catalog_date"] != row["observation_date"]:
            date_differences.add((row["catalog_date"], row["observation_date"]))

    dates = sorted(dates)
    gaps = []
    for previous, current in zip(dates, dates[1:]):
        days = (date.fromisoformat(current) - date.fromisoformat(previous)).days
        if days > 10:
            gaps.append([previous, current, days])

    return {
        "files": len(manifest),
        "observations": len(observations),
        "prices": prices,
        "first_date": dates[0],
        "last_date": dates[-1],
        "missing": missing,
        "cities": sorted(cities),
        "products": sorted(products),
        "catalog_date_differences": sorted(date_differences),
        "weekly_gaps_over_10_days": gaps,
    }


def main():
    manifest = json.loads((ROOT / "data/manifest.json").read_text(encoding="utf-8"))
    observations = []
    errors = []
    for record in manifest:
        try:
            observations.extend(parse_release(record))
        except Exception as error:
            errors.append({"file": record["path"], "error": str(error)})

    output = ROOT / "data/processed"
    output.mkdir(parents=True, exist_ok=True)
    (output / "parse_errors.json").write_text(
        json.dumps(errors, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if errors:
        raise SystemExit(f"Ошибок разбора: {len(errors)}. Подробнее в parse_errors.json.")
    if not observations:
        raise ValueError("Наблюдений нет. Публикация отменена.")

    check_duplicates(observations)
    with (output / "observations.jsonl").open("w", encoding="utf-8") as file:
        for row in observations:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = create_report(manifest, observations)
    (output / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Разобрано файлов: {len(manifest)}, наблюдений: {len(observations):,}")


if __name__ == "__main__":
    main()
