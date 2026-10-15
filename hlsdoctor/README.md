# HLS access doctor

Getting NASA's Harmonized Landsat Sentinel-2 (HLS) data takes an Earthdata login, a correctly written `~/.netrc`, the right CMR names, a redirect dance through Earthdata Login to a signed S3 link, and the right GDAL settings to stream cloud-optimised GeoTIFFs. When any piece is off, the errors say things like `not recognized as a supported file format` or `HTTP 403`, which don't point to the cause.

The doctor checks each piece in order and says in plain words what is wrong and how to fix it. It also checks HLS files you already downloaded for the problems that bite later: login pages saved as `.tif`, cut-off downloads, retired versions, the southern-hemisphere CRS label, missing EPSG codes, missing no-data, overlapping tiles, and mixed-up L30/S30 band numbers.

- **Python** command line and library (`hlsdoctor/`), **standard library only**. rasterio or GDAL is optional and adds the streaming and file checks.
- **QGIS Processing script** (`qgis/hlsdoctor_processing.py`) that runs the same checks with QGIS's own GDAL and environment, and can apply the recommended GDAL settings to the running QGIS session.
- **No Earth Engine version**, on purpose: Earth Engine hosts HLS itself (`NASA/HLS/HLSL30/v002`, `NASA/HLS/HLSS30/v002`) with no Earthdata login, so none of the access checks apply there. The data-use gotchas (band numbers, Fmask bits, scale) are in `python -m hlsdoctor gotchas`.

## Run it on your own computer

NASA Earthdata is blocked from the cloud sandbox where this was built, so the network checks have only run against a local fake (see Testing). Please run these on your machine:

```sh
cd hlsdoctor
python -m hlsdoctor check                      # everything; exit code 1 if anything FAILs
python -m hlsdoctor check --bbox 36.0 -0.4 36.15 -0.25 --days 60   # test search over your own area (W S E N)
python -m hlsdoctor check --files ~/data/hls   # also check a folder of downloads
python -m hlsdoctor files ~/data/hls           # only the file checks, no internet
python -m hlsdoctor check --offline            # only checks that need no internet
python -m hlsdoctor check --format markdown > report.md   # or --format json
python -m hlsdoctor gotchas                    # every known problem and its fix
python -m hlsdoctor gotchas southern-epsg      # one of them
```

Optional extras: `pip install rasterio earthaccess` (rasterio enables the GDAL streaming check outside QGIS; earthaccess is the easiest way to write `~/.netrc`). A token is optional: `EARTHDATA_TOKEN=... python -m hlsdoctor check` or `--token-file`.

**What to look at in your run.** These are the parts I could not check against the real servers, so a surprise in them is a bug in the doctor, not your setup:

1. *Earthdata username and password*: uses `GET /api/users/tokens` with your login. If NASA changed that endpoint you'll see `skip`, and the download check still tests the login.
2. *Download part of a real HLS file*: should show `OK`, with a path through urs.earthdata.nasa.gov and back to data.lpdaac... before it reaches an S3 address with status 206 or 200. The exact hops are listed, which helps if it fails.
3. *Stream with GDAL*: should be `OK` or `WARN` (works only with the recommended settings).
4. If you have never downloaded from LP DAAC, the application-approval detection (`eula`) works by spotting the words authorize/approve/agree on the page Earthdata Login shows; tell me what the page says if it misfires.

## In QGIS

Processing Toolbox > Scripts > Add Script to Toolbox... and pick `qgis/hlsdoctor_processing.py` (keep it inside this folder, or set `HLSDOCTOR_PATH` to this folder). Then run **NASA HLS > HLS access doctor**. Options: an area for the test search, a folder of downloads to check, a URL to test streaming on, a Markdown report file, and **Apply recommended GDAL settings for this QGIS session**, which sets the cookie jar and related options so `/vsicurl/` HLS layers load until you restart QGIS. To keep them, add the same names under Settings > Options > System > Environment.

QGIS often has a different GDAL and a different environment from your terminal, so "works in Python, fails in QGIS" shows up here as a difference between the two runs.

## What it checks

| Group | Check | Needs |
|---|---|---|
| Software | Python version; earthaccess, rasterio, pyproj, requests; GDAL version; **two GDALs** (rasterio's own vs the osgeo bindings, whose settings don't reach each other) | - |
| Software | GDAL settings for streaming: cookie jar, `GDAL_HTTP_NETRC`, `GDAL_DISABLE_READDIR_ON_OPEN`, and harmful ones (`GDAL_HTTP_UNSAFESSL`, `AWS_NO_SIGN_REQUEST`) | - |
| Software | Proxy and CA bundle variables: files that don't exist, `GDAL_CURL_CA_BUNDLE` and `CURL_CA_BUNDLE` pointing at different bundles | - |
| Login | `~/.netrc` (and `$NETRC`, and `_netrc` on Windows): missing file, wrong machine name (`earthdata.nasa.gov`, `https://...`), missing or placeholder login/password, duplicate entries (curl uses the first, Python the last), Windows line endings, Notepad byte-order mark, `#` or quotes in the password, permissions, and whether Python's own netrc reader can parse it | - |
| Login | `EARTHDATA_USERNAME`/`PASSWORD`; `EARTHDATA_TOKEN` decoded locally: expired, expiring within 7 days, pasted with `Bearer ` in front, or not a token | - |
| Network | Reach Earthdata Login, CMR and LP DAAC, telling apart DNS failure, proxy refusal, certificate failure, timeout and refusal; **computer clock** against NASA's servers (signed links fail when it's off) | internet |
| Network | Username and password accepted; HLSL30 and HLSS30 v2.0 found in CMR under LPCLOUD; granules over your area | internet |
| Network | Download the first 16 kB of a real Fmask file through the full redirect dance, and explain the outcome: wrong password, no login sent, LP DAAC app not approved, login page instead of the file, token passed on to S3, expired signed link, 404 | internet |
| Network | Stream one block with GDAL `/vsicurl/`, first with your settings and then with the recommended ones, so it can say which setting makes the difference | internet + GDAL |
| Network | Direct S3: outside AWS us-west-2 it says to use https links; inside, it fetches temporary S3 keys and reads over `/vsis3/` | internet |
| Files | Empty, HTML, S3-error or cut-off `.tif`; HLS version; southern-hemisphere CRS label (using QA Mask Builder's fix); no EPSG code on the CRS; scale and no-data; not cloud-optimised | - |
| Folder | L30 and S30 mixed (band-number table); the same date on neighbouring MGRS tiles; bands without Fmask | - |

Passwords are never printed. Your username and password go only to `urs.earthdata.nasa.gov`, and a token only to `data.lpdaac.earthdatacloud.nasa.gov`, never on to the signed S3 address.

## Known gotchas

Built in as `python -m hlsdoctor gotchas`:

| Problem | You see | Fix |
|---|---|---|
| **No Earthdata login file** (`netrc-missing`) | Downloads end in 401 errors or a saved login page; GDAL and QGIS say the file isn't a supported format. | Create a free account at https://urs.earthdata.nasa.gov. Then run python -c "import earthaccess; earthaccess.login(persist=True)" which asks for the login and writes ~/.netrc, or write the one line yourself: machine urs.earthdata.nasa.gov login YOUR_USERNAME password YOUR_PASSWORD |
| **The .netrc entry has the wrong machine name or format** (`netrc-machine`) | 401 errors even though the password works in a browser. | Keep one line: machine urs.earthdata.nasa.gov login YOUR_USERNAME password YOUR_PASSWORD. Use your Earthdata username, not your email address. |
| **.netrc can be read by other users** (`netrc-perms`) | Usually nothing visible, but your NASA password is exposed, and Python's netrc.netrc() with no arguments refuses the file. | chmod 600 ~/.netrc |
| **Earthdata rejects the username or password** (`login`) | HTTP 401 from urs.earthdata.nasa.gov. | Log in at https://urs.earthdata.nasa.gov in a browser to confirm, then correct ~/.netrc. |
| **LP DAAC's application isn't approved for your account** (`eula`) | A login works, but downloads land on an 'authorize' or 'agree' page or return 403. | At https://urs.earthdata.nasa.gov open Applications > Authorized Apps and approve the LP DAAC ones, or open any HLS file link in a browser once and click Authorize/Agree. |
| **A .tif that is really a web page or half a file** (`html-as-tif`) | GDAL/QGIS: 'not recognized as being in a supported file format'; the file is a few kB; opening it in a text editor shows HTML. | Fix the login (run python -m hlsdoctor check), delete the bad files (python -m hlsdoctor files <folder> lists them) and download again. |
| **Earthdata tokens expire** (`token`) | Scripts that worked last month now get 401. | Generate a new one and update EARTHDATA_TOKEN. Store the token alone, without the word 'Bearer'. |
| **A token sent on to S3** (`bearer-s3`) | HTTP 400 with 'Only one auth mechanism allowed' after a redirect. | Use requests (it drops the header on redirect) or earthaccess, or use ~/.netrc with cookies instead of a token. |
| **s3:// links only work inside AWS us-west-2** (`s3-region`) | 'Access Denied' or no response from s3://lp-prod-protected/... paths; earthaccess.open() hangs or fails when access='direct'. | On a laptop or any other cloud, use the https:// links (earthaccess: access='external'). In us-west-2, refresh the keys at least hourly. |
| **GDAL streaming without the right settings** (`gdal-cookies`) | Opening a remote HLS file is very slow, fails part way, or works in Python but not in QGIS. | Set GDAL_HTTP_COOKIEFILE and GDAL_HTTP_COOKIEJAR to a file such as ~/cookies.txt, GDAL_HTTP_NETRC=YES, GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR and CPL_VSIL_CURL_ALLOWED_EXTENSIONS=TIF. In QGIS, add them under Settings > Options > System > Environment and restart QGIS. |
| **rasterio and the GDAL bindings are separate GDALs** (`two-gdals`) | A setting made with gdal.SetConfigOption() seems to be ignored by rasterio, or the other way round. | Set GDAL options as environment variables before Python starts, or pass them to rasterio.Env(...). |
| **Southern-hemisphere tiles are labelled with a northern UTM zone** (`southern-epsg`) | HLS (and OPERA DSWx-HLS) files south of the equator say EPSG:326xx and have negative Y; mosaics with Sentinel-2 or Digital Earth Africa data reproject or misalign; PostGIS rejects them. | Relabel as EPSG:327xx and add 10,000,000 m to Y, with no resampling: python -m qamask fix-crs <files> --vrt (QA Mask Builder, in this portfolio). |
| **HLS files carry no EPSG code** (`no-epsg`) | rasterio's src.crs.to_epsg() returns None; some tools say 'unknown CRS' or treat two tiles in the same zone as different. | rasterio: src.crs.to_epsg(confidence_threshold=20). GDAL: srs.AutoIdentifyEPSG(). The file's metadata also has HORIZONTAL_CS_CODE on many granules. |
| **Landsat and Sentinel-2 HLS use different band numbers** (`band-numbers`) | NDVI from S30 looks wrong; an L30+S30 time series jumps between the two sensors. | Map bands by name per product. In Earth Engine the band names are the same B-numbers, so the same care applies. |
| **Scale factor, and no Sentinel-2 offset** (`scale`) | Reflectance in the thousands, or values 10,000 times too small after scaling twice. | Multiply reflectance by 0.0001 once. Read each band's scale_factor from its metadata rather than assuming. |
| **Fill pixels counted as data** (`nodata`) | Strange very low values at tile edges; averages pulled down. | Set no-data to -9999 (bands) or 255 (Fmask). |
| **Fmask is bit flags** (`fmask`) | Masking 'value == 0' keeps almost nothing; class values look random. | Decode bits; QA Mask Builder in this portfolio does it in Python, QGIS and Earth Engine. |
| **Overlapping MGRS tiles count dates twice** (`tiles`) | Too many observations per date near tile edges; composites weighted towards overlaps. | Keep one tile per area of interest. |
| **Old HLS versions and providers** (`versions`) | CMR returns nothing, or old code points at v1.5 or provider LPDAAC_ECS. | Search short_name HLSL30 / HLSS30, version 2.0, provider LPCLOUD. |
| **Bounding box in the wrong order** (`bbox`) | A search for a place returns nothing or the wrong continent. | Write the box as (W, S, E, N), e.g. Nakuru: 36.0, -0.4, 36.15, -0.25. |
| **Computer clock off** (`clock`) | S3 answers 'Request has expired' or tokens are refused right after creating them. | Turn on automatic time setting. |
| **Company proxy breaks HTTPS** (`tls`) | CERTIFICATE_VERIFY_FAILED or 'SSL certificate problem' for every NASA address. | Get your organisation's CA bundle and point SSL_CERT_FILE, REQUESTS_CA_BUNDLE and CURL_CA_BUNDLE at it. Don't turn certificate checks off. |
| **NASA servers unreachable** (`network`) | Timeouts, 'could not resolve host', or a proxy refusal. | Try another network; ask IT to allow those domains; check https://status.earthdata.nasa.gov. |

Two of these I found while building rather than from documentation: many HLS S30 files store an unnamed "UTM Zone 10, Northern Hemisphere" CRS with no EPSG authority, so rasterio's `crs.to_epsg()` returns `None` (it matches at `confidence_threshold=20`); and a netrc saved by Notepad with a byte-order mark makes Python's netrc reader fail outright (`bad toplevel token '﻿machine'`).

## Demo

`demo/files/` holds small cut-outs of real HLS files plus the kinds of broken files failed downloads leave behind. `demo/make_demo_files.py` rebuilds it from two public sources that need no login (an S30 band from NASA OPERA's public input bucket, and the southern-hemisphere L30 Fmask in `../qamaskbuilder/demo/data`). `demo/output/` has the reports:

- `files_report.txt`: `python -m hlsdoctor files demo/files`. It finds the login page saved as `.tif`, the S3 "AccessDenied" saved as `.tif`, the cut-off and the empty download, the v1.5 name, the missing no-data value, the southern CRS label, the missing EPSG codes, the same date on two tiles (T19JHM is a renamed copy, to show the check), and the missing Fmask.
- `check_report.txt`: the full check in the cloud sandbox, where a proxy blocks NASA. It reports "the network's proxy refused to connect to urs.earthdata.nasa.gov", which is the right diagnosis there.
- `qgis_report.md`: the same from the QGIS script, with the files folder and a public HLS file to stream.

`demo/run_demo.sh` rebuilds all of it and runs the tests.

## Testing

What was run, in the cloud sandbox:

- **35 pytest tests** (`python -m pytest tests`). Network checks run against `tests/fake_earthdata.py`, four local servers that mimic Earthdata Login, CMR, LP DAAC and S3, including the 302 to Earthdata Login, the 401 challenge, the code-for-cookie redirect and the 307 to a signed S3 link. Covered: good login, wrong password, unconfirmed account, LP DAAC app not approved, no login, expired signed link, bad token, a token reaching only the data host, a token wrongly passed to S3, temporary S3 keys in us-west-2, clock 60 minutes off, unreachable servers, missing collections and empty searches. Plus 14 netrc and token cases, GDAL error wording, the file checks on the demo folder, and the CLI.
- **Real GDAL through the login redirect**: one test has GDAL 3.12 (inside rasterio) open a file from the fake LP DAAC with the recommended settings and a netrc file. It follows the redirects, logs in from netrc, keeps the cookie, reads a block from the fake S3, and reports `auth` when the password is wrong.
- **Real network**: a real public HLS S30 file streamed over `/vsicurl/`, and the real proxy block on NASA's hosts diagnosed correctly.
- **QGIS 3.34** headless (`python3.12 tests/qgis_smoke.py`): the Processing script loads, runs every check with QGIS's GDAL 3.8, applies the GDAL settings, and writes the Markdown report.

**Not tested:** the real Earthdata Login, CMR and LP DAAC servers (blocked here; see "Run it on your own computer"); the bearer token sent through GDAL (`GDAL_HTTP_HEADERS`); direct S3 access from inside us-west-2; Windows (the `_netrc` advice comes from curl's documented behaviour); macOS; QGIS 4.

## Related tools in this portfolio

- **QA Mask Builder** (`../qamaskbuilder`): `python -m qamask fix-crs` fixes the southern-hemisphere label this doctor finds; the doctor imports its check and falls back to `hlsdoctor/_crsfix_copy.py` when the folder isn't next to it.
- **Composite Check** and **Time Profile** download HLS with the same GDAL settings this doctor recommends; if their downloads fail, run the doctor.
