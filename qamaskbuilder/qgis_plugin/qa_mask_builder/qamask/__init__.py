"""QA Mask Builder: turn NASA quality bit layers into clean masks.

One flag list (flags.json) drives the Python core, the QGIS plugin and the
Earth Engine script.
"""

__version__ = "0.1.0"

from .registry import PRODUCTS, get_product, detect_product  # noqa: F401
from .core import build_mask, decode_field, flag_array, flag_stats  # noqa: F401
from .crsfix import hls_crs_fix  # noqa: F401
