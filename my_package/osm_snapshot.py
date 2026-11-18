"""Read local OSM features and construct separate walking and driving networks."""

import json
import math
from pathlib import Path
import re
from collections.abc import Mapping

import geopandas as gpd
import networkx as nx
import pandas as pd
import pyogrio


OSM_LAYERS = {
    "points": "node",
    "lines": "way",
    "multilinestrings": "relation",
    "multipolygons": "relation",
}

DRIVE_SPEEDS = {
    "motorway": 90, "trunk": 70, "primary": 60, "secondary": 50,
    "tertiary": 40, "unclassified": 30, "residential": 30,
    "living_street": 20, "service": 15, "road": 30,
}
WALK_TYPES = {
    "footway", "pedestrian", "path", "steps", "track", "bridleway",
    "cycleway", "corridor", *DRIVE_SPEEDS,
} - {"motorway", "trunk"}
ALLOWED = {"yes", "designated", "permissive", "official"}
RESTRICTED = {"no", "private", "agricultural", "forestry", "customers", "permit", "military"}


def _matches(frame, tags):
    mask = pd.Series(False, index=frame.index)
    for name, values in tags.items():
        if name in frame:
            column = frame[name]
            mask |= column.notna() if values is True else column.isin([values] if isinstance(values, str) else values)
    return mask


def _decode_tags(value):
    if isinstance(value, Mapping):
        return value
    if isinstance(value, (str, bytes, bytearray)):
        return json.loads(value)
    if pd.isna(value):
        return {}
    raise TypeError(f"Неизвестный формат тегов GDAL: {type(value).__name__}")


def read_snapshot(path, city, network_extent, river_extent, layer_tags):
    """Keep OSMnx-style tag unions and geometry intersection for each study layer."""
    if pyogrio.list_drivers().get("OSM") is None:
        raise RuntimeError("В установленном GDAL отсутствует драйвер OSM.")
    wanted = set().union(*(tags.keys() for tags in layer_tags.values()), {
        "name", "name:ru", "building:levels", "access", "entrance", "garden:type",
        "bridge", "tunnel", "highway", "layer", "foot", "vehicle", "motor_vehicle",
        "motorcar", "oneway", "oneway:foot", "oneway:motor_vehicle", "oneway:motorcar",
        "junction", "maxspeed", "maxspeed:forward", "maxspeed:backward", "motorroad",
    })
    chunks = {name: [] for name in layer_tags}
    network = []
    rivers = []
    for layer, kind in OSM_LAYERS.items():
        # Read the small city snapshot without a GDAL spatial filter so that
        # the driver can reconstruct ways and relations from all their members.
        raw = pyogrio.read_dataframe(path, layer=layer, TAGS_FORMAT="JSON")
        raw = raw.loc[raw.geometry.notna() & ~raw.geometry.is_empty].copy()
        if raw.empty:
            continue
        in_extent = raw.sindex.query(network_extent.union(river_extent), predicate="intersects")
        raw = raw.iloc[in_extent].reset_index(drop=True)
        if raw.empty:
            continue
        extras = raw.get("other_tags", pd.Series(index=raw.index, dtype=object))
        decoded = pd.DataFrame(
            [{k: v for k, v in _decode_tags(value).items() if k in wanted} for value in extras],
            index=raw.index,
        )
        tags = raw[list(wanted.intersection(raw.columns))].combine_first(decoded).astype("string")
        osm_id = kind + "/" + raw["osm_id"].astype("string")
        if layer == "multipolygons":
            way_id = raw["osm_way_id"].astype("string")
            osm_id = osm_id.mask(way_id.notna(), "way/" + way_id)
        if osm_id.isna().any():
            raise ValueError(f"GDAL не вернул идентификаторы OSM для слоя {layer}.")
        frame = gpd.GeoDataFrame(tags.assign(osm_id=osm_id), geometry=raw.geometry, crs=raw.crs)
        if layer == "lines" and "highway" in frame:
            roads = frame.loc[frame.highway.notna()]
            network.append(roads.iloc[roads.sindex.query(network_extent, predicate="intersects")])
        if layer in {"lines", "multilinestrings"} and "waterway" in frame:
            axes = frame.loc[frame.waterway.eq("river").fillna(False)]
            rivers.append(axes.iloc[axes.sindex.query(river_extent, predicate="intersects")])
        selected = frame.iloc[frame.sindex.query(city, predicate="intersects")]
        for name, tags in layer_tags.items():
            chunks[name].append(selected.loc[_matches(selected, tags)])

    def combine(parts):
        if not parts:
            return gpd.GeoDataFrame({"osm_id": pd.Series(dtype="string")}, geometry=[], crs=4326)
        combined = pd.concat(parts, ignore_index=True)
        return combined.drop_duplicates("osm_id").reset_index(drop=True)

    result = {name: combine(parts) for name, parts in chunks.items()}
    for name in ("structures", "barriers"):
        if result[name].empty:
            raise ValueError(f"В локальном PBF нет объектов обязательного слоя {name}. Проверьте охват.")
    result["network_ways"] = combine(network)
    result["river_axes"] = combine(rivers)
    if result["network_ways"].empty:
        raise ValueError("В локальном PBF нет дорожных линий для построения графов.")
    return result


def _access(tags, walking):
    highway = tags.get("highway", "")
    modes = ("foot",) if walking else ("motorcar", "motor_vehicle", "vehicle")
    explicit = next((tags[mode] for mode in modes if tags.get(mode)), "")
    access = explicit or tags.get("access", "")
    if access in RESTRICTED:
        return False
    if walking:
        return explicit in ALLOWED or (highway.removesuffix("_link") in WALK_TYPES
                                      and tags.get("motorroad") != "yes")
    return highway.removesuffix("_link") in DRIVE_SPEEDS


def _directions(tags, walking):
    if walking:
        oneway = tags.get("oneway:foot", "")
    else:
        oneway = next((tags[k] for k in ("oneway:motorcar", "oneway:motor_vehicle", "oneway")
                       if tags.get(k)), "")
        if not oneway and (tags["highway"] in {"motorway", "motorway_link"}
                           or tags.get("junction") in {"roundabout", "circular"}):
            oneway = "yes"
    return oneway != "-1", oneway not in {"yes", "true", "1"}


def _speed(tags, direction):
    value = tags.get(f"maxspeed:{direction}") or tags.get("maxspeed", "")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(km/h|kph|mph)?", value.strip().lower())
    if match and float(match[1]) > 0:
        return float(match[1]) * (1.609344 if match[2] == "mph" else 1)
    return DRIVE_SPEEDS[tags["highway"].removesuffix("_link")]


def build_network(ways, crs, mode):
    """Use consecutive vertices of each OSM way, without noding geometric crossings."""
    if mode not in {"walk", "drive"}:
        raise ValueError(f"Неизвестный режим: {mode}")
    graph = nx.MultiDiGraph(crs=int(crs.to_epsg()), mode=mode)
    walking = mode == "walk"
    rows = ways.to_crs(crs).explode(index_parts=False, ignore_index=True)
    nodes = {}
    for _, row in rows.iterrows():
        if row.geometry.geom_type != "LineString":
            continue
        tags = row.drop(labels="geometry").dropna().to_dict()
        if not _access(tags, walking):
            continue
        forward, backward = _directions(tags, walking)
        speeds = None if walking else (_speed(tags, "forward"), _speed(tags, "backward"))
        coords = [(x, y) for x, y, *_ in row.geometry.coords]
        grade = tags.get("layer") or (
            "1" if tags.get("bridge", "no") != "no" else "-1" if tags.get("tunnel", "no") != "no" else "0"
        )
        # Bridge and tunnel ends connect to approaches. Intermediate vertices
        # at different grade levels are kept distinct.
        ids = []
        for i, (x, y) in enumerate(coords):
            node_key = x, y, "0" if i in (0, len(coords) - 1) else grade
            if node_key not in nodes:
                nodes[node_key] = len(nodes)
                graph.add_node(nodes[node_key], x=x, y=y)
            ids.append(nodes[node_key])
        for i, (u, v) in enumerate(zip(ids, ids[1:])):
            length = math.dist(coords[i], coords[i + 1])
            if length <= 0:
                continue
            for j, (allowed, a, b) in enumerate(((forward, u, v), (backward, v, u))):
                if allowed:
                    attrs = {"length": length, "osm_id": str(row.osm_id)}
                    if speeds is not None:
                        attrs["time_min"] = length * 0.06 / speeds[j]
                    graph.add_edge(a, b, **attrs)
    graph.remove_nodes_from(list(nx.isolates(graph)))
    if graph.number_of_edges() == 0:
        raise ValueError(f"Из PBF не построен граф {mode}. Проверьте покрытие и теги.")
    return graph


def ensure_graph(path: Path, ways, crs, mode):
    """Reuse a cached GraphML if it exists and can be read."""
    if path.is_file():
        try:
            cached = nx.read_graphml(path)
            if cached.number_of_edges() and cached.graph.get("mode") == mode:
                return path
        except (OSError, ValueError, nx.NetworkXException, SyntaxError):
            pass
    graph = build_network(ways, crs, mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    nx.write_graphml(graph, temporary)
    temporary.replace(path)
    return path
