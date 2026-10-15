# HLS access doctor report

**8 problem(s) stop HLS access on this machine. Fix the FAIL lines first, top to bottom.**

| | Check | Found | Fix |
|---|---|---|---|
| OK | Python version | Python 3.12.3 (/usr/bin/python3.12). |  |
| info | Python packages | Found: pyproj 3.6.1, requests 2.31.0, numpy 1.26.4, GDAL Python bindings 3.8.4. Not installed: earthaccess, rasterio. earthaccess is optional for this doctor, but it is the easiest way to search and log in. |  |
| OK | GDAL for streaming | osgeo: GDAL 3.8.4. |  |
| OK | GDAL settings for streaming HLS | Cookie jar, netrc and directory-listing settings are in place. |  |
| info | Proxy and certificate settings | SSL_CERT_FILE=/root/.ccr/ca-bundle.crt; REQUESTS_CA_BUNDLE=/root/.ccr/ca-bundle.crt; CURL_CA_BUNDLE=/root/.ccr/ca-bundle.crt; GDAL_CURL_CA_BUNDLE=/root/.ccr/ca-bundle.crt; HTTPS_PROXY is set (traffic goes through a proxy). |  |
| FAIL | Earthdata login in ~/.netrc | No netrc file found (looked for /root/.netrc). | Make a free account at https://urs.earthdata.nasa.gov, then run: python -c "import earthaccess; earthaccess.login(persist=True)" or create the file yourself with the line: machine urs.earthdata.nasa.gov login YOUR_USERNAME password YOUR_PASSWORD |
| skip | EARTHDATA_USERNAME / EARTHDATA_PASSWORD | Not set (fine when ~/.netrc is set up). |  |
| skip | Earthdata token | No token given (set EARTHDATA_TOKEN or pass --token-file). Tokens are optional; a netrc login is enough. |  |
| FAIL | Reach Earthdata Login (urs.earthdata.nasa.gov) | The network's proxy refused to connect to urs.earthdata.nasa.gov (Tunnel connection failed: 403 Forbidden). | A firewall or proxy blocks NASA Earthdata here. Ask IT to allow *.earthdata.nasa.gov and *.earthdatacloud.nasa.gov, or try another network. |
| FAIL | Reach CMR search (cmr.earthdata.nasa.gov) | The network's proxy refused to connect to cmr.earthdata.nasa.gov (Tunnel connection failed: 403 Forbidden). | A firewall or proxy blocks NASA Earthdata here. Ask IT to allow *.earthdata.nasa.gov and *.earthdatacloud.nasa.gov, or try another network. |
| FAIL | Reach LP DAAC data (data.lpdaac.earthdatacloud.nasa.gov) | The network's proxy refused to connect to data.lpdaac.earthdatacloud.nasa.gov (Tunnel connection failed: 403 Forbidden). | A firewall or proxy blocks NASA Earthdata here. Ask IT to allow *.earthdata.nasa.gov and *.earthdatacloud.nasa.gov, or try another network. |
| OK | Stream with GDAL (/vsicurl/) | Read a 256x256 block in 1.2 s with your current settings (gdal). |  |
| OK | 1 file(s) with nothing to fix |  |  |
| WARN | HLS.L30.T19JHM.2024279T141847.v2.0.Fmask.tif | - southern-hemisphere CRS label: EPSG:32619 with negative northings; relabel as EPSG:32719 and add 10,000,000 m to Y | Relabel without resampling: python -m qamask fix-crs <file> --vrt (QA Mask Builder), or leave it if you only work in this one file's CRS. |
| FAIL | HLS.L30.T19JHN.2024279T141847.v2.0.B05.tif | - this is an S3 error message (AccessDenied) saved with a .tif name | AccessDenied: s3:// links only work inside AWS us-west-2; use the https:// link. Expired/RequestExpired: signed links last about an hour; fetch a fresh one. |
| WARN | HLS.L30.T19JHN.2024279T141847.v2.0.Fmask.tif | - southern-hemisphere CRS label: EPSG:32619 with negative northings; relabel as EPSG:32719 and add 10,000,000 m to Y | Relabel without resampling: python -m qamask fix-crs <file> --vrt (QA Mask Builder), or leave it if you only work in this one file's CRS. |
| WARN | HLS.S30.T10TCT.2021345T191811.v1.5.B8A.tif | - HLS version 1.5; v2.0 is the current release and older versions are retired | Search for short names HLSL30 / HLSS30 version 2.0. |
| FAIL | HLS.S30.T10TCT.2021345T191811.v2.0.B02.tif | - starts like a GeoTIFF but can't be read (/mnt/attach/project-files/tools/hlsdoctor/demo/files/HLS.S30.T10TCT.2021345T191811.v2.0.B02.tif: TIFFReadDirectory:Faile); usually a download that stopped part way | Download it again. Partial files often have the right name but a size much smaller than the others. |
| FAIL | HLS.S30.T10TCT.2021345T191811.v2.0.B03.tif | - this is a web page saved with a .tif name, almost always the Earthdata login page | Your download didn't send the Earthdata login. Fix ~/.netrc (run the full check) and download again. |
| WARN | HLS.S30.T10TCT.2021345T191811.v2.0.B04.tif | - no no-data value set; HLS fill pixels (-9999) will count as data | Set no-data to -9999 (QGIS: Layer Properties > Transparency; GDAL: gdal_edit -a_nodata -9999). |
| FAIL | HLS.S30.T10TCT.2021345T191811.v2.0.B11.tif | - the file is empty (0 bytes): the download stopped before any data came | Download it again. |
| WARN | EPSG code on the CRS | 3 file(s) (e.g. HLS.S30.T10TCT.2021345T191811.v1.5.B8A.tif) store an unnamed 'UTM zone N' CRS with no EPSG code. The CRS is right, but rasterio's crs.to_epsg() returns None and some tools report 'unknown CRS' or treat same-zone tiles as different. | rasterio: crs.to_epsg(confidence_threshold=20); GDAL: AutoIdentifyEPSG(); QGIS: set the layer CRS to EPSG:326 + the zone in the tile name (327 + zone south of the equator, after the CRS fix). |
| info | Landsat (L30) and Sentinel-2 (S30) files together | The same band number means different light in the two products: NIR: L30 B05 = S30 B8A; SWIR 1: L30 B06 = S30 B11; SWIR 2: L30 B07 = S30 B12; cirrus: L30 B09 = S30 B10. S30 B05 is red edge, not NIR. Pick bands by name, not number. |  |
| WARN | Neighbouring MGRS tiles | 1 date(s) appear on more than one tile (e.g. L30 2024279 on T19JHM, T19JHN). Tiles overlap by several kilometres, so a time series or composite over the overlap counts the same observation twice. | Keep one tile per area (most tools have a --tile option). |
| WARN | Fmask alongside the bands | 1 granule(s) have bands but no Fmask file (e.g. S30.T10TCT.2021345T191811). | Download the .Fmask.tif too; without it clouds can't be masked. |
