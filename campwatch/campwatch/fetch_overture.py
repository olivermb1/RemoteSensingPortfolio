"""Building footprints and place names for an area from Overture Maps (free, no login).

    python -m campwatch fetch-places    --bbox 22.36 13.38 22.52 13.52 --out data/places.geojson

Overture's building layer merges Google Open Buildings, Microsoft footprints and
OpenStreetMap, so it covers rural Africa far better than OSM alone. The files
are GeoParquet on a public S3 bucket; only row groups whose bounding box
overlaps --bbox are read (about 30 s and ~100 MB of requests for 300 km2).
Needs pyarrow and shapely.
"""

import json
import os

RELEASE = "2026-09-23.0"
BUCKET = "overturemaps-us-west-2/release"


def _dataset(theme, kind, release):
    import pyarrow.dataset as ds
    import pyarrow.fs as fs
    s3 = fs.S3FileSystem(anonymous=True, region="us-west-2")
    return ds.dataset(f"{BUCKET}/{release}/theme={theme}/type={kind}/", filesystem=s3, format="parquet")


def _bbox_filter(bbox):
    import pyarrow.dataset as ds
    w, s, e, n = bbox
    return ((ds.field("bbox", "xmin") <= e) & (ds.field("bbox", "xmax") >= w)
            & (ds.field("bbox", "ymin") <= n) & (ds.field("bbox", "ymax") >= s))


def _write_geojson(features, out):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f)


def fetch_buildings(bbox, out, release=RELEASE, log=print):
    """Write building footprints (EPSG:4326 GeoJSON, properties id and source dataset)."""
    import shapely
    d = _dataset("buildings", "building", release)
    t = d.to_table(columns=["id", "geometry", "sources"], filter=_bbox_filter(bbox))
    geoms = shapely.from_wkb(t["geometry"].to_numpy(zero_copy_only=False))
    srcs = [(s[0]["dataset"] if s else None) for s in t["sources"].to_pylist()]
    feats = [{"type": "Feature", "properties": {"id": i, "source": s}, "geometry": shapely.geometry.mapping(g)}
             for i, s, g in zip(t["id"].to_pylist(), srcs, geoms)]
    _write_geojson(feats, out)
    counts = {}
    for s in srcs:
        counts[s] = counts.get(s, 0) + 1
    log(f"{len(feats)} buildings ({counts}) -> {out}")
    return len(feats)


def fetch_places(bbox, out, release=RELEASE, log=print):
    """Write named settlements (towns, villages, hamlets, neighbourhoods) as points."""
    import pyarrow.dataset as ds
    import shapely
    d = _dataset("divisions", "division", release)
    flt = _bbox_filter(bbox) & ds.field("subtype").isin(["locality", "localadmin", "neighborhood", "microhood", "macrohood"])
    t = d.to_table(columns=["id", "geometry", "subtype", "class", "names"], filter=flt)
    feats = []
    for i, g, st, cl, nm in zip(t["id"].to_pylist(), shapely.from_wkb(t["geometry"].to_numpy(zero_copy_only=False)),
                                t["subtype"].to_pylist(), t["class"].to_pylist(), t["names"].to_pylist()):
        name = (nm or {}).get("primary")
        common = dict((nm or {}).get("common") or [])
        feats.append({"type": "Feature", "geometry": shapely.geometry.mapping(g.representative_point()),
                      "properties": {"id": i, "name": name, "name_en": common.get("en"), "subtype": st, "class": cl}})
    _write_geojson(feats, out)
    log(f"{len(feats)} places -> {out}")
    return len(feats)
