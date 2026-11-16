import json
import pytest
from etl.download import ROOT
from etl.parse import numeric, product, city, parse_release


@pytest.mark.parametrize(
    "raw,expected", [("2823)", 282), ("100,01)", 100), ("100,0*", 100), (123.4, 123.4)]
)
def test_numeric_footnotes(raw, expected):
    assert numeric(raw) == (expected, "observed")


@pytest.mark.parametrize("raw", ["…1)", "...", "..", ""])
def test_missing_is_not_zero(raw):
    assert numeric(raw) == (None, "missing")


def test_specs_are_not_merged():
    assert (
        product("Молоко пастеризованное 2,5%, литр")[0]
        != product(
            "Молоко (пастеризованное, ультрапастеризованное, стерилизованное от 2,2% до 6% жирности), литр"
        )[0]
    )
    assert product("Масло сливочное несоленое")[0] != product("Масло сливочное")[0]
    assert product("Рис шлифованный, полированный (весовой) 2)")[0] == product("Рис шлифованный")[0]


def test_units_and_geographies():
    assert product("Яйца, 1 категории, десяток")[2] == "десяток"
    assert product("Кефир 2,5%, литр")[2] == "л"
    assert city("Петропавлск") == "Петропавловск"
    assert city("Кызылорда1)") == "Кызылорда"


def test_source_dates_and_prices():
    manifest = json.loads((ROOT / "data/manifest.json").read_text(encoding="utf-8"))
    first = parse_release(next(r for r in manifest if r["element_id"] == "8151"))
    row = next(
        r
        for r in first
        if r["metric"] == "price" and r["city"] == "Казахстан" and r["product_id"] == "potato"
    )
    assert row["value"] == 153.51
    assert row["source_row"] == 16
    assert len([r for r in first if r["metric"] == "price"]) == 19 * 21
    # The catalog dates publication; the workbook dates the observed prices.
    shifted = parse_release(next(r for r in manifest if r["element_id"] == "67190"))
    assert {r["observation_date"] for r in shifted} == {"2023-06-27"}
    assert {r["catalog_date"] for r in shifted} == {"2023-06-29"}


def test_text_only_excel_and_combined_index():
    manifest = json.loads((ROOT / "data/manifest.json").read_text(encoding="utf-8"))
    text = parse_release(next(r for r in manifest if r["element_id"] == "8826"))
    assert len([r for r in text if r["metric"] == "yoy"]) == 20 * 20
    combined = parse_release(next(r for r in manifest if r["element_id"] == "280698"))
    assert (
        len([r for r in combined if r["metric"] == "wow"])
        == len([r for r in combined if r["metric"] == "ytd"])
        > 0
    )
