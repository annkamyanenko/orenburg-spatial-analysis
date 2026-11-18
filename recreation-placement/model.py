"""Local network routing and competitive allocation for practice 3."""
from functools import lru_cache
from hashlib import file_digest, sha256
import json
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent / "data/orenburg"
SOURCE = DATA / "results/8d64d1206ffa9bd94e07cad3"
CACHE = ROOT / ".cache"
MODES = {"walk": 1000, "transit": 10}
SNAP = 100
APPROACH = 15


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite(value):
    return float(value) if np.isfinite(value) else None


class Network:
    def __init__(self, path, weight, crs):
        graph = nx.read_graphml(path)
        nodes = list(graph)
        order = {node: i for i, node in enumerate(nodes)}
        points = gpd.points_from_xy([graph.nodes[n]["x"] for n in nodes],
                                    [graph.nodes[n]["y"] for n in nodes], crs=graph.graph["crs"])
        self.points = gpd.GeoSeries(points).to_crs(crs)
        self.tree = cKDTree(np.column_stack([self.points.x, self.points.y]))
        edges = {}
        for u, v, data in graph.edges(data=True):
            i, j, value = order[u], order[v], float(data[weight])
            edges[i, j] = min(value, edges.get((i, j), np.inf))
            if not graph.is_directed():
                edges[j, i] = min(value, edges.get((j, i), np.inf))
        row, col = zip(*edges)
        self.graph = csr_matrix((list(edges.values()), (row, col)), shape=(len(nodes), len(nodes)))
        self.reverse = self.graph.T.tocsr()

    def snap(self, points):
        distances, indices = self.tree.query(np.column_stack([points.x, points.y]))
        return distances, indices


class Model:
    def __init__(self):
        self.meta = json.loads((SOURCE / "metadata.json").read_text(encoding="utf-8"))
        inputs = ["blocks.geojson", "blocks_attributes.csv", "resources.geojson",
                  *(f"{mode}_{kind}.csv" for mode in MODES for kind in ("routes", "allocation"))]
        for name in inputs:
            require(digest(SOURCE / name) == self.meta["files"][name], f"Изменилась выгрузка: {name}")
        graph_root = DATA / "cache" / ("graphs-" + self.meta["stage_keys"]["osm"])
        self.paths = {"walk": graph_root / "walk.graphml", "transit": graph_root / "drive.graphml"}
        for mode, field in (("walk", "walk_graph_sha256"), ("transit", "graph_sha256")):
            require(digest(self.paths[mode]) == self.meta[field], f"Граф {mode} отличается от практики № 2")
        self.signature = sha256(json.dumps([self.meta["files"], self.meta["graph_sha256"],
                                            self.meta["walk_graph_sha256"], digest(Path(__file__))],
                                          sort_keys=True).encode()).hexdigest()[:20]
        self.attributes = pd.read_csv(SOURCE / "blocks_attributes.csv", index_col="block_id").sort_index()
        self.ids = self.attributes.index.to_numpy(dtype=int)
        self.demand = self.attributes.population.to_numpy(dtype=np.int64) * 11
        require(len(self.ids) == 2233 and np.array_equal(self.ids, np.arange(len(self.ids))),
                "Ожидаются 2233 квартала с последовательными идентификаторами")
        require(np.array_equal(self.demand, self.attributes.recreation_demand_m2), "Не совпадает спрос")
        self.blocks = gpd.read_file(SOURCE / "blocks.geojson").set_index("block_id").loc[self.ids].to_crs(self.meta["metric_crs"])
        self.origins = self.blocks.representative_point()
        resources = gpd.read_file(SOURCE / "resources.geojson").set_index("resource_id").sort_index()
        self.capacity = np.floor(resources.resource_area_m2.to_numpy()).astype(np.int64)
        require(np.array_equal(resources.index, np.arange(len(resources))), "Не совпадают ID ресурсов")
        self.inventory = float(resources.resource_area_m2.sum())
        self.routes = {mode: pd.read_csv(SOURCE / f"{mode}_routes.csv") for mode in MODES}
        self.base = {mode: self.attributes[f"{mode}_deficit_m2"].to_numpy() for mode in MODES}
        self.bound = {mode: self.attributes[f"{mode}_origin_bound"].to_numpy(dtype=bool) for mode in MODES}
        self.memo = {}

    @lru_cache(maxsize=2)
    def network(self, mode):
        return Network(self.paths[mode], "length" if mode == "walk" else "time_min", self.blocks.crs)

    @lru_cache(maxsize=1)
    def access_points(self):
        points = self.network("walk").points
        block_row, point_row = points.sindex.query(self.blocks.geometry.buffer(APPROACH), predicate="intersects")
        origins = self.origins.array
        dist = points.iloc[point_row].array.distance(origins[block_row])
        pairs = pd.DataFrame({"block": block_row, "node": point_row, "dist": dist})
        chosen = pairs.sort_values(["block", "dist", "node"]).drop_duplicates("block")
        index = chosen.set_index("block").node.reindex(self.ids, fill_value=-1).to_numpy()
        coords = np.full((len(self.ids), 2), np.nan)
        has_point = index >= 0
        coords[has_point] = np.column_stack([points.iloc[index[has_point]].x, points.iloc[index[has_point]].y])
        return index, coords

    @lru_cache(maxsize=2)
    def candidate_routes(self, mode):
        path = CACHE / f"{self.signature}-{mode}.npz"
        if path.exists():
            with np.load(path) as source:
                return source["costs"], source["bound"]
        network = self.network(mode)
        nodes, coords = self.access_points()
        has_point = nodes >= 0
        origin_distance, origin_node = network.snap(self.origins)
        require(np.array_equal(origin_distance <= SNAP, self.bound[mode]), "Привязка источников отличается от базы")
        target_distance, target_node = network.snap(gpd.GeoSeries(
            gpd.points_from_xy(*coords[has_point].T), crs=self.blocks.crs))
        selected = np.flatnonzero(has_point)[target_distance <= SNAP]
        destinations = target_node[target_distance <= SNAP]
        offsets = target_distance[target_distance <= SNAP]
        bound = np.zeros(len(self.ids), dtype=bool)
        bound[selected] = True
        costs = np.full((len(self.ids), len(self.ids)), np.inf, dtype=np.float64)
        origins = np.flatnonzero(self.bound[mode] & (self.demand > 0))
        limit = MODES[mode]
        for node, indexes in pd.Series(np.arange(len(selected)), index=destinations).groupby(level=0):
            distances = dijkstra(network.reverse, indices=int(node), limit=limit)[origin_node[origins]]
            if mode == "walk":
                distances = distances + origin_distance[origins]
            for i in indexes:
                total = distances + offsets[i] if mode == "walk" else distances
                passed = total <= limit
                costs[selected[i], origins[passed]] = total[passed]
        CACHE.mkdir(exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with temporary.open("wb") as stream:
            np.savez_compressed(stream, costs=costs, bound=bound)
        temporary.replace(path)
        return costs, bound

    def validate_objects(self, objects):
        require(isinstance(objects, list) and len(objects) <= 2, "Допускается не более двух объектов")
        result = []
        for item in objects:
            require(isinstance(item, dict), "Некорректный объект сценария")
            block, area = item.get("block"), item.get("area")
            require(type(block) is int and 0 <= block < len(self.ids), "Выберите квартал")
            require(type(area) is int and 0 < area <= 2**53 - 1, "Площадь должна быть положительным целым числом")
            result.append((block, area))
        return tuple(sorted(result))

    @lru_cache(maxsize=2)
    def base_edges(self, mode):
        source = self.routes[mode]
        i, j, cost = (source[key].to_numpy() for key in ("block_id", "resource_id", "cost"))
        valid = (self.demand[i] > 0) & (self.capacity[j] > 0)
        return i[valid], j[valid], cost[valid]

    def edges(self, mode, objects):
        i, j, cost = self.base_edges(mode)
        areas = self.capacity
        if not objects:
            return i, j, cost, areas
        candidates, bound = self.candidate_routes(mode)
        origins, targets, distances = [i], [j], [cost]
        for k, (block, _) in enumerate(objects):
            if not bound[block]:
                continue
            valid = np.flatnonzero(np.isfinite(candidates[block]))
            origins.append(valid)
            targets.append(np.full(len(valid), len(areas) + k))
            distances.append(candidates[block, valid])
        return (np.concatenate(origins), np.concatenate(targets), np.concatenate(distances),
                np.r_[areas, [area for _, area in objects]].astype(np.int64))

    def solve(self, mode, objects, reference=False):
        i, j, cost, areas = self.edges(mode, objects)
        if not len(i):
            return np.zeros(len(self.ids), dtype=np.int64), 0.0
        weights = self.demand[i].astype(float) * areas[j] / (cost + 1)
        if reference:
            from blocksnet.analysis.provision import competitive_provision
            active_i, row = np.unique(i, return_inverse=True)
            active_j, col = np.unique(j, return_inverse=True)
            n = len(active_i)
            index = pd.RangeIndex(n + len(active_j))
            matrix = np.full((len(index), len(index)), np.inf)
            matrix[row, col + n] = cost
            np.fill_diagonal(matrix, 0)
            inputs = pd.DataFrame({"demand": np.r_[self.demand[active_i], np.zeros(len(active_j), dtype=int)],
                                   "capacity": np.r_[np.zeros(n, dtype=int), areas[active_j]]}, index=index)
            _, allocation = competitive_provision(inputs, pd.DataFrame(matrix, index=index, columns=index),
                                                  MODES[mode], self_supply=False, max_depth=1)
            actual = allocation.value.reindex(pd.MultiIndex.from_arrays([row, col + n]), fill_value=0).to_numpy()
        else:
            e = np.arange(len(i))
            incidence = csr_matrix((np.ones(2 * len(e)), (np.r_[i, j + len(self.ids)], np.tile(e, 2))),
                                   shape=(len(self.ids) + len(areas), len(e)))
            result = linprog(-weights / weights.max(), A_ub=incidence, b_ub=np.r_[self.demand, areas],
                             method="highs-ds", options={"dual_feasibility_tolerance": 1e-9})
            if not result.success:
                raise RuntimeError(result.message)
            actual = result.x
        flow = np.rint(actual).astype(np.int64)
        served = np.zeros(len(self.ids), dtype=np.int64)
        used = np.zeros(len(areas), dtype=np.int64)
        np.add.at(served, i, flow)
        np.add.at(used, j, flow)
        if (not np.allclose(flow, actual, atol=1e-5, rtol=0) or (flow < 0).any()
                or (served > self.demand).any() or (used > areas).any()):
            raise RuntimeError("Оптимизатор нарушил целочисленность или баланс площадей")
        return served, float(weights @ flow)

    def verify_baseline(self):
        result = {}
        for mode in MODES:
            reference, objective = self.solve(mode, (), reference=True)
            fast, fast_objective = self.solve(mode, ())
            saved = self.attributes[f"{mode}_assigned_m2"].fillna(0).to_numpy()
            require(np.array_equal(reference, saved), f"BlocksNet не воспроизводит базу: {mode}")
            require(np.isclose(fast_objective, objective, rtol=1e-8) and fast.sum() == reference.sum(),
                    f"Разрежённая модель отличается по цели или дефициту: {mode}")
            result[mode] = {"assigned": int(reference.sum()), "deficit": int(np.nansum(self.base[mode])),
                            "same_quarters": bool(np.array_equal(fast, reference))}
        return result

    def score(self, mode, objects):
        if not objects:
            return self.demand - np.nan_to_num(self.base[mode], nan=0).astype(np.int64)
        key = mode, objects
        if key not in self.memo:
            if len(self.memo) >= 16:
                self.memo.pop(next(iter(self.memo)))
            self.memo[key] = self.solve(mode, objects)[0]
        return self.memo[key]

    def scenario(self, mode, objects):
        require(mode in MODES, "Неизвестный режим сети")
        objects = self.validate_objects(objects)
        served = self.score(mode, objects)
        observed = self.bound[mode]
        deficit = np.where(observed, self.demand - served, np.nan)
        base = self.base[mode]
        area = sum(area for _, area in objects)
        denominator = int(self.demand[observed].sum())
        coords = self.access_points()[1] if objects else None
        bound = self.candidate_routes(mode)[1] if objects else None
        marks = [{"block": block, "area": size, "point": self.point(coords[block]), "bound": bool(bound[block])}
                 for block, size in objects]
        return {"mode": mode, "objects": marks, "area": area, "inventory": self.inventory,
                "baseline_deficit": int(np.nansum(base)), "deficit": int(np.nansum(deficit)),
                "gain": int(np.nansum(base) - np.nansum(deficit)), "demand": denominator,
                "bound_population": denominator // 11,
                "rows": [[int(i), int(d), finite(b), finite(s), finite(b - s)]
                         for i, d, b, s in zip(self.ids, self.demand, base, deficit)]}

    def point(self, coord):
        if not np.isfinite(coord).all():
            return None
        point = gpd.GeoSeries(gpd.points_from_xy([coord[0]], [coord[1]]), crs=self.blocks.crs).to_crs(4326).iloc[0]
        return [point.y, point.x]

    def rank(self, mode, area, progress):
        require(mode in MODES, "Неизвестный режим сети")
        self.validate_objects([{"block": 0, "area": area}])
        path = CACHE / f"ranking-{self.signature}-{mode}-{area}.json"
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            progress(len(self.ids), len(self.ids))
            return saved
        costs, bound = self.candidate_routes(mode)
        total = len(self.ids)
        rows = []
        baseline = int(np.nansum(self.base[mode]))
        observed = self.bound[mode]
        for done, block in enumerate(self.ids, 1):
            i = int(block)
            if not bound[i]:
                rows.append({"block": i, "gain": None, "status": "unbound"})
            elif not np.isfinite(costs[i]).any():
                rows.append({"block": i, "gain": 0, "status": "calculated"})
            else:
                try:
                    served, _ = self.solve(mode, ((i, area),))
                    rows.append({"block": i, "gain": baseline - int((self.demand - served)[observed].sum()),
                                 "status": "calculated"})
                except RuntimeError as error:
                    rows.append({"block": i, "gain": None, "status": "failed", "error": str(error)})
            progress(done, total)
        rows.sort(key=lambda item: (item["gain"] is None, -(item["gain"] or 0), item["block"]))
        best = rows[0]["gain"]
        result = {"mode": mode, "area": area, "rows": rows, "total": total,
                  "best": [item["block"] for item in rows if best is not None and item["gain"] == best],
                  "complete": not any(item["status"] == "failed" for item in rows)}
        if result["complete"]:
            atomic_json(path, result)
        return result
