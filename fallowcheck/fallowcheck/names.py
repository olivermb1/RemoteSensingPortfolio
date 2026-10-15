"""Label areas with the nearest named place (copied from tools/burncheck)."""


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
