"""Known problems getting and using NASA HLS data, in plain words.
`python -m hlsdoctor gotchas` lists them; checks point at them by id."""

GOTCHAS = {
    "netrc-missing": (
        "No Earthdata login file",
        "Downloads end in 401 errors or a saved login page; GDAL and QGIS say the file isn't a supported format.",
        "HLS lives behind NASA Earthdata Login. Programs that aren't earthaccess (GDAL, QGIS, curl, wget) find your "
        "username and password in a file called .netrc in your home folder.",
        "Create a free account at https://urs.earthdata.nasa.gov. Then run "
        "python -c \"import earthaccess; earthaccess.login(persist=True)\" which asks for the login and writes ~/.netrc, "
        "or write the one line yourself: machine urs.earthdata.nasa.gov login YOUR_USERNAME password YOUR_PASSWORD"),
    "netrc-machine": (
        "The .netrc entry has the wrong machine name or format",
        "401 errors even though the password works in a browser.",
        "The machine name must be exactly urs.earthdata.nasa.gov: not earthdata.nasa.gov, no https://, no slash. "
        "A second entry for the same machine, Windows line endings, a byte-order mark from Notepad, or a password with "
        "# or quotes can make different programs read different things.",
        "Keep one line: machine urs.earthdata.nasa.gov login YOUR_USERNAME password YOUR_PASSWORD. "
        "Use your Earthdata username, not your email address."),
    "netrc-perms": (
        ".netrc can be read by other users",
        "Usually nothing visible, but your NASA password is exposed, and Python's netrc.netrc() with no arguments refuses the file.",
        "The file holds a password in plain text.",
        "chmod 600 ~/.netrc"),
    "login": (
        "Earthdata rejects the username or password",
        "HTTP 401 from urs.earthdata.nasa.gov.",
        "Wrong username (people often put their email), wrong password, or a new account whose email isn't confirmed.",
        "Log in at https://urs.earthdata.nasa.gov in a browser to confirm, then correct ~/.netrc."),
    "eula": (
        "LP DAAC's application isn't approved for your account",
        "A login works, but downloads land on an 'authorize' or 'agree' page or return 403.",
        "Earthdata Login asks each user to approve each data centre's application once.",
        "At https://urs.earthdata.nasa.gov open Applications > Authorized Apps and approve the LP DAAC ones, or open "
        "any HLS file link in a browser once and click Authorize/Agree."),
    "html-as-tif": (
        "A .tif that is really a web page or half a file",
        "GDAL/QGIS: 'not recognized as being in a supported file format'; the file is a few kB; opening it in a text "
        "editor shows HTML.",
        "When the login isn't sent, the server answers with the login page and many download tools save it under the "
        "file name anyway. A dropped connection leaves a short, unreadable file.",
        "Fix the login (run python -m hlsdoctor check), delete the bad files (python -m hlsdoctor files <folder> lists them) "
        "and download again."),
    "token": (
        "Earthdata tokens expire",
        "Scripts that worked last month now get 401.",
        "Tokens from https://urs.earthdata.nasa.gov/users/tokens last 60 days, and each user can hold two at a time.",
        "Generate a new one and update EARTHDATA_TOKEN. Store the token alone, without the word 'Bearer'."),
    "bearer-s3": (
        "A token sent on to S3",
        "HTTP 400 with 'Only one auth mechanism allowed' after a redirect.",
        "LP DAAC redirects each download to a signed Amazon S3 address. If your program re-sends the "
        "'Authorization: Bearer' header to S3 (curl -L -H does), S3 sees two logins and refuses.",
        "Use requests (it drops the header on redirect) or earthaccess, or use ~/.netrc with cookies instead of a token."),
    "s3-region": (
        "s3:// links only work inside AWS us-west-2",
        "'Access Denied' or no response from s3://lp-prod-protected/... paths; earthaccess.open() hangs or fails when access='direct'.",
        "LP DAAC allows direct S3 reads only from Amazon's us-west-2 region, with temporary keys from "
        "https://data.lpdaac.earthdatacloud.nasa.gov/s3credentials that last one hour.",
        "On a laptop or any other cloud, use the https:// links (earthaccess: access='external'). In us-west-2, refresh "
        "the keys at least hourly."),
    "gdal-cookies": (
        "GDAL streaming without the right settings",
        "Opening a remote HLS file is very slow, fails part way, or works in Python but not in QGIS.",
        "Each piece GDAL reads is a separate request. Without a cookie jar, every one goes through the Earthdata Login "
        "redirect again; without GDAL_DISABLE_READDIR_ON_OPEN, GDAL first tries to list the folder. QGIS has its own GDAL "
        "and its own environment, so settings made in a terminal may not reach it.",
        "Set GDAL_HTTP_COOKIEFILE and GDAL_HTTP_COOKIEJAR to a file such as ~/cookies.txt, GDAL_HTTP_NETRC=YES, "
        "GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR and CPL_VSIL_CURL_ALLOWED_EXTENSIONS=TIF. In QGIS, add them under "
        "Settings > Options > System > Environment and restart QGIS."),
    "two-gdals": (
        "rasterio and the GDAL bindings are separate GDALs",
        "A setting made with gdal.SetConfigOption() seems to be ignored by rasterio, or the other way round.",
        "pip's rasterio wheels carry their own copy of GDAL. The two copies don't share settings.",
        "Set GDAL options as environment variables before Python starts, or pass them to rasterio.Env(...)."),
    "southern-epsg": (
        "Southern-hemisphere tiles are labelled with a northern UTM zone",
        "HLS (and OPERA DSWx-HLS) files south of the equator say EPSG:326xx and have negative Y; mosaics with "
        "Sentinel-2 or Digital Earth Africa data reproject or misalign; PostGIS rejects them.",
        "A known HLS v2.0 labelling issue, confirmed by LP DAAC in January 2026 with no fix date. The pixels are in the "
        "right place; only the label and false northing differ.",
        "Relabel as EPSG:327xx and add 10,000,000 m to Y, with no resampling: python -m qamask fix-crs <files> --vrt "
        "(QA Mask Builder, in this portfolio)."),
    "no-epsg": (
        "HLS files carry no EPSG code",
        "rasterio's src.crs.to_epsg() returns None; some tools say 'unknown CRS' or treat two tiles in the same zone as different.",
        "Many HLS files store an unnamed 'UTM Zone N' definition. It is correct, but nothing ties it to an EPSG code.",
        "rasterio: src.crs.to_epsg(confidence_threshold=20). GDAL: srs.AutoIdentifyEPSG(). The file's metadata also has "
        "HORIZONTAL_CS_CODE on many granules."),
    "band-numbers": (
        "Landsat and Sentinel-2 HLS use different band numbers",
        "NDVI from S30 looks wrong; an L30+S30 time series jumps between the two sensors.",
        "HLS keeps each sensor's own numbering. NIR is B05 in L30 but B8A in S30 (S30 B05 is red edge); SWIR 1 is "
        "B06 vs B11; SWIR 2 is B07 vs B12; cirrus is B09 vs B10.",
        "Map bands by name per product. In Earth Engine the band names are the same B-numbers, so the same care applies."),
    "scale": (
        "Scale factor, and no Sentinel-2 offset",
        "Reflectance in the thousands, or values 10,000 times too small after scaling twice.",
        "HLS reflectance is int16 x 10000 (scale_factor 0.0001, add_offset 0). Unlike Sentinel-2 L2A from baseline 04.00, "
        "HLS has no -1000 offset to remove. Angle and thermal bands use other scales.",
        "Multiply reflectance by 0.0001 once. Read each band's scale_factor from its metadata rather than assuming."),
    "nodata": (
        "Fill pixels counted as data",
        "Strange very low values at tile edges; averages pulled down.",
        "HLS fill is -9999 for bands and 255 for Fmask. A copy that lost its no-data setting treats them as real values.",
        "Set no-data to -9999 (bands) or 255 (Fmask)."),
    "fmask": (
        "Fmask is bit flags",
        "Masking 'value == 0' keeps almost nothing; class values look random.",
        "Each Fmask bit is one flag (cirrus, cloud, adjacent, shadow, snow, water) and bits 6-7 are aerosol level. "
        "A clear pixel with low aerosol is 64, not 0.",
        "Decode bits; QA Mask Builder in this portfolio does it in Python, QGIS and Earth Engine."),
    "tiles": (
        "Overlapping MGRS tiles count dates twice",
        "Too many observations per date near tile edges; composites weighted towards overlaps.",
        "MGRS tiles overlap by several kilometres, and a bounding-box search returns every tile that touches it.",
        "Keep one tile per area of interest."),
    "versions": (
        "Old HLS versions and providers",
        "CMR returns nothing, or old code points at v1.5 or provider LPDAAC_ECS.",
        "HLS v2.0 replaced v1.5, and the data moved to NASA's cloud under provider LPCLOUD (short names HLSL30 and HLSS30).",
        "Search short_name HLSL30 / HLSS30, version 2.0, provider LPCLOUD."),
    "bbox": (
        "Bounding box in the wrong order",
        "A search for a place returns nothing or the wrong continent.",
        "CMR and earthaccess want west, south, east, north in degrees. Other tools use lat/lon order.",
        "Write the box as (W, S, E, N), e.g. Nakuru: 36.0, -0.4, 36.15, -0.25."),
    "clock": (
        "Computer clock off",
        "S3 answers 'Request has expired' or tokens are refused right after creating them.",
        "Signed links and tokens are checked against the time.",
        "Turn on automatic time setting."),
    "tls": (
        "Company proxy breaks HTTPS",
        "CERTIFICATE_VERIFY_FAILED or 'SSL certificate problem' for every NASA address.",
        "Some company networks re-sign HTTPS with their own certificate, which Python and GDAL don't trust by default.",
        "Get your organisation's CA bundle and point SSL_CERT_FILE, REQUESTS_CA_BUNDLE and CURL_CA_BUNDLE at it. "
        "Don't turn certificate checks off."),
    "network": (
        "NASA servers unreachable",
        "Timeouts, 'could not resolve host', or a proxy refusal.",
        "A firewall, proxy or DNS filter blocks *.earthdata.nasa.gov or *.earthdatacloud.nasa.gov, or the internet is down.",
        "Try another network; ask IT to allow those domains; check https://status.earthdata.nasa.gov."),
}


def show(ids=None):
    ids = ids or list(GOTCHAS)
    out = []
    for i in ids:
        if i not in GOTCHAS:
            out.append(f"{i}: no such entry. Known: {', '.join(GOTCHAS)}")
            continue
        t, sym, cause, fix = GOTCHAS[i]
        out.append(f"{t}  [{i}]\n  You see: {sym}\n  Why: {cause}\n  Fix: {fix}\n")
    return "\n".join(out)


def to_markdown():
    rows = ["| Problem | You see | Fix |", "|---|---|---|"]
    for i, (t, sym, _, fix) in GOTCHAS.items():
        rows.append(f"| **{t}** (`{i}`) | {sym} | {fix} |")
    return "\n".join(rows)
