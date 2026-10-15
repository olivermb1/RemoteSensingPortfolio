"""What earlier runs reported, so each run returns only what is new.

The state folder holds state.json (run history and the rules used) and one
<tile>.npz per MGRS tile with a uint16 grid: the run number at which each
pixel was first reported, 0 if never.
"""

import datetime as dt
import json
import os

import numpy as np

RULE_KEYS = ("level", "min_loss", "since", "min_patch_px", "forest_mask")


class State:
    def __init__(self, folder):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        self.path = os.path.join(folder, "state.json")
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.meta = json.load(f)
        else:
            self.meta = {"tool": "distwatch", "runs": []}

    @property
    def run_number(self):
        return len(self.meta["runs"]) + 1

    @property
    def last_run(self):
        return self.meta["runs"][-1] if self.meta["runs"] else None

    def rule_changes(self, rules):
        """Rules that differ from the previous run. New loss may then come from the change."""
        last = self.last_run
        if not last:
            return {}
        old = last.get("rules", {})
        return {k: (old.get(k), rules.get(k)) for k in RULE_KEYS if old.get(k) != rules.get(k)}

    def _tile_path(self, tile):
        return os.path.join(self.folder, f"{tile}.npz")

    def tile(self, tile, grid):
        p = self._tile_path(tile)
        if not os.path.exists(p):
            return np.zeros((grid.height, grid.width), "uint16")
        z = np.load(p, allow_pickle=False)
        if tuple(np.round(z["gt"], 6)) != tuple(np.round(grid.gt, 6)) or z["reported"].shape != (grid.height, grid.width):
            raise ValueError(f"Saved state for tile {tile} is on a different grid. "
                             "Use a new state folder, or delete this tile's file to start it over.")
        return z["reported"].astype("uint16")

    def set_tile(self, tile, reported, grid):
        tmp = self._tile_path(tile) + ".tmp.npz"
        np.savez_compressed(tmp, reported=reported.astype("uint16"), gt=np.array(grid.gt, "float64"))
        os.replace(tmp, self._tile_path(tile))

    def add_run(self, record):
        record = {"run": self.run_number, "time": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")} | record
        self.meta["runs"].append(record)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.meta, f, indent=1)
        os.replace(tmp, self.path)
        return record
