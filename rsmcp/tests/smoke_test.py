"""Start the server the way Claude Desktop does (stdio) and call it on the tools' demo data.

    python tests/smoke_test.py            # offline, uses demo data only (~1 minute)
    python tests/smoke_test.py --online   # also downloads a small area (~3 minutes)

Works with mcp 1.x and 2.x. Outputs go to a temporary workspace that is printed at the end.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).resolve().parents[1] / "rs_mcp_server.py"
TOOLS = Path(os.environ.get("RS_TOOLS_DIR", SERVER.parents[1]))
ONLINE = "--online" in sys.argv


def text(res):
    return " ".join(getattr(c, "text", f"<{c.type}>") for c in res.content)


async def main():
    ws = tempfile.mkdtemp(prefix="rs-smoke-")
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)],
                                   env=dict(os.environ, RS_WORKSPACE=ws))
    failures = []

    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            async def call(name, args, expect_error=False):
                res = await s.call_tool(name, args)
                is_err = getattr(res, "is_error", None)
                if is_err is None:  # mcp 1.x
                    is_err = res.isError
                ok = bool(is_err) == expect_error
                print(("PASS " if ok else "FAIL ") + name, text(res)[:160].replace("\n", " "))
                if not ok:
                    failures.append(name)
                return res

            names = [t.name for t in (await s.list_tools()).tools]
            print("tools:", ", ".join(names))
            await call("list_tools", {})
            await call("tool_help", {"tool": "floodcrop"})
            await call("tool_limits", {"tool": "floodcrop"})
            await call("fetch_sentinel2", {"bbox": [30, 0, 32, 2], "start": "2024-01-01", "end": "2024-01-10",
                                           "name": "too-big"}, expect_error=True)

            d = TOOLS / "floodcrop" / "demo" / "data"
            res = await call("flooded_cropland", {
                "event_files": [str(d / "s1" / "S1_VV_20240506.tif")],
                "baseline_files": [str(d / "s1" / "S1_VV_20240224.tif"), str(d / "s1" / "S1_VV_20240307.tif")],
                "cropland": str(d / "deafrica_cropmask_2019.tif"), "crop_preset": "deafrica",
                "zones": str(d / "zones_subcounties.geojson"), "permanent_water": str(d / "wofs_alltime_frequency.tif"),
                "title": "Kano Plains smoke test"})
            folder = json.loads(text(res)).get("folder", "")
            await call("read_output", {"path": folder + "/summary.csv"})
            await call("read_output", {"path": folder + "/map.png"})

            scenes = TOOLS / "timeprofile" / "demo" / "data" / "s2_mwea"
            if scenes.is_dir():
                await call("time_profile", {"scenes": str(scenes), "title": "Mwea smoke test",
                                            "features_geojson": str(TOOLS / "timeprofile" / "demo" / "mwea_features.geojson")})
            await call("run_tool", {"tool": "qamask", "label": "hls mask", "args": [
                "build", "demo/data/HLS.L30.T19JHN.2024279T141847.v2.0.Fmask.tif", "--out", "{run}/mask.tif"]})
            await call("check_nasa_access", {"offline": True})

            if ONLINE:
                res = await call("fetch_flood_inputs", {"bbox": [34.85, -0.30, 35.05, -0.12], "event_date": "2024-05-01",
                                                        "name": "kano-small", "country": "KE"})
                j = json.loads(text(res))
                await call("flooded_cropland", {"event_files": j["event_files"], "baseline_files": j["baseline_files"],
                                                "cropland": "downloads/kano-small/worldcover_2021_v200.tif",
                                                "zones": "downloads/kano-small/zones_KE_county.geojson",
                                                "permanent_water": "downloads/kano-small/wofs_alltime_frequency.tif",
                                                "title": "Kano small, fetched"})
                await call("fetch_sentinel2", {"bbox": [37.33, -0.66, 37.36, -0.63], "start": "2024-01-01",
                                               "end": "2024-02-15", "name": "mwea-small"})
                await call("time_profile", {"scenes": "downloads/mwea-small/s2", "points": ["37.3515,-0.649,paddy"],
                                            "title": "Mwea point"})
            await call("list_runs", {})

    print(f"\nworkspace: {ws}")
    print("all passed" if not failures else f"{len(failures)} failed: {', '.join(failures)}")
    sys.exit(1 if failures else 0)


asyncio.run(main())
