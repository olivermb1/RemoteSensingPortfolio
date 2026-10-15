"""Turn building footprints into reporting units (settlements and town blocks).

Villages: buildings within `link` metres of each other are joined into one
settlement. Towns: a settlement bigger than `max_km2` is cut into `cell`-metre
square blocks, so a burned neighbourhood is not averaged away across a whole
city. Needs geopandas and shapely 2.
"""

import numpy as np


def utm_crs(lon, lat):
    return f"EPSG:{(32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1}"


def settlements(buildings, link=40.0, max_km2=0.5, cell=250.0, min_buildings=5):
    """buildings: GeoDataFrame in a metric CRS. Returns GeoDataFrame of units with
    unit_id, kind ('settlement' or 'block'), n_buildings, area_ha."""
    import geopandas as gpd
    import shapely

    pts = buildings.geometry.representative_point()
    blobs = shapely.unary_union(shapely.buffer(buildings.geometry.values, link / 2, quad_segs=2))
    parts = list(getattr(blobs, "geoms", [blobs]))
    units, kinds = [], []
    for g in parts:
        if g.area / 1e6 <= max_km2:
            units.append(g)
            kinds.append("settlement")
            continue
        x0, y0, x1, y1 = g.bounds
        x0, y0 = np.floor(x0 / cell) * cell, np.floor(y0 / cell) * cell  # grid aligned to round coordinates
        for x in np.arange(x0, x1, cell):
            for y in np.arange(y0, y1, cell):
                piece = g.intersection(shapely.box(x, y, x + cell, y + cell))
                if not piece.is_empty and piece.area > 0:
                    units.append(piece)
                    kinds.append("block")
    u = gpd.GeoDataFrame({"kind": kinds}, geometry=units, crs=buildings.crs)
    u["n_buildings"] = count_points(u, pts)
    u = u[u.n_buildings >= min_buildings].reset_index(drop=True)
    u.insert(0, "unit_id", np.arange(1, len(u) + 1))
    u["area_ha"] = (u.geometry.area / 1e4).round(2)
    return u


def count_points(units, pts):
    import geopandas as gpd
    j = gpd.sjoin(gpd.GeoDataFrame(geometry=pts.values, crs=units.crs), units[["geometry"]], predicate="within")
    return np.bincount(j["index_right"].to_numpy(), minlength=len(units))


def rings(units, inner=50.0, outer=300.0, buildings=None):
    """Open land around each unit: a band from `inner` to `outer` m outside it."""
    import geopandas as gpd
    g = units.geometry
    r = g.buffer(outer, quad_segs=4).difference(g.buffer(inner, quad_segs=4))
    return gpd.GeoDataFrame({"unit_id": units.unit_id}, geometry=r, crs=units.crs)


def name_units(units, places, max_dist=1500.0):
    """Nearest named place (Overture divisions) within max_dist m; contained places win."""
    import geopandas as gpd
    if places is None or len(places) == 0:
        return [None] * len(units), [None] * len(units)
    pl = places.to_crs(units.crs)
    label = pl["name_en"].fillna(pl["name"]) if "name_en" in pl else pl["name"]
    pl = gpd.GeoDataFrame({"label": label}, geometry=pl.geometry, crs=units.crs)
    j = gpd.sjoin_nearest(units[["unit_id", "geometry"]], pl, how="left", max_distance=max_dist, distance_col="dist")
    j = j.sort_values("dist").drop_duplicates("unit_id").set_index("unit_id").reindex(units.unit_id)
    return j["label"].tolist(), j["dist"].round(0).tolist()
