"""Copy the timeprofile package into the plugin folder and zip it for QGIS 'Install from ZIP'."""

import os
import shutil
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.join(HERE, "time_profile")
CORE = os.path.join(HERE, "..", "timeprofile")

dst = os.path.join(PLUGIN, "timeprofile")
shutil.rmtree(dst, ignore_errors=True)
shutil.copytree(CORE, dst, ignore=shutil.ignore_patterns("__pycache__", "cli.py", "__main__.py", "fetch_*.py",
                                                         "rio_io.py"))
out = os.path.join(HERE, "time_profile.zip")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for root, dirs, files in os.walk(PLUGIN):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            p = os.path.join(root, f)
            z.write(p, os.path.relpath(p, HERE))
print(out)
