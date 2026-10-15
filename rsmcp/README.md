# rs-tools MCP server

**Ask Claude a question about a place, and it runs the remote sensing tools for you.** This is option A from the project's AI setup plan (kept in the project's research notes, not in this repo). It is a small local MCP server: one Python file (`rs_mcp_server.py`) that tells Claude Desktop which tools exist and runs them on your computer. The tools themselves are unchanged. Results land in a folder you can open in QGIS.

> "How much cropland flooded around Kano Plains, Kenya, after the late-April 2024 rains? Break it down by county."
>
> Claude calls `fetch_flood_inputs` (Sentinel-1 before and after, WorldCover cropland, permanent water, Kenyan counties), then `flooded_cropland`, then `read_output` on the map, and answers: about 183 ha of 6,992 ha cropland newly under water in the test box, 116 ha of it in Nyando…

## What Claude can call

| MCP tool | What it does | Login? |
|---|---|---|
| `list_tools`, `tool_help`, `tool_limits` | which tool fits, its full options, and the README's "untested" section so caveats get passed on | no |
| `fetch_sentinel2` | Sentinel-2 L2A for a small bbox and date range (AWS) | no |
| `fetch_flood_inputs` | Sentinel-1 before/after, cropland, permanent water, admin zones; returns the event and baseline file lists | no |
| `flooded_cropland` | **floodcrop**: hectares of cropland newly flooded, per zone | no |
| `time_profile` | **timeprofile**: cloud-masked NDVI (or any index) through time for points or fields | no |
| `drought_check` | **droughtcheck**: CHIRPS download, SPI drought maps and events | no |
| `burned_settlements` | **burncheck**: buildings + Sentinel-2 before/after, villages with new burn scars | no |
| `new_forest_loss` | **distwatch**: new OPERA DIST-ALERT loss since the last check | Earthdata |
| `check_nasa_access` | **hlsdoctor**: what's wrong with your NASA login or GDAL streaming | — |
| `run_tool` | any subcommand of any tool: campwatch, fallowcheck, qamask, nisargunw, ecogeocheck, classspectra, compositecheck, droughtcheck greenness, … | depends |
| `list_runs`, `read_output` | earlier results; CSV/JSON as text, PNG maps and charts as images Claude can see | no |

Every run gets its own folder under `~/rs-workspace/runs/`, downloads go to `~/rs-workspace/downloads/<name>/`. Downloads are refused if the box is bigger than 0.5 square degrees (about 55 × 55 km) so a vague question can't start a huge download.

## Set it up

This folder must sit next to the tool folders (`floodcrop/`, `timeprofile/`, …), as it does in `/mnt/project-files/tools/` and in the portfolio repo. Otherwise set `RS_TOOLS_DIR`.

1. **Python environment.** Conda is the easy way to get GDAL working, especially on Windows:
   ```
   conda env create -f environment.yml
   conda activate rs-tools
   ```
   (Or `pip install -r requirements.txt` in a venv where rasterio installs cleanly.)
2. **Check it works** before involving Claude. This starts the server the way Claude Desktop does and runs the demos:
   ```
   python tests/smoke_test.py            # ~1 min, demo data only
   python tests/smoke_test.py --online   # ~2 min, also downloads two small areas
   ```
3. **Find the full path of that Python**, since Claude Desktop doesn't activate conda: `python -c "import sys; print(sys.executable)"`.
4. **Tell Claude Desktop about the server.** In Claude Desktop: Settings → Developer → Edit Config, which opens `claude_desktop_config.json` (Mac: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`). Add:
   ```json
   {
     "mcpServers": {
       "rs-tools": {
         "command": "/Users/you/miniconda3/envs/rs-tools/bin/python",
         "args": ["/Users/you/RemoteSensingPortfolio/rsmcp/rs_mcp_server.py"],
         "env": { "RS_WORKSPACE": "/Users/you/rs-workspace" }
       }
     }
   }
   ```
   On Windows the paths look like `"C:\\Users\\you\\miniconda3\\envs\\rs-tools\\python.exe"` (double backslashes).
5. **Restart Claude Desktop.** The tools appear under the tools/connectors menu in the chat box. Try: *"List the remote sensing tools you have."*
6. **NASA data** (OPERA DIST/DSWx, HLS, ECOSTRESS, NISAR): make a free Earthdata account, then `python -c "import earthaccess; earthaccess.login(persist=True)"` writes `~/.netrc`. Ask Claude to run `check_nasa_access` if anything fails.

Claude Code works too: `claude mcp add rs-tools -- /path/to/python /path/to/rs_mcp_server.py`.

Optional settings (in the `env` block): `RS_MAX_AREA_DEG2` (bbox limit, default 0.5), `RS_TIMEOUT_MIN` (per run, default 30), `RS_PYTHON` (Python used for the tools), `RS_TOOLS_DIR`.

## Seeing results in QGIS

Each answer names its run folder. Drag the `.tif` and `.geojson` files into QGIS; `qamask` also writes `.qml` styles. Community "QGIS MCP" plugins exist that would let Claude load layers into a running QGIS itself; none is tested or wired in here.

## Example questions

- "Flooded cropland around Kano Plains after 1 May 2024, by county." (`fetch_flood_inputs` → `flooded_cropland`)
- "NDVI through January–March 2024 at 37.3515, -0.649 in the Mwea rice scheme, and show me the chart." (`fetch_sentinel2` → `time_profile` → `read_output`)
- "Is the area around Nakuru in drought right now, and what were the worst droughts since 1981?" (`drought_check`)
- "Did any parts of El Geneina burn between April and June 2023?" (`burned_settlements`)
- "Run the Camp Growth Watch demo data and summarize it." (`tool_help campwatch run` → `run_tool`)

## How it works

Each MCP tool builds the same command you'd type (`python -m floodcrop --source sar …`) and runs it in the tool's own folder with the tool on `PYTHONPATH`. It returns `ok`, the exact command, the printed summary, the run folder and its file list. Because it shells out, a tool crash can't take the server down, and the command in each answer can be re-run by hand. Errors Claude can fix (box too big, file not found, unknown tool) come back as readable messages so it can retry.

## Tested, and not tested

Tested here (Linux, Python 3.13), through a real MCP client over stdio, with both the `mcp` 2.2 and 1.30 libraries:
- `flooded_cropland`, `time_profile`, `run_tool` (qamask), `read_output` (CSV, GeoJSON, PNG as image), `list_runs`, `tool_help`, `tool_limits`, and the bbox guard, on the tools' demo data.
- Live downloads and analysis: `fetch_flood_inputs` + `flooded_cropland` (Kano Plains, May 2024: 183 ha of 6,992 ha cropland flooded in the test box), `fetch_sentinel2` + `time_profile` (Mwea), `drought_check` (Nakuru, CHIRPS 1981–2025), `burned_settlements` (El Geneina, April vs June 2023: 8 likely-burned, 9 possible of 285 units in a 4 × 4 km box).

**Not tested:**
- **Inside Claude Desktop itself.** The server speaks standard MCP over stdio, the same as in the tests, but the app's config, tool menu and how Claude picks tools were not tried. Claude Desktop may also time out long tool calls; a large download could hit that. If it does, use a smaller box or fewer dates.
- **Windows and macOS.** Paths and conda setup were written for both but only run on Linux.
- **NASA-login tools:** `new_forest_loss` (distwatch `--fetch`) and the online part of `check_nasa_access`, because NASA servers were blocked from the build sandbox. Same for anything via `run_tool` that needs Earthdata.
- Each tool's own untested parts still apply; `tool_limits` returns them.
