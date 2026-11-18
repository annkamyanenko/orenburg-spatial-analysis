"""Run end-to-end numerical checks on the frozen practice 2 research data."""
import json
import time

import geopandas as gpd
import numpy as np
import pyarrow.parquet as pq
from scipy.sparse.csgraph import dijkstra

from model import MODES, SNAP, SOURCE, Model, digest, require


def check_network(model, mode, block):
    network = model.network(mode)
    distances, origin_nodes = network.snap(model.origins)
    _, coordinates = model.access_points()
    point = gpd.GeoSeries(gpd.points_from_xy([coordinates[block, 0]], [coordinates[block, 1]]),
                          crs=model.blocks.crs)
    offset, target = network.snap(point)
    require(offset[0] <= SNAP, "Контрольный объект вне привязки")
    cached = model.candidate_routes(mode)[0][block]
    eligible = np.flatnonzero(model.bound[mode] & (model.demand > 0))
    for origin in eligible[np.linspace(0, len(eligible) - 1, 16, dtype=int)]:
        forward = dijkstra(network.graph, indices=int(origin_nodes[origin]), limit=MODES[mode])[target[0]]
        if mode == "walk":
            forward += distances[origin] + offset[0]
        expected = forward if forward <= MODES[mode] else np.inf
        require(np.isclose(expected, cached[origin]), "Обратный поиск не совпал с прямым")


def main():
    model = Model()
    path = SOURCE / "transport_matrix_min.parquet"
    require(digest(path) == model.meta["files"][path.name], "Нарушена контрольная сумма матрицы")
    parquet = pq.ParquetFile(path)
    require(parquet.schema.names == list(map(str, model.ids)), "Столбцы матрицы отличаются")
    # This export stores the sequential block IDs in a pandas RangeIndex.
    index = json.loads(parquet.metadata.metadata[b"pandas"])["index_columns"]
    require(index == [{"kind": "range", "name": "block_id", "start": 0, "stop": 2233, "step": 1}],
            "Строки матрицы отличаются")
    baseline = model.verify_baseline()
    print("BASE", json.dumps(baseline))
    for area in (0, -1, 1.25, "6000", True):
        try:
            model.validate_objects([{"block": 1, "area": area}])
        except ValueError:
            continue
        raise AssertionError("Принята недопустимая площадь")
    report = {}
    for mode in MODES:
        start = time.monotonic()
        progress = []
        ranking = model.rank(mode, 6000, lambda count, total: progress.append((count, total)))
        rows = ranking["rows"]
        assert ranking["complete"] and len(rows) == 2233 and {r["block"] for r in rows} == set(model.ids)
        assert progress[-1] == (2233, 2233)
        good = [row for row in rows if row["status"] == "calculated"]
        assert len(good) and all(good[i]["gain"] >= good[i + 1]["gain"] for i in range(len(good) - 1))
        assert ranking["best"] == [row["block"] for row in good if row["gain"] == good[0]["gain"]]
        best = good[0]["block"]
        check_network(model, mode, best)
        samples = [((good[i]["block"], 6000),) for i in (0, len(good) // 2, len(good) - 1)]
        samples.append(((314, 3000), (779, 3000)))
        for objects in samples:
            old, objective = model.solve(mode, objects, reference=True)
            new, fast_objective = model.solve(mode, objects)
            assert np.isclose(objective, fast_objective, rtol=1e-8) and old.sum() == new.sum()
        a = model.scenario(mode, [{"block": best, "area": 6000}])
        b = model.scenario(mode, [{"block": 314, "area": 3000}, {"block": 779, "area": 3000}])
        assert a["gain"] == good[0]["gain"] and a["area"] == b["area"] == 6000
        assert model.scenario(mode, [{"block": best, "area": 6000}]) == a
        assert model.scenario(mode, [])["deficit"] == baseline[mode]["deficit"]
        for scenario in (a, b):
            assert len(scenario["rows"]) == 2233
            assert sum(row[3] for row in scenario["rows"] if row[3] is not None) == scenario["deficit"]
            assert sum(row[4] for row in scenario["rows"] if row[4] is not None) == scenario["gain"]
        report[mode] = {"calculated": len(good), "unbound": len(rows) - len(good),
                        "best_count": len(ranking["best"]), "first_best": best, "max_gain": a["gain"],
                        "two_objects_gain": b["gain"], "checks_seconds": round(time.monotonic() - start, 1)}
        print("CHECKED", mode, json.dumps(report[mode]), flush=True)


if __name__ == "__main__":
    main()
