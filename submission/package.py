"""Create local delivery artifacts without rebuilding the applications or source data."""
from hashlib import file_digest
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "submission/artifacts"
DATA = ROOT / "data/orenburg"
EXPORT = DATA / "results/8d64d1206ffa9bd94e07cad3"
BOUNDARY = DATA / "cache/boundary-25690f23b4a3bc4ff732ff8e"


def checksum(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def dashboard():
    source = ROOT / "dashboard"
    html = (source / "index.html").read_text(encoding="utf-8")
    for name in ("leaflet.css", "style.css"):
        html = html.replace(f'<link rel="stylesheet" href="{name}">',
                            f'<style>\n{(source / name).read_text(encoding="utf-8")}\n</style>')
    scripts = []
    for name in ("leaflet.js", "data.js", "basemaps.js", "app.js"):
        html = html.replace(f'<script defer src="{name}"></script>', "")
        script = (source / name).read_text(encoding="utf-8")
        if "</script" in script.lower():
            raise ValueError(f"Закрывающий тег внутри {name}")
        if name == "leaflet.js":
            license_text = (source / "leaflet.LICENSE.txt").read_text(encoding="utf-8")
            script = f"/*\n{license_text}\n*/\n{script}"
        scripts.append(f"<script>\n{script}\n</script>")
    (DEST / "dashboard.html").write_text(html.replace("</body>", "\n".join(scripts) + "\n</body>"),
                                        encoding="utf-8")


def data_package():
    metadata = json.loads((EXPORT / "metadata.json").read_text(encoding="utf-8"))
    osm_key = metadata["stage_keys"]["osm"]
    graph_dir = DATA / "cache" / f"graphs-{osm_key}"
    walks = DATA / "cache" / f"osm-pbf-{osm_key}" / "network_ways.parquet"
    raw = DATA / "raw/orenburg.osm.pbf"
    drive, walk = graph_dir / "drive.graphml", graph_dir / "walk.graphml"
    payload = {EXPORT / name: expected for name, expected in metadata["files"].items()}
    payload.update({raw: metadata["osm_snapshot"]["sha256"], drive: metadata["graph_sha256"],
                    walk: metadata["walk_graph_sha256"]})
    for path, expected in payload.items():
        if checksum(path) != expected:
            raise ValueError(f"Контрольная сумма не совпадает: {path.name}")
    payload.update({path: checksum(path) for path in
                    (walks, BOUNDARY / "manifest.json", BOUNDARY / "city.parquet")})
    for field, path in (("osm_snapshot", raw), ("transport_graph", drive)):
        metadata[field]["path"] = path.relative_to(ROOT).as_posix()
    metadata["walk_graph"] = walk.relative_to(ROOT).as_posix()
    destination = DEST / "orenburg-data.zip"
    temp = destination.with_suffix(".tmp")
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in payload:
            archive.write(path, path.relative_to(ROOT).as_posix())
        archive.writestr((EXPORT / "metadata.json").relative_to(ROOT).as_posix(),
                         json.dumps(metadata, ensure_ascii=False, indent=2))
    temp.replace(destination)
    for path in (destination, DEST / "dashboard.html"):
        print(f"{path.name}: {path.stat().st_size:,} bytes, SHA-256 {checksum(path)}")


if __name__ == "__main__":
    DEST.mkdir(parents=True, exist_ok=True)
    dashboard()
    data_package()
