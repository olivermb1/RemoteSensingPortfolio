"""MCP server that lets Claude Desktop (or any MCP client) run the remote sensing tools.

Each tool in the portfolio already has a command line (`python -m floodcrop ...`). This server
wraps those commands: the typed tools below cover the common workflows, and `run_tool` reaches
every subcommand of every tool. Nothing in the tools themselves changes.

Run:  python rs_mcp_server.py            (stdio, which is what Claude Desktop uses)

Settings (environment variables, all optional):
  RS_TOOLS_DIR      folder holding the tool folders (default: the folder above this file)
  RS_WORKSPACE      where downloads and run outputs go (default: ~/rs-workspace)
  RS_PYTHON         Python used to run the tools (default: the one running this server)
  RS_MAX_AREA_DEG2  largest bbox a download may cover, in square degrees (default 0.5, ~55 x 55 km)
  RS_TIMEOUT_MIN    longest a single tool run may take, in minutes (default 30)
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:  # mcp >= 2
    from mcp.server.mcpserver import Image, MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server, Image
    from mcp.server.fastmcp.exceptions import ToolError

HERE = Path(__file__).resolve().parent
TOOLS_DIR = Path(os.environ.get("RS_TOOLS_DIR", HERE.parent)).expanduser().resolve()
WORKSPACE = Path(os.environ.get("RS_WORKSPACE", Path.home() / "rs-workspace")).expanduser().resolve()
PYTHON = os.environ.get("RS_PYTHON", sys.executable)
MAX_AREA = float(os.environ.get("RS_MAX_AREA_DEG2", "0.5"))
TIMEOUT = float(os.environ.get("RS_TIMEOUT_MIN", "30")) * 60

# name -> (folder under TOOLS_DIR, python module, one-line description)
TOOLS = {
    "floodcrop": ("floodcrop", "floodcrop", "Hectares of cropland newly under water per admin unit / FEWS NET zone (OPERA DSWx, Sentinel-1, optical)"),
    "floodcrop.fetch": ("floodcrop", "floodcrop.fetch", "Download flood inputs: Sentinel-1, OPERA DSWx, cropland, permanent water, admin zones, FEWS NET zones"),
    "timeprofile": ("timeprofile", "timeprofile", "Cloud-masked NDVI/any index through time for points or fields; also fetch-s2 / fetch-hls downloads"),
    "droughtcheck": ("droughtcheck", "droughtcheck", "SPI/SPEI drought maps and events from CHIRPS; 'drought or something else?' greenness check"),
    "droughtcheck.fetch": ("droughtcheck", "droughtcheck.fetch", "Download CHIRPS rainfall, NASA POWER temperatures, NDVI anomaly, WorldCover"),
    "distwatch": ("distwatch", "distwatch", "New vegetation loss per area since the last run, from OPERA DIST-ALERT (Earthdata login)"),
    "burncheck": ("burncheck", "burncheck", "Which villages / town blocks show new burn scars between two Sentinel-2 windows"),
    "campwatch": ("campwatch", "campwatch", "Where new shelter / camp areas appeared, when, and how big"),
    "fallowcheck": ("fallowcheck", "fallowcheck", "Normally farmed cropland left unfarmed in a season (abandoned fields)"),
    "classspectra": ("classspectra", "classspectra", "Spectral signatures per land cover class, as a check on a land cover map"),
    "compositecheck": ("compositecheck", "compositecheck", "Quality layers and report for a Landsat/Sentinel-2/HLS composite"),
    "qamask": ("qamaskbuilder", "qamask", "Build clean masks from NASA QA layers (HLS Fmask, Landsat, OPERA, ECOSTRESS); fix HLS CRS"),
    "hlsdoctor": ("hlsdoctor", "hlsdoctor", "Check NASA Earthdata login, HLS search and streaming setup; check downloaded HLS files"),
    "ecogeocheck": ("ecogeocheck", "ecogeocheck", "Find ECOSTRESS scenes that are mislocated and keep them out"),
    "nisargunw": ("nisargunw", "nisargunw", "Convert NISAR GUNW interferograms (HDF5) to GeoTIFFs with corrections applied"),
}

mcp = _Server(
    "rs-tools",
    instructions=(
        "Remote sensing tools for Africa-focused analysis with NASA and ESA data. Typical flow: download inputs "
        "for a small bbox (fetch_* tools), run an analysis tool, then read the summary with read_output. "
        "Keep areas small (towns, districts). Every tool writes into a new run folder under the workspace; "
        "tell the user the folder so they can open the GeoTIFF/GeoJSON layers in QGIS. Each tool's README lists "
        "what is untested; say so when a result depends on it. bbox is always [west, south, east, north] in degrees."
    ),
)


# ---------------------------------------------------------------- helpers

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "run"


def _new_run(tool: str, label: str = "") -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    d = WORKSPACE / "runs" / f"{stamp}_{tool.replace('.', '-')}{'_' + _slug(label) if label else ''}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(p: str) -> str:
    """Workspace-relative paths are allowed, so Claude can say 'downloads/kano/s1/...'."""
    q = Path(p).expanduser()
    return str(q if q.is_absolute() else WORKSPACE / q)


def _check_bbox(bbox: list[float]) -> None:
    if len(bbox) != 4:
        raise ToolError("bbox must be [west, south, east, north] in degrees")
    w, s, e, n = bbox
    if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
        raise ToolError(f"bbox {bbox} is not [west, south, east, north] with west<east and south<north")
    area = (e - w) * (n - s)
    if area > MAX_AREA:
        raise ToolError(f"bbox covers {area:.2f} square degrees; the limit is {MAX_AREA} (set RS_MAX_AREA_DEG2 to raise it). "
                         "Pick a smaller area, e.g. one district.")


def _files(folder: Path, limit: int = 60) -> list[str]:
    if not folder.exists():
        return []
    out = sorted(str(p.relative_to(WORKSPACE)) if p.is_relative_to(WORKSPACE) else str(p)
                 for p in folder.rglob("*") if p.is_file() and not p.name.endswith(".aux.xml"))
    return out[:limit] + ([f"... {len(out) - limit} more"] if len(out) > limit else [])


def _tail(text: str, n: int = 4000) -> str:
    return text if len(text) <= n else "...\n" + text[-n:]


def _run(tool: str, args: list[str], out: Path | None = None, timeout: float | None = None) -> dict:
    if tool not in TOOLS:
        raise ToolError(f"unknown tool {tool!r}; known: {', '.join(TOOLS)}")
    folder, module, _ = TOOLS[tool]
    cwd = TOOLS_DIR / folder
    if not cwd.is_dir():
        raise ToolError(f"tool folder {cwd} not found; set RS_TOOLS_DIR to the folder holding the tools")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(cwd), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep),
               MPLBACKEND="Agg", PYTHONUNBUFFERED="1")
    cmd = [PYTHON, "-m", module, *[str(a) for a in args]]
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout or TIMEOUT)
        code, so, se = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        so = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        code, se = -1, f"stopped after {(timeout or TIMEOUT) / 60:.0f} minutes (RS_TIMEOUT_MIN)"
    res = {"ok": code == 0, "command": " ".join(["python", "-m", module, *map(str, args)]),
           "output": _tail(so)}
    if code != 0:
        res["error"] = _tail(se, 3000) or f"exit code {code}"
    elif se.strip():
        res["warnings"] = _tail(se, 1500)
    if out is not None:
        res["folder"] = str(out)
        res["files"] = _files(out)
    return res


# ---------------------------------------------------------------- discovery

@mcp.tool()
def list_tools() -> dict:
    """List the remote sensing tools, what each does, and where its README and demo data are.
    Call this first if unsure which tool answers the user's question."""
    rows = {}
    for name, (folder, module, desc) in TOOLS.items():
        d = TOOLS_DIR / folder
        rows[name] = {"does": desc, "readme": str(d / "README.md"), "installed": d.is_dir(),
                      "demo_data": str(d / "demo" / "data") if (d / "demo" / "data").is_dir() else None}
    return {"workspace": str(WORKSPACE), "tools": rows}


@mcp.tool()
def tool_help(tool: str, subcommand: str = "") -> str:
    """Show a tool's full command-line options (its --help), e.g. tool='burncheck', subcommand='run'.
    Use before run_tool so the arguments are right."""
    r = _run(tool, ([subcommand] if subcommand else []) + ["--help"], timeout=60)
    return r.get("output") or r.get("error", "")


@mcp.tool()
def tool_limits(tool: str) -> str:
    """Return the 'untested / limits' section of a tool's README, so caveats can be passed on to the user."""
    folder = TOOLS[tool][0] if tool in TOOLS else tool
    readme = TOOLS_DIR / folder / "README.md"
    if not readme.exists():
        return "no README found"
    text = readme.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^##+ .*(untested|not tested|limits).*$", text, re.I | re.M)
    if not m:
        return "README has no limits section; first part:\n" + text[:2500]
    nxt = re.search(r"^## ", text[m.end():], re.M)
    return text[m.start(): m.end() + (nxt.start() if nxt else 4000)][:5000]


# ---------------------------------------------------------------- downloads

@mcp.tool()
def check_nasa_access(offline: bool = False) -> dict:
    """Check the NASA Earthdata login (~/.netrc or EARTHDATA_TOKEN), HLS search and GDAL streaming.
    Run this when a NASA download (HLS, OPERA DSWx/DIST, ECOSTRESS, NISAR) fails."""
    return _run("hlsdoctor", ["check", "--format", "markdown"] + (["--offline"] if offline else []), timeout=300)


@mcp.tool()
def fetch_sentinel2(bbox: list[float], start: str, end: str, name: str, max_cloud: float = 60.0) -> dict:
    """Download Sentinel-2 L2A scenes (6 bands + quality mask, 10 m) for a small area from the free AWS
    bucket, no login. Dates YYYY-MM-DD. Files go to <workspace>/downloads/<name>/s2. The folder works as
    `scenes` for time_profile. Several months of scenes for a district can take a few minutes."""
    _check_bbox(bbox)
    out = WORKSPACE / "downloads" / _slug(name) / "s2"
    out.mkdir(parents=True, exist_ok=True)
    return _run("timeprofile", ["fetch-s2", "--bbox", *bbox, "--start", start, "--end", end,
                                "--out", out, "--max-cloud", max_cloud], out)


@mcp.tool()
def fetch_flood_inputs(bbox: list[float], event_date: str, name: str, country: str = "",
                       zone_level: str = "county", cropland: str = "worldcover",
                       deafrica_region: str = "eastern") -> dict:
    """Download everything flooded_cropland needs for an area, no login: Sentinel-1 VV after the event
    and before it (dry baseline), a cropland map, permanent water (DE Africa WOfS) and admin zones
    (Overture). event_date YYYY-MM-DD. country is ISO-2 (e.g. KE); without it no zones are fetched.
    zone_level: region, county or localadmin. cropland: worldcover or deafrica (deafrica_region:
    eastern, western, northern, southern, central, sahel, south_eastern, indian_ocean).
    Files go to <workspace>/downloads/<name>/."""
    _check_bbox(bbox)
    out = WORKSPACE / "downloads" / _slug(name)
    out.mkdir(parents=True, exist_ok=True)
    steps = {
        "s1": ["s1", "--bbox", *bbox, "--event-date", event_date, "--out", out],
        "cropland": ["cropland", "--bbox", *bbox, "--source", cropland, "--region", deafrica_region, "--out", out],
        "permanent": ["permanent", "--bbox", *bbox, "--out", out],
    }
    if country:
        steps["zones"] = ["zones", "--bbox", *bbox, "--country", country.upper(), "--level", zone_level, "--out", out]
    res = {step: _run("floodcrop.fetch", a) for step, a in steps.items()}
    # split the Sentinel-1 files at the event date so flooded_cropland can be called directly
    ev = event_date.replace("-", "")
    vv = sorted(str(p) for p in (out / "s1").glob("S1_VV_*.tif"))
    return {"folder": str(out), "files": _files(out),
            "event_files": [p for p in vv if p[-12:-4] >= ev], "baseline_files": [p for p in vv if p[-12:-4] < ev],
            "steps": {k: {"ok": v["ok"], **({"error": v["error"]} if not v["ok"] else {})} for k, v in res.items()}}


# ---------------------------------------------------------------- analyses

@mcp.tool()
def flooded_cropland(event_files: list[str], cropland: str, title: str,
                     baseline_files: list[str] | None = None, zones: str = "", permanent_water: str = "",
                     source: str = "sar", crop_preset: str = "worldcover") -> dict:
    """Hectares of cropland newly flooded, overall and per zone. source: sar (Sentinel-1 VV from
    fetch_flood_inputs, files s1/S1_VV_*.tif), dswx (OPERA DSWx WTR), optical, or mask. Give the
    post-event files as event_files and pre-event ones as baseline_files. crop_preset must match the
    cropland file: worldcover (worldcover_2021_v200.tif) or deafrica (deafrica_cropmask_2019.tif).
    zones: GeoJSON of admin units. permanent_water: wofs_alltime_frequency.tif. Paths may be relative to
    the workspace. Returns totals plus summary.csv, a map PNG and GeoTIFF layers."""
    out = _new_run("floodcrop", title)
    args = ["--source", source, "--event", *map(_path, event_files)]
    if baseline_files:
        args += ["--baseline", *map(_path, baseline_files)]
    args += ["--cropland", _path(cropland), "--crop-preset", crop_preset, "--out", out, "--title", title]
    if zones:
        args += ["--zones", _path(zones)]
    if permanent_water:
        args += ["--permanent", _path(permanent_water)]
    return _run("floodcrop", args, out)


@mcp.tool()
def time_profile(scenes: str, title: str, index: str = "NDVI", features_geojson: str = "",
                 points: list[str] | None = None, start: str = "", end: str = "") -> dict:
    """Index through time (cloud-masked, smoothed) for fields or points. scenes: a folder from
    fetch_sentinel2 or HLS downloads. Give features_geojson (polygons/points with a 'name' property) or
    points as 'lon,lat,name' strings. index: NDVI, EVI, NDMI, MNDWI ... comma-separated for several.
    Returns series.csv and chart PNGs (open them with read_output)."""
    if not features_geojson and not points:
        raise ToolError("give features_geojson or points")
    out = _new_run("timeprofile", title)
    args = ["extract", "--scenes", _path(scenes), "--index", index, "--out", out, "--title", title]
    if features_geojson:
        args += ["--features", _path(features_geojson)]
    for p in points or []:
        args += ["--point", p]
    if start:
        args += ["--start", start]
    if end:
        args += ["--end", end]
    return _run("timeprofile", args, out)


@mcp.tool()
def drought_check(bbox: list[float], name: str, start: str = "1981-01", end: str = "",
                  events_since: str = "2000-01") -> dict:
    """SPI drought maps, classes and drought events for an area from CHIRPS monthly rainfall (no login).
    start/end are YYYY-MM; the SPI needs a long record, so keep start at 1981-01. end defaults to last
    month. Downloads to <workspace>/downloads/<name>/ then writes a run folder."""
    _check_bbox(bbox)
    end = end or (dt.date.today().replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
    dl = WORKSPACE / "downloads" / _slug(name)
    dl.mkdir(parents=True, exist_ok=True)
    precip = dl / "chirps_monthly.tif"
    if not precip.exists():
        f = _run("droughtcheck.fetch", ["chirps", "--bbox", *bbox, "--start", start, "--end", end, "--out", precip])
        if not f["ok"]:
            return {"step": "download CHIRPS", **f}
    out = _new_run("droughtcheck", name)
    return _run("droughtcheck", ["drought", "--precip", precip, "--events-since", events_since, "--out", out], out)


@mcp.tool()
def burned_settlements(bbox: list[float], name: str, before_start: str, before_end: str,
                       after_start: str, after_end: str) -> dict:
    """Which villages / town blocks show new burn scars between two windows (conflict observation).
    Downloads Overture buildings and place names plus Sentinel-2 for both windows (no login), then runs
    burncheck. Windows of 3-4 weeks each, dates YYYY-MM-DD. Results are indicators, not confirmed damage:
    say so to the user."""
    _check_bbox(bbox)
    dl = WORKSPACE / "downloads" / _slug(name)
    b = [str(x) for x in bbox]
    steps = [
        ["fetch-buildings", "--bbox", *b, "--out", dl / "buildings.geojson"],
        ["fetch-places", "--bbox", *b, "--out", dl / "places.geojson"],
        ["fetch-s2", "--bbox", *b, "--start", before_start, "--end", before_end, "--out", dl / "s2_before"],
        ["fetch-s2", "--bbox", *b, "--start", after_start, "--end", after_end, "--out", dl / "s2_after"],
    ]
    dl.mkdir(parents=True, exist_ok=True)
    for a in steps:
        if a[0] in ("fetch-buildings", "fetch-places") and Path(a[-1]).exists():
            continue
        r = _run("burncheck", a)
        if not r["ok"]:
            return {"step": " ".join(map(str, a[:1])), **r}
    out = _new_run("burncheck", name)
    return _run("burncheck", ["run", "--before", str(dl / "s2_before" / "*.tif"), "--after", str(dl / "s2_after" / "*.tif"),
                              "--buildings", dl / "buildings.geojson", "--places", dl / "places.geojson", "--out", out], out)


@mcp.tool()
def new_forest_loss(areas_geojson: str, watch_name: str, min_loss: int = 50) -> dict:
    """New vegetation loss per area from NASA OPERA DIST-ALERT, counting only what is new since the last
    call with the same watch_name. Needs a NASA Earthdata login (run check_nasa_access if it fails).
    areas_geojson: polygons in lon/lat (farms, concessions, districts)."""
    state = WORKSPACE / "watches" / _slug(watch_name)
    out = _new_run("distwatch", watch_name)
    return _run("distwatch", ["run", "--areas", _path(areas_geojson), "--state", state, "--out", out,
                              "--fetch", "--min-loss", min_loss], out)


@mcp.tool()
def run_tool(tool: str, args: list[str], label: str = "") -> dict:
    """Run any tool's command line directly, for anything the other tools don't cover (e.g. campwatch run,
    fallowcheck, qamask build, nisargunw convert, ecogeocheck check, classspectra, compositecheck,
    droughtcheck greenness). Check the options with tool_help first. Write '{run}' wherever the command
    needs an output folder or file; it is replaced by a fresh run folder. Relative input paths are
    relative to the tool's own folder (so its demo/data files work); use absolute paths for downloads."""
    out = _new_run(tool, label)
    filled = [a.replace("{run}", str(out)) for a in args]
    return _run(tool, filled, out)


# ---------------------------------------------------------------- results

@mcp.tool()
def list_runs(limit: int = 20) -> list[dict]:
    """List recent run folders, newest first, with their files."""
    runs = sorted((WORKSPACE / "runs").glob("*"), reverse=True)[:limit] if (WORKSPACE / "runs").exists() else []
    return [{"folder": str(r), "files": _files(r, 15)} for r in runs]


@mcp.tool()
def read_output(path: str, max_chars: int = 6000):
    """Read a result file: CSV, JSON, GeoJSON, TXT or MD as text (truncated), or a PNG/JPG chart or map as
    an image. Paths may be relative to the workspace. GeoTIFFs can't be shown here: point the user to the
    file to open in QGIS."""
    p = Path(_path(path))
    if not p.exists():
        raise ToolError(f"{p} not found")
    if p.suffix.lower() in (".png", ".jpg", ".jpeg"):
        return Image(path=str(p))
    if p.suffix.lower() in (".tif", ".tiff", ".h5", ".vrt", ".zip"):
        return f"{p} is a {p.suffix} file ({p.stat().st_size / 1e6:.1f} MB); open it in QGIS."
    text = p.read_text(encoding="utf-8", errors="replace")
    if p.suffix.lower() == ".geojson" and len(text) > max_chars:
        try:
            g = json.loads(text)
            feats = g.get("features", [])
            return json.dumps({"features": len(feats), "first_properties": [f.get("properties") for f in feats[:10]]}, indent=1)
        except ValueError:
            pass
    return text[:max_chars] + (f"\n... ({len(text) - max_chars} more characters)" if len(text) > max_chars else "")


def main() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    mcp.run()


if __name__ == "__main__":
    main()
