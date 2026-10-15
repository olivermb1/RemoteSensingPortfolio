"""Spectral indices as small formulas over common band names, plus a safe
evaluator for your own formula (e.g. "(nir - swir1) / (nir + swir1)")."""

import ast

import numpy as np

INDICES = {
    "NDVI": ("(nir - red) / (nir + red)", "greenness"),
    "EVI": ("2.5 * (nir - red) / (nir + 6 * red - 7.5 * blue + 1)", "greenness, less saturation in dense canopy"),
    "EVI2": ("2.5 * (nir - red) / (nir + 2.4 * red + 1)", "EVI without the blue band"),
    "SAVI": ("1.5 * (nir - red) / (nir + red + 0.5)", "greenness over sparse cover / bright soil"),
    "NDWI": ("(green - nir) / (green + nir)", "open water (McFeeters)"),
    "MNDWI": ("(green - swir1) / (green + swir1)", "open water, better near built-up land"),
    "NDMI": ("(nir - swir1) / (nir + swir1)", "canopy moisture"),
    "NBR": ("(nir - swir2) / (nir + swir2)", "burn severity / disturbance"),
    "NDRE": ("(nir - rededge1) / (nir + rededge1)", "chlorophyll (Sentinel-2 and HLS S30 only)"),
    "BSI": ("((swir1 + red) - (nir + blue)) / ((swir1 + red) + (nir + blue))", "bare soil"),
}

_FUNCS = {"sqrt": np.sqrt, "abs": np.abs, "log": np.log, "exp": np.exp,
          "minimum": np.minimum, "maximum": np.maximum, "where": np.where}
_OK = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Load, ast.Call,
       ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd, ast.Compare,
       ast.Gt, ast.Lt, ast.GtE, ast.LtE)


class Formula:
    """A parsed formula. .bands lists the band names it needs."""

    def __init__(self, name, expr):
        self.name, self.expr = name, expr
        tree = ast.parse(expr, mode="eval")
        for node in ast.walk(tree):
            if not isinstance(node, _OK):
                raise ValueError(f"{name}: '{type(node).__name__}' is not allowed in a formula")
            if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id in _FUNCS):
                raise ValueError(f"{name}: only {', '.join(_FUNCS)} can be called")
        self.bands = sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - set(_FUNCS))
        self._code = compile(tree, name, "eval")

    def __call__(self, bands):
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            out = eval(self._code, {"__builtins__": {}}, {**_FUNCS, **bands})  # noqa: S307 (AST checked above)
        return np.asarray(out, dtype="float64")


def resolve(spec):
    """'NDVI', a band name like 'nir', or 'NAME=formula' -> Formula."""
    spec = spec.strip()
    if "=" in spec and not spec.startswith("="):
        name, expr = spec.split("=", 1)
        return Formula(name.strip(), expr.strip())
    if spec.upper() in INDICES:
        return Formula(spec.upper(), INDICES[spec.upper()][0])
    return Formula(spec, spec)  # a single band (or an unnamed formula)
