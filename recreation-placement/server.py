"""Serve the scenario app and its local calculation API on loopback."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from mimetypes import guess_type
from uuid import uuid4

from model import CACHE, DATA, ROOT, SOURCE, Model

DASHBOARD = ROOT.parent / "dashboard"
ASSETS = {"/": ROOT / "index.html", **{f"/{name}": ROOT / name for name in ("app.js", "style.css")},
          **{f"/shared/{name}": DASHBOARD / name
             for name in ("leaflet.js", "leaflet.css", "style.css", "basemaps.js", "data.js")}}


def make_handler(model):
    jobs = {}
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="calculation")
    baseline = {mode: model.scenario(mode, []) for mode in ("walk", "transit")}

    class Handler(BaseHTTPRequestHandler):
        def send(self, body, content_type, status=200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def reply(self, obj, status=200):
            self.send(json.dumps(obj, ensure_ascii=False, allow_nan=False).encode(),
                      "application/json; charset=utf-8", status)

        def do_GET(self):
            if self.path in ASSETS:
                path = ASSETS[self.path]
                self.send(path.read_bytes(), (guess_type(path)[0] or "text/plain") + "; charset=utf-8")
            elif self.path == "/api/base":
                self.reply(baseline)
            elif self.path.startswith("/api/jobs/") and self.path[10:] in jobs:
                self.reply(jobs[self.path[10:]].copy())
            elif self.path == "/walking.geojson":
                self.send((CACHE / "walking.geojson").read_bytes(), "application/geo+json")
            elif self.path == "/functional-zones.geojson" and (ROOT / "functional-zones.geojson").is_file():
                self.send((ROOT / "functional-zones.geojson").read_bytes(), "application/geo+json")
            else:
                self.reply({"error": "Ресурс не найден"}, 404)

        def do_POST(self):
            if self.path not in {"/api/scenario", "/api/rank"}:
                self.reply({"error": "Ресурс не найден"}, 404)
                return
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 16_384:
                    raise ValueError("Некорректный размер запроса")
                request = json.loads(self.rfile.read(size))
                mode = request["mode"]
                if mode not in baseline:
                    raise ValueError("Выберите режим оценки")
                ranking = self.path == "/api/rank"
                if ranking:
                    model.validate_objects([{"block": 0, "area": request["area"]}])
                else:
                    model.validate_objects(request["objects"])
            except (ValueError, TypeError, KeyError) as error:
                self.reply({"error": str(error)}, 400)
                return
            if len(jobs) >= 24:
                for key, record in list(jobs.items()):
                    if record["status"] in {"done", "error"}:
                        del jobs[key]
                        break
                else:
                    self.reply({"error": "Очередь расчётов заполнена"}, 503)
                    return
            job = uuid4().hex
            jobs[job] = {"status": "queued", "checked": 0, "total": len(model.ids) if ranking else 1}

            def calculate():
                jobs[job]["status"] = "running"
                try:
                    if ranking:
                        result = model.rank(mode, request["area"], lambda checked, _: jobs[job].update(checked=checked))
                    else:
                        result = model.scenario(mode, request["objects"])
                    jobs[job].update(status="done", result=result)
                except Exception as error:
                    jobs[job].update(status="error", error=str(error))

            worker.submit(calculate)
            self.reply({"job": job}, 202)

    return Handler


def walking_layer(model):
    from hashlib import sha256
    import sys

    import geopandas as gpd

    sys.path.insert(0, str(ROOT.parent))
    from my_package.osm_snapshot import _access
    path = CACHE / "walking.geojson"
    key = CACHE / "walking-source.txt"
    source = DATA / "cache" / f"osm-pbf-{model.meta['stage_keys']['osm']}" / "network_ways.parquet"
    signature = sha256((model.signature + model.meta["walk_graph_sha256"]).encode()).hexdigest()
    if path.exists() and key.exists() and key.read_text() == signature:
        return
    ways = gpd.read_parquet(source)
    mask = ways.drop(columns="geometry").apply(lambda row: _access(row.dropna().to_dict(), True), axis=1)
    CACHE.mkdir(exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(ways.loc[mask, ["geometry"]].to_crs(4326).to_json(drop_id=True), encoding="utf-8")
    temporary.replace(path)
    key.write_text(signature)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8033)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    model = Model()
    if args.verify:
        print(json.dumps(model.verify_baseline(), ensure_ascii=False))
        return
    walking_layer(model)
    with ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(model)) as server:
        print(f"http://127.0.0.1:{args.port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
