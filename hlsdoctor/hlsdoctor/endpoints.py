"""NASA endpoints the doctor talks to. Each can be overridden with an
environment variable, which the tests use to point at a local fake server."""

import os
from urllib.parse import urlparse

URS = os.environ.get("HLSDOCTOR_URS", "https://urs.earthdata.nasa.gov")
CMR = os.environ.get("HLSDOCTOR_CMR", "https://cmr.earthdata.nasa.gov")
DATA = os.environ.get("HLSDOCTOR_DATA", "https://data.lpdaac.earthdatacloud.nasa.gov")
S3CREDS = DATA + "/s3credentials"
PROVIDER = "LPCLOUD"
COLLECTIONS = {"L30": "HLSL30", "S30": "HLSS30"}
VERSION = "2.0"
REGION = "us-west-2"  # where LP DAAC keeps HLS on S3; s3:// links only work from here

# Nakuru, Kenya: a small area HLS covers every few days
DEFAULT_BBOX = (36.0, -0.40, 36.15, -0.25)


def host(url):
    return urlparse(url).netloc.lower()


URS_HOST = host(URS)
DATA_HOST = host(DATA)
