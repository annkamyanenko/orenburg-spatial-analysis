"""Calibrate population and infer potential access points from a walking graph."""

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import shapely as shp


def calibrate_population(population, target):
    values = population.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any() or values.sum() <= 0:
        raise ValueError("Исходные оценки населения должны быть конечными и неотрицательными.")
    if isinstance(target, bool) or not isinstance(target, int) or target <= 0:
        raise ValueError("Статистическая численность должна быть положительным целым числом.")
    scaled = values * (target / values.sum())
    counts = np.floor(scaled).astype(np.int64)
    remainder = target - counts.sum()
    order = np.argsort(-(scaled - counts), kind="stable")
    counts[order[:remainder]] += 1
    if counts.sum() != target or (counts[values == 0] != 0).any():
        raise ValueError("Калибровка нарушила баланс населения.")
    return pd.Series(counts, index=population.index, name="population")


def _walk_segments(path, crs, grade_separated):
    graph = nx.read_graphml(path)
    shapes = []
    seen = set()
    for u, v, attrs in graph.edges(data=True):
        if attrs.get("osm_id") in grade_separated:
            continue
        geometry = attrs.get("geometry")
        key = (frozenset((u, v)), geometry)
        if key in seen:
            continue
        seen.add(key)
        if geometry:
            shapes.append(shp.from_wkt(geometry))
        else:
            shapes.append(shp.LineString([(float(graph.nodes[n]["x"]), float(graph.nodes[n]["y"]))
                                          for n in (u, v)]))
    return gpd.GeoSeries(shapes, crs=graph.graph["crs"]).to_crs(crs)


def _junction_points(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type == "Point":
        yield geometry
    elif geometry.geom_type == "LineString":
        yield shp.Point(geometry.coords[0])
        yield shp.Point(geometry.coords[-1])
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from _junction_points(part)


def infer_entrances(resources, observed, walk_path, grade_separated, spacing_m):
    segments = _walk_segments(walk_path, resources.crs, grade_separated)
    boundaries = resources.boundary
    resource_pos, segment_pos = segments.sindex.query(boundaries, predicate="intersects")
    intersections = shp.intersection(
        boundaries.iloc[resource_pos].array, segments.iloc[segment_pos].array
    )
    candidates = {}
    for index, geometry in zip(resource_pos, intersections):
        resource_id = resources.resource_id.iloc[index]
        candidates.setdefault(resource_id, []).extend(_junction_points(geometry))
    fixed = {key: list(points.geometry) for key, points in observed.groupby("resource_id")}
    inferred = []
    for key, points in sorted(candidates.items()):
        anchors = fixed.get(key, [])
        for point in sorted(points, key=lambda point: (point.x, point.y)):
            if any(point.distance(anchor) <= spacing_m for anchor in anchors):
                continue
            anchors.append(point)
            inferred.append({"resource_id": key, "source": "Примыкание пешей сети",
                             "entrance_kind": "potential", "offset_m": np.nan, "geometry": point})
    base = observed.assign(entrance_kind="observed")
    if inferred:
        potential = gpd.GeoDataFrame(inferred, geometry="geometry", crs=resources.crs)
        base = pd.concat([base, potential], ignore_index=True)
    base = base.reset_index(drop=True)
    base.index.name = "entrance_id"
    output = resources.copy()
    for kind in ("observed", "potential"):
        counts = base.loc[base.entrance_kind.eq(kind), "resource_id"].value_counts()
        output[f"{kind}_entry_count"] = output.resource_id.map(counts).fillna(0).astype(int)
    output["entry_count"] = output.observed_entry_count + output.potential_entry_count
    return {"resources": output, "entrances": base}
