"""Find and download real NISAR GUNW files over an African area, then convert them.

Run this on your own computer (NASA Earthdata is not reachable from where the
tool was built). Needs a free Earthdata login (https://urs.earthdata.nasa.gov)
in ~/.netrc or the EARTHDATA_USERNAME / EARTHDATA_PASSWORD variables, and
`pip install earthaccess`.

    python demo/fetch_real_gunw.py                       # Fentale, Ethiopia (default)
    python demo/fetch_real_gunw.py --bbox 29.1,-1.6,29.4,-1.3 --name nyiragongo
    python demo/fetch_real_gunw.py --list-only           # just show what exists

The collection short names are a best guess from the Earthdata catalogue
pages (NISAR_L2_GUNW_V1, _PROVISIONAL_V1, _BETA_V1); the script tries each.
"""
import argparse
import glob
import os
import subprocess
import sys

COLLECTIONS = ["NISAR_L2_GUNW_V1", "NISAR_L2_GUNW_PROVISIONAL_V1", "NISAR_L2_GUNW_BETA_V1"]
HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", default="39.75,8.80,40.05,9.10", help="W,S,E,N (default: Fentale, Ethiopia)")
    ap.add_argument("--start", default="2025-10-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--count", type=int, default=2, help="how many granules to download")
    ap.add_argument("--name", default="fentale")
    ap.add_argument("--dem", help="optional DEM GeoTIFF for the conversion")
    ap.add_argument("--list-only", action="store_true")
    a = ap.parse_args()
    import earthaccess

    earthaccess.login(strategy="netrc" if os.path.exists(os.path.expanduser("~/.netrc")) else "environment")
    bbox = tuple(float(v) for v in a.bbox.split(","))
    results = []
    for sn in COLLECTIONS:
        try:
            r = earthaccess.search_data(short_name=sn, bounding_box=bbox,
                                        temporal=(a.start, a.end), count=50)
        except Exception as e:  # unknown collection name, etc.
            print(f"{sn}: {e}")
            continue
        print(f"{sn}: {len(r)} granule(s)")
        results += r
        if r:
            break
    if not results:
        sys.exit("No GUNW granules found. Try a wider --bbox or earlier --start, or check the "
                 "collection names at https://search.asf.alaska.edu (dataset NISAR, product GUNW).")
    for g in results[:20]:
        print("  ", g["umm"]["GranuleUR"])
    if a.list_only:
        return
    dl = os.path.join(HERE, "real", a.name, "granules")
    os.makedirs(dl, exist_ok=True)
    files = earthaccess.download(results[: a.count], dl)
    out = os.path.join(HERE, "real", a.name, "output")
    cmd = [sys.executable, "-m", "nisargunw", "convert", *[str(f) for f in files], "-o", out,
           "--bbox", a.bbox, "--layers", "default,vertical_displacement,keep_mask"]
    if a.dem:
        cmd += ["--dem", a.dem]
    print(" ".join(cmd))
    subprocess.run([sys.executable, "-m", "nisargunw", "inspect", str(files[0])], cwd=os.path.dirname(HERE))
    subprocess.run(cmd, cwd=os.path.dirname(HERE), check=False)
    print(f"\nOutputs in {out}. Please send back the *_metadata.json files and the inspect output above.")


if __name__ == "__main__":
    main()
