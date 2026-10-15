#!/bin/sh
# Demo on real files: Landsat 8 over the Kenya Rift (Narok, 4 Nov 2024, DE Africa bucket)
# and a southern-hemisphere HLS L30 Fmask + OPERA DSWx tile (T19JHN, northern Argentina,
# 5 Oct 2024, OPERA's public validation bucket). Run from the qamaskbuilder folder.
set -e
D=demo/data
O=demo/output
mkdir -p $O
LS=$D/LC08_L2SP_169060_20241104_20241113_02_T1
python3 -m qamask build ${LS}_QA_PIXEL_crop.tif --drop clear --buffer 1 --out $O/kenya_landsat_clear_mask.tif
python3 -m qamask build ${LS}_SR_QA_AEROSOL_crop.tif --drop aerosol_high --out $O/kenya_landsat_aerosol_mask.tif
python3 -m qamask apply ${LS}_SR_B5_crop.tif --mask $O/kenya_landsat_clear_mask.tif --out $O/kenya_landsat_nir_masked.tif
python3 -m qamask stats ${LS}_QA_PIXEL_crop.tif > $O/kenya_landsat_flag_stats.txt
python3 -m qamask build $D/HLS.L30.T19JHN.2024279T141847.v2.0.Fmask.tif --out $O/hls_T19JHN_clear_mask.tif
python3 -m qamask decode $D/HLS.L30.T19JHN.2024279T141847.v2.0.Fmask.tif --out $O/hls_T19JHN_decoded.tif
python3 -m qamask fix-crs $D/HLS.L30.T19JHN.2024279T141847.v2.0.Fmask.tif --vrt --out $O/hls_T19JHN_fixcrs.vrt
python3 -m qamask build $D/OPERA_L3_DSWx-HLS_T19JHN_20241005T141847Z_L8_30_v1.0_B03_CONF.tif --out $O/dswx_T19JHN_high_conf_water.tif
python3 demo/make_figure.py $O
