"""Validate the practice 2 export and prepare a compact, static browser payload."""
import argparse
import csv
from hashlib import file_digest
import json
import math
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "data/orenburg/results/8d64d1206ffa9bd94e07cad3"
FIELDS = """block_id stable_id site_area population population_original population_ha fsi gsi l mxi
osr share_living share_non_living
spacematrix strelka land_use land_use_unknown riparian riparian_share green_share attractor_count
attractors_km2 transport_bound transport_snap_m reachable_area_share reachable_bound_area_share
reachable_area_time_min walk_nearest transit_nearest walk_origin_bound transit_origin_bound
walk_satisfied transit_satisfied walk_deficit_m2 transit_deficit_m2 walk_m2_person transit_m2_person
local_recreation_m2 local_m2_person recreation_demand_m2""".split()
LAYERS = {
    "city": (), "water": ("name",), "green": (), "riparian": ("zone_type",),
    "attractors": ("name", "category"), "barriers": ("kind",),
    "bridges": ("name",), "crossings": ("name", "highway", "railway"),
    "resources": ("name", "resource_area_m2", "observed_entry_count", "potential_entry_count"),
    "entrances": ("entrance_kind", "resource_id", "entrance_id"),
}


def check(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(source, name):
    return json.loads((source / name).read_text(encoding="utf-8-sig"))


def table(source, name):
    with (source / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def agrees(actual, expected):
    return math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-8)


def matches_csv(value, raw):
    if value is None:
        return raw == ""
    if isinstance(value, bool):
        return str(value) == raw
    if isinstance(value, (int, float)):
        return raw != "" and agrees(value, float(raw))
    return value == raw


def compact(feature, fields):
    def rounded(values):
        if isinstance(values, list):
            return [rounded(value) for value in values]
        return round(values, 6)

    def geometry(value):
        if value["type"] == "GeometryCollection":
            return {"type": value["type"], "geometries": [geometry(part) for part in value["geometries"]]}
        return {"type": value["type"], "coordinates": rounded(value["coordinates"])}

    return {
        "type": "Feature", "geometry": geometry(feature["geometry"]),
        "properties": {key: feature["properties"].get(key) for key in fields},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE,
                        help="Каталог выгрузки с metadata.json")
    args = parser.parse_args()
    prepare(args.source.resolve())


def prepare(source):
    metadata = read_json(source, "metadata.json")
    check(metadata["signature"] == source.name, "Имя каталога не совпадает с идентификатором выгрузки")
    for name, checksum in metadata["files"].items():
        with (source / name).open("rb") as stream:
            check(file_digest(stream, "sha256").hexdigest() == checksum, f"Нарушена контрольная сумма {name}")
    blocks = read_json(source, "blocks.geojson")["features"]
    attributes = table(source, "blocks_attributes.csv")
    by_id = {row["block_id"]: row for row in attributes}
    ids = {str(feature["properties"]["block_id"]) for feature in blocks}
    check(len(ids) == len(blocks) == len(by_id) == len(attributes) and ids == set(by_id),
          "Идентификаторы кварталов не согласованы")
    props = [feature["properties"] for feature in blocks]
    for block in props:
        row = by_id[str(block["block_id"])]
        for field in FIELDS:
            check(matches_csv(block[field], row[field]), f"Расхождение {field} в квартале {block['block_id']}")
        check(block["site_area"] > 0, "Неположительная площадь")
        for field in ("gsi", "mxi", "green_share", "riparian_share", "reachable_area_share",
                      "reachable_bound_area_share", "walk_satisfied", "transit_satisfied"):
            value = block[field]
            check(value is None or 0 <= value <= 1 + 1e-8, f"Доля вне диапазона: {field}")
        check(agrees(block["population_ha"], block["population"] * 10_000 / block["site_area"]), "Плотность")
        check(agrees(block["recreation_demand_m2"], block["population"] * metadata["parameters"]["recreation_m2_person"]), "Спрос")
        for mode, limit in (("walk", "walk_limit_m"), ("transit", "transport_limit_min")):
            value = block[f"{mode}_nearest"]
            check(value is None or 0 <= value <= metadata["parameters"][limit], "Время или расстояние вне порога")
            check(block[f"{mode}_origin_bound"] or block[f"{mode}_satisfied"] is None, "Пропуск представлен числом")
    layers = {name: read_json(source, name + ".geojson")["features"] for name in LAYERS}
    resources = [item["properties"] for item in layers["resources"]]
    entrances = [item["properties"] for item in layers["entrances"]]
    for kind in ("observed", "potential"):
        check(sum(item["entrance_kind"] == kind for item in entrances)
              == sum(item[f"{kind}_entry_count"] for item in resources) == metadata["access_points"][kind],
              "Расхождение инвентаря входов")
    stats = [float(row["value"]) for row in table(source, "city_summary.csv")]
    population, original = (sum(item[field] for item in props) for field in ("population", "population_original"))
    resource_area = sum(item["resource_area_m2"] for item in resources)
    check(agrees(original, stats[0]) and agrees(population, stats[1]), "Итог населения")
    check(agrees(resource_area, stats[6]) and agrees(resource_area / population, stats[8]), "Итог площади ресурсов")
    check(agrees(sum(item["recreation_demand_m2"] for item in props), stats[5]), "Итог спроса")
    diagnostics = {row[""]: float(row["value"]) for row in table(source, "transport_diagnostics.csv")}
    bound = [item for item in props if item["transport_bound"]]
    check(len(bound) == diagnostics["blocks_bound"], "Число привязанных кварталов")
    check(agrees(sum(item["site_area"] for item in bound) / sum(item["site_area"] for item in props),
                 diagnostics["bound_area_share"]), "Площадь привязанных кварталов")
    check(agrees(median(item["reachable_area_share"] for item in props), diagnostics["median_reachable_area_share"]),
          "Медиана от всей площади")
    check(agrees(median(item["reachable_bound_area_share"] for item in bound if item["reachable_bound_area_share"] is not None),
                 diagnostics["median_reachable_bound_area_share"]), "Медиана среди привязанных")
    groups = table(source, "comparison.csv")
    for row in groups:
        group = [item for item in props if item["riparian"] == (row["group"] == "Приречные")]
        for field in ("population", "population_original"):
            check(agrees(sum(item[field] for item in group), float(row[field])), f"Сравнение групп: {field}")
        check(len(group) == int(row["blocks"]), "Число кварталов в группе")
        check(agrees(sum(item["local_recreation_m2"] for item in group), float(row["local_recreation_m2"])), "Площадь группы")
        check(agrees(sum(item["local_recreation_m2"] for item in group) / sum(item["population"] for item in group),
                     float(row["recreation_m2_person"])), "Обеспеченность группы на жителя")
    payload = {
        "signature": metadata["signature"],
        "blocks": [compact(item, FIELDS) for item in blocks],
        "layers": {name: [compact(item, LAYERS[name]) for item in content] for name, content in layers.items()},
        "groups": [{key: value if key == "group" else float(value) if value else None for key, value in row.items()}
                   for row in groups],
        "diagnostics": diagnostics, "parameters": metadata["parameters"],
        "summary": dict(population=population, original=original, factor=stats[2], demand=stats[5],
                        recreation_area=resource_area, per_person=stats[8],
                        observed=metadata["access_points"]["observed"],
                        potential=metadata["access_points"]["potential"]),
    }
    destination = ROOT / "data.js"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text("window.ORENBURG = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False) + ";\n", encoding="utf-8")
    temporary.replace(destination)
    print(f"Validated {len(blocks)} blocks, {len(entrances)} entrances and {len(metadata['files'])} checksums.")


if __name__ == "__main__":
    main()
