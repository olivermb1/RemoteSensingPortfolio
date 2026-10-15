"""Download the demo scenes: Sentinel-2 L2A over part of the Mwea irrigation
scheme, Kirinyaga, Kenya (rice paddies, a village), 2023-2024, 20 m.

Source: AWS Open Data bucket sentinel-cogs (Element 84), free, no login.
Writes demo/data/s2_mwea/<scene>.tif (about 35 MB in total). Scenes with less
than 5% clear sky over the area are skipped.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
if os.path.exists("/root/.ccr/ca-bundle.crt"):  # the sandbox this was built in
    os.environ.setdefault("CURL_CA_BUNDLE", "/root/.ccr/ca-bundle.crt")
    os.environ.setdefault("SSL_CERT_FILE", "/root/.ccr/ca-bundle.crt")

from timeprofile import fetch_s2  # noqa: E402

BBOX = (37.3223, -0.675, 37.3636, -0.6352)  # W S E N

if __name__ == "__main__":
    fetch_s2.fetch(BBOX, "2023-01-01", "2024-12-31", os.path.join(HERE, "data", "s2_mwea"), res=20)
