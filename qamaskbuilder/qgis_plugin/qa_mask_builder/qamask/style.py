"""QGIS .qml sidecar styles. QGIS loads <name>.qml next to <name>.tif as the layer's default style."""

import os
from xml.sax.saxutils import quoteattr

_HEAD = "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>\n<qgis version=\"3.34\" styleCategories=\"AllStyleCategories\">\n <pipe>\n"
_TAIL = " </pipe>\n</qgis>\n"


def paletted_qml(entries, band=1):
    """entries: list of (value, '#rrggbb', alpha, label)."""
    rows = "\n".join(f'    <paletteEntry value="{v}" color="{c}" alpha="{a}" label={quoteattr(lbl)}/>' for v, c, a, lbl in entries)
    return (_HEAD + f'  <rasterrenderer type="paletted" band="{band}" opacity="1" alphaBand="-1" nodataColor="">\n'
            f"   <colorPalette>\n{rows}\n   </colorPalette>\n  </rasterrenderer>\n" + _TAIL)


MASK_ENTRIES = [(0, "#d73027", 255, "masked"), (1, "#1a9850", 255, "usable"), (255, "#000000", 0, "no data")]


def write_mask_qml(tif_path):
    path = os.path.splitext(tif_path)[0] + ".qml"
    with open(path, "w") as fh:
        fh.write(paletted_qml(MASK_ENTRIES))
    return path


_PALETTE = ["#4575b4", "#d73027", "#fdae61", "#74add1", "#1a9850", "#984ea3", "#a6761d", "#e7298a",
            "#66a61e", "#7570b3", "#e6ab02", "#666666", "#1b9e77", "#d95f02", "#ffff99", "#b15928"]


def write_field_qml(tif_path, product, field, band=1):
    """A paletted style for one decoded field, labelled from flags.json."""
    vals = product.fields[field]["values"]
    entries = [(int(v), _PALETTE[i % len(_PALETTE)], 255, f"{v}: {lbl}") for i, (v, lbl) in enumerate(vals.items())]
    path = os.path.splitext(tif_path)[0] + ".qml"
    with open(path, "w") as fh:
        fh.write(paletted_qml(entries, band))
    return path
