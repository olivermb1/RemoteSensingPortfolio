import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)


@pytest.fixture
def fake(monkeypatch):
    from fake_earthdata import FakeEarthdata
    from hlsdoctor import endpoints as ep

    for k in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(k, "127.0.0.1,127.0.0.2,localhost")
    f = FakeEarthdata()
    saved = {k: getattr(ep, k) for k in ("URS", "CMR", "DATA", "S3CREDS", "URS_HOST", "DATA_HOST")}
    f.patch(ep)
    yield f
    for k, v in saved.items():
        setattr(ep, k, v)
    f.close()
