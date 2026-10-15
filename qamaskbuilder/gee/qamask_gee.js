// QA Mask Builder for Google Earth Engine.
// Generated from qamask/flags.json by `python -m qamask.gee_build`; edit
// gee/template.js and the JSON, not qamask_gee.js.
//
// Paste the whole file into the Code Editor, or save it as a script and
//   var QAMask = require('users/<you>/<repo>:qamask_gee');
//
//   QAMask.products()                          // list product keys
//   QAMask.flags('hls_fmask')                  // flags and presets for one product
//   QAMask.mask(img, 'hls_fmask')              // band 'qa_mask': 1 usable, 0 masked; fill is masked out
//   QAMask.apply(img, 'hls_fmask', {drop: ['clear', 'water'], buffer: 2})
//   QAMask.decode(img, 'landsat_c2_qa_pixel')  // one band per QA field
//
// options: {drop: [flags or presets], keep: [flags], band: 'Fmask', buffer: pixels}
// The HLS southern-hemisphere CRS fix is not needed here: Earth Engine reads
// the pixels' true location when it ingests HLS.

var PRODUCTS = {"hls_fmask":{"title":"HLS v2.0 Fmask (HLSL30 and HLSS30)","layer":"Fmask","dtype":"uint8","fill":[255],"fields":[{"name":"cirrus","bits":[0,1]},{"name":"cloud","bits":[1,1]},{"name":"adjacent","bits":[2,1]},{"name":"shadow","bits":[3,1]},{"name":"snow","bits":[4,1]},{"name":"water","bits":[5,1]},{"name":"aerosol","bits":[6,2]}],"flags":[{"name":"cirrus","field":"cirrus","in":[1]},{"name":"cloud","field":"cloud","in":[1]},{"name":"adjacent","field":"adjacent","in":[1]},{"name":"shadow","field":"shadow","in":[1]},{"name":"snow","field":"snow","in":[1]},{"name":"water","field":"water","in":[1]},{"name":"aerosol_high","field":"aerosol","in":[3]},{"name":"aerosol_moderate","field":"aerosol","in":[2]},{"name":"aerosol_climatology","field":"aerosol","in":[0]}],"presets":{"clear":["cloud","adjacent","shadow","snow","aerosol_high"],"clear_land":["cloud","adjacent","shadow","snow","aerosol_high","water"],"strict":["cloud","adjacent","shadow","snow","aerosol_high","aerosol_moderate"],"cloud_only":["cloud","shadow"]},"default_preset":"clear","gee":{"collections":["NASA/HLS/HLSL30/v002","NASA/HLS/HLSS30/v002"],"band":"Fmask"}},"landsat_c2_qa_pixel":{"title":"Landsat 8/9 Collection 2 QA_PIXEL (Level 1 and Level 2)","layer":"QA_PIXEL","dtype":"uint16","fill":[1],"fill_rule":{"field":"fill","in":[1]},"fields":[{"name":"fill","bits":[0,1]},{"name":"dilated_cloud","bits":[1,1]},{"name":"cirrus","bits":[2,1]},{"name":"cloud","bits":[3,1]},{"name":"shadow","bits":[4,1]},{"name":"snow","bits":[5,1]},{"name":"clear","bits":[6,1]},{"name":"water","bits":[7,1]},{"name":"cloud_conf","bits":[8,2]},{"name":"shadow_conf","bits":[10,2]},{"name":"snow_conf","bits":[12,2]},{"name":"cirrus_conf","bits":[14,2]}],"flags":[{"name":"dilated_cloud","field":"dilated_cloud","in":[1]},{"name":"cirrus","field":"cirrus","in":[1]},{"name":"cloud","field":"cloud","in":[1]},{"name":"shadow","field":"shadow","in":[1]},{"name":"snow","field":"snow","in":[1]},{"name":"water","field":"water","in":[1]},{"name":"not_clear","field":"clear","in":[0]},{"name":"cloud_conf_medium","field":"cloud_conf","in":[2]},{"name":"cloud_conf_high","field":"cloud_conf","in":[3]},{"name":"shadow_conf_high","field":"shadow_conf","in":[3]},{"name":"cirrus_conf_high","field":"cirrus_conf","in":[3]},{"name":"snow_conf_high","field":"snow_conf","in":[3]}],"presets":{"clear":["dilated_cloud","cirrus","cloud","shadow","snow"],"clear_land":["dilated_cloud","cirrus","cloud","shadow","snow","water"],"strict":["dilated_cloud","cirrus","cloud","shadow","snow","cloud_conf_medium","cloud_conf_high"],"cloud_only":["cloud","shadow"]},"default_preset":"clear","gee":{"collections":["LANDSAT/LC08/C02/T1_L2","LANDSAT/LC09/C02/T1_L2","LANDSAT/LE07/C02/T1_L2","LANDSAT/LT05/C02/T1_L2"],"band":"QA_PIXEL"}},"landsat_c2_sr_qa_aerosol":{"title":"Landsat 8/9 Collection 2 SR_QA_AEROSOL","layer":"SR_QA_AEROSOL","dtype":"uint8","fill":[1],"fill_rule":{"field":"fill","in":[1]},"fields":[{"name":"fill","bits":[0,1]},{"name":"valid_retrieval","bits":[1,1]},{"name":"water","bits":[2,1]},{"name":"interpolated","bits":[5,1]},{"name":"aerosol","bits":[6,2]}],"flags":[{"name":"aerosol_high","field":"aerosol","in":[3]},{"name":"aerosol_medium","field":"aerosol","in":[2]},{"name":"no_retrieval","field":"valid_retrieval","in":[0]},{"name":"interpolated","field":"interpolated","in":[1]},{"name":"water","field":"water","in":[1]}],"presets":{"clear":["aerosol_high"],"strict":["aerosol_high","aerosol_medium"]},"default_preset":"clear","gee":{"collections":["LANDSAT/LC08/C02/T1_L2","LANDSAT/LC09/C02/T1_L2"],"band":"SR_QA_AEROSOL"}},"modis_mod09_state_1km":{"title":"MODIS MOD09GA / MYD09GA state_1km (Collection 6.1)","layer":"state_1km","dtype":"uint16","fill":[],"fields":[{"name":"cloud_state","bits":[0,2]},{"name":"shadow","bits":[2,1]},{"name":"land_water","bits":[3,3]},{"name":"aerosol","bits":[6,2]},{"name":"cirrus","bits":[8,2]},{"name":"internal_cloud","bits":[10,1]},{"name":"internal_fire","bits":[11,1]},{"name":"mod35_snow","bits":[12,1]},{"name":"adjacent","bits":[13,1]},{"name":"salt_pan","bits":[14,1]},{"name":"internal_snow","bits":[15,1]}],"flags":[{"name":"cloudy","field":"cloud_state","in":[1]},{"name":"mixed","field":"cloud_state","in":[2]},{"name":"shadow","field":"shadow","in":[1]},{"name":"not_land","field":"land_water","in":[0,2,3,4,5,6,7]},{"name":"aerosol_high","field":"aerosol","in":[3]},{"name":"cirrus_average","field":"cirrus","in":[2]},{"name":"cirrus_high","field":"cirrus","in":[3]},{"name":"internal_cloud","field":"internal_cloud","in":[1]},{"name":"fire","field":"internal_fire","in":[1]},{"name":"snow","field":"mod35_snow","in":[1]},{"name":"internal_snow","field":"internal_snow","in":[1]},{"name":"adjacent","field":"adjacent","in":[1]},{"name":"salt_pan","field":"salt_pan","in":[1]}],"presets":{"clear":["cloudy","mixed","shadow","cirrus_high","internal_cloud","snow","adjacent","aerosol_high"],"clear_land":["cloudy","mixed","shadow","cirrus_high","internal_cloud","snow","adjacent","aerosol_high","not_land"],"cloud_only":["cloudy","mixed","shadow"]},"default_preset":"clear","gee":{"collections":["MODIS/061/MOD09GA","MODIS/061/MYD09GA"],"band":"state_1km"}},"modis_mod13_detailed_qa":{"title":"MODIS MOD13Q1 / MOD13A1 / MYD13 vegetation index DetailedQA (Collection 6.1)","layer":"DetailedQA","dtype":"uint16","fill":[65535],"fields":[{"name":"vi_quality","bits":[0,2]},{"name":"usefulness","bits":[2,4]},{"name":"aerosol","bits":[6,2]},{"name":"adjacent_cloud","bits":[8,1]},{"name":"brdf_corrected","bits":[9,1]},{"name":"mixed_clouds","bits":[10,1]},{"name":"land_water","bits":[11,3]},{"name":"snow_ice","bits":[14,1]},{"name":"shadow","bits":[15,1]}],"flags":[{"name":"check_other_qa","field":"vi_quality","in":[1]},{"name":"probably_cloudy","field":"vi_quality","in":[2]},{"name":"not_produced","field":"vi_quality","in":[3]},{"name":"low_usefulness","field":"usefulness","in":[12,13,14,15]},{"name":"aerosol_high","field":"aerosol","in":[3]},{"name":"adjacent_cloud","field":"adjacent_cloud","in":[1]},{"name":"mixed_clouds","field":"mixed_clouds","in":[1]},{"name":"not_land","field":"land_water","in":[0,2,3,4,5,6,7]},{"name":"snow","field":"snow_ice","in":[1]},{"name":"shadow","field":"shadow","in":[1]}],"presets":{"clear":["probably_cloudy","not_produced","low_usefulness","aerosol_high","adjacent_cloud","mixed_clouds","snow","shadow"],"good_only":["check_other_qa","probably_cloudy","not_produced"],"clear_land":["probably_cloudy","not_produced","low_usefulness","aerosol_high","adjacent_cloud","mixed_clouds","snow","shadow","not_land"]},"default_preset":"clear","gee":{"collections":["MODIS/061/MOD13Q1","MODIS/061/MOD13A1","MODIS/061/MYD13Q1"],"band":"DetailedQA"}},"modis_mod13_summary_qa":{"title":"MODIS MOD13 vegetation index SummaryQA (pixel reliability)","layer":"SummaryQA","dtype":"int16","fill":[-1],"fields":[{"name":"reliability","bits":[0,2]}],"flags":[{"name":"marginal","field":"reliability","in":[1]},{"name":"snow","field":"reliability","in":[2]},{"name":"cloudy","field":"reliability","in":[3]}],"presets":{"good_only":["marginal","snow","cloudy"],"clear":["snow","cloudy"]},"default_preset":"good_only","gee":{"collections":["MODIS/061/MOD13Q1","MODIS/061/MOD13A1"],"band":"SummaryQA"}},"modis_mod11_qc":{"title":"MODIS MOD11A1 / MOD11A2 land surface temperature QC_Day or QC_Night (Collection 6.1)","layer":"QC_Day","dtype":"uint8","fill":[],"fields":[{"name":"mandatory","bits":[0,2]},{"name":"data_quality","bits":[2,2]},{"name":"emis_error","bits":[4,2]},{"name":"lst_error","bits":[6,2]}],"flags":[{"name":"other_quality","field":"mandatory","in":[1]},{"name":"not_produced_cloud","field":"mandatory","in":[2]},{"name":"not_produced_other","field":"mandatory","in":[3]},{"name":"lst_error_gt2k","field":"lst_error","in":[2,3]},{"name":"lst_error_gt1k","field":"lst_error","in":[1,2,3]},{"name":"emis_error_gt002","field":"emis_error","in":[2,3]}],"presets":{"good_only":["other_quality","not_produced_cloud","not_produced_other"],"error_2k":["not_produced_cloud","not_produced_other","lst_error_gt2k"]},"default_preset":"error_2k","gee":{"collections":["MODIS/061/MOD11A1","MODIS/061/MYD11A1","MODIS/061/MOD11A2"],"band":"QC_Day"}},"ecostress_lste_qc":{"title":"ECOSTRESS L2 LSTE QC (ECO2LSTE / ECO_L2T_LSTE, collection 2)","layer":"QC","dtype":"uint16","fill":[],"fields":[{"name":"mandatory","bits":[0,2]},{"name":"data_quality","bits":[2,2]},{"name":"cloud_ocean","bits":[4,2]},{"name":"iterations","bits":[6,2]},{"name":"opacity","bits":[8,2]},{"name":"mmd","bits":[10,2]},{"name":"emis_accuracy","bits":[12,2]},{"name":"lst_accuracy","bits":[14,2]}],"flags":[{"name":"nominal","field":"mandatory","in":[1]},{"name":"cloud","field":"mandatory","in":[2]},{"name":"not_produced","field":"mandatory","in":[3]},{"name":"bad_l1b","field":"data_quality","in":[1,3]},{"name":"high_opacity","field":"opacity","in":[0]},{"name":"lst_poor","field":"lst_accuracy","in":[0]},{"name":"lst_marginal","field":"lst_accuracy","in":[1]},{"name":"emis_poor","field":"emis_accuracy","in":[0]}],"presets":{"clear":["cloud","not_produced","bad_l1b"],"accurate":["cloud","not_produced","bad_l1b","lst_poor"],"strict":["cloud","not_produced","bad_l1b","lst_poor","lst_marginal","high_opacity"]},"default_preset":"accurate","gee":{"collections":[],"band":"QC"}},"ecostress_cloud":{"title":"ECOSTRESS cloud mask (ECO_L2T_LSTE 'cloud' layer or ECO2CLD v002 Cloud_final)","layer":"cloud","dtype":"uint8","fill":[255],"fields":[{"name":"cloud","bits":[0,8]}],"flags":[{"name":"cloud","field":"cloud","in":[1]}],"presets":{"clear":["cloud"]},"default_preset":"clear","gee":{"collections":[],"band":"cloud"}},"opera_dswx_hls_wtr":{"title":"OPERA DSWx-HLS v1 WTR (B01) or BWTR (B02) water classes","layer":"WTR","dtype":"uint8","fill":[255],"fields":[{"name":"class","bits":[0,8]}],"flags":[{"name":"not_water","field":"class","in":[0]},{"name":"open_water","field":"class","in":[1]},{"name":"partial_water","field":"class","in":[2]},{"name":"snow","field":"class","in":[252]},{"name":"cloud","field":"class","in":[253]},{"name":"ocean","field":"class","in":[254]}],"presets":{"observed":["snow","cloud","ocean"],"water_only":["not_water","snow","cloud","ocean"],"open_water_only":["not_water","partial_water","snow","cloud","ocean"]},"default_preset":"water_only","gee":{"collections":["OPERA/DSWX/L3_V1/HLS"],"band":"B01_WTR"}},"opera_dswx_hls_conf":{"title":"OPERA DSWx-HLS v1 CONF (B03) water confidence","layer":"CONF","dtype":"uint8","fill":[255],"fields":[{"name":"class","bits":[0,8]}],"flags":[{"name":"not_water","field":"class","in":[0,10,20]},{"name":"water_high","field":"class","in":[1,11,21]},{"name":"water_moderate","field":"class","in":[2,12,22]},{"name":"partial_conservative","field":"class","in":[3,13,23]},{"name":"partial_aggressive","field":"class","in":[4,14,24]},{"name":"cloud","field":"class","in":[10,11,12,13,14]},{"name":"snow","field":"class","in":[20,21,22,23,24]},{"name":"ocean","field":"class","in":[254]}],"presets":{"high_conf_water":["not_water","water_moderate","partial_conservative","partial_aggressive","cloud","snow","ocean"],"any_water_clear":["not_water","cloud","snow","ocean"],"observed":["cloud","snow","ocean"]},"default_preset":"high_conf_water","gee":{"collections":["OPERA/DSWX/L3_V1/HLS"],"band":"B03_CONF"}},"opera_dist_alert_status":{"title":"OPERA DIST-ALERT-HLS v1 VEG-DIST-STATUS","layer":"VEG-DIST-STATUS","dtype":"uint8","fill":[255],"fields":[{"name":"status","bits":[0,8]}],"flags":[{"name":"none","field":"status","in":[0]},{"name":"first_low","field":"status","in":[1]},{"name":"provisional_low","field":"status","in":[2]},{"name":"confirmed_low","field":"status","in":[3,7]},{"name":"first_high","field":"status","in":[4]},{"name":"provisional_high","field":"status","in":[5]},{"name":"confirmed_high","field":"status","in":[6,8]}],"presets":{"confirmed_only":["none","first_low","provisional_low","first_high","provisional_high"],"confirmed_high_only":["none","first_low","provisional_low","confirmed_low","first_high","provisional_high"],"any_disturbance":["none"]},"default_preset":"confirmed_only","gee":{"collections":[],"band":"VEG-DIST-STATUS"}}};

function product(key) {
  var p = PRODUCTS[key];
  if (!p) throw new Error('Unknown product ' + key + '. Known: ' + Object.keys(PRODUCTS).join(', '));
  return p;
}

function resolve(p, names) {
  var out = [];
  (names || []).forEach(function (n) {
    if (p.presets[n]) out = out.concat(p.presets[n]);
    else if (p.flags.some(function (f) { return f.name === n; })) out.push(n);
    else throw new Error("'" + n + "' is not a flag or preset. Flags: " +
      p.flags.map(function (f) { return f.name; }).join(', ') + '. Presets: ' + Object.keys(p.presets).join(', '));
  });
  return out.filter(function (x, i) { return out.indexOf(x) === i; });
}

function fieldDef(p, name) {
  for (var i = 0; i < p.fields.length; i++) if (p.fields[i].name === name) return p.fields[i];
  throw new Error('Unknown field ' + name);
}

function flagDef(p, name) {
  for (var i = 0; i < p.flags.length; i++) if (p.flags[i].name === name) return p.flags[i];
  throw new Error('Unknown flag ' + name);
}

function fieldImage(qa, p, name) {
  var b = fieldDef(p, name).bits;
  return qa.rightShift(b[0]).bitwiseAnd((1 << b[1]) - 1);
}

function anyOf(img, values) {
  var out = img.eq(values[0]);
  for (var i = 1; i < values.length; i++) out = out.or(img.eq(values[i]));
  return out;
}

function flagImage(qa, p, name) {
  var f = flagDef(p, name);
  return anyOf(fieldImage(qa, p, f.field), f['in']);
}

function qaBand(img, p, options) {
  var band = (options && options.band) || p.gee.band || p.layer;
  // signed layers (MODIS SummaryQA, fill -1) become unsigned, like the Python core
  var bits = p.dtype === 'uint8' ? 8 : (p.dtype === 'int32' || p.dtype === 'uint32' ? 32 : 16);
  var qa = img.select(band).toInt64();
  if (p.dtype.charAt(0) === 'i') qa = qa.bitwiseAnd(Math.pow(2, bits) - 1);
  return qa;
}

function fillImage(qa, p) {
  var fill = qa.multiply(0);
  var bits = p.dtype === 'uint8' ? 8 : 16;
  var vals = (p.fill || []).map(function (v) { return v < 0 ? v + Math.pow(2, bits) : v; });
  if (vals.length) fill = fill.or(anyOf(qa, vals));
  if (p.fill_rule) fill = fill.or(anyOf(fieldImage(qa, p, p.fill_rule.field), p.fill_rule['in']));
  return fill;
}

function mask(img, key, options) {
  options = options || {};
  var p = product(key);
  var qa = qaBand(img, p, options);
  var drop = resolve(p, options.drop || [p.default_preset]);
  var keep = resolve(p, options.keep || []);
  var fill = fillImage(qa, p);
  var bad = qa.multiply(0);
  drop.forEach(function (f) { bad = bad.or(flagImage(qa, p, f)); });
  bad = bad.and(fill.not());
  if (options.buffer) bad = bad.focalMax({radius: options.buffer, kernelType: 'square', units: 'pixels'}).and(fill.not());
  if (keep.length) {
    var good = qa.multiply(0);
    keep.forEach(function (f) { good = good.or(flagImage(qa, p, f)); });
    bad = bad.or(good.not());
  }
  return bad.not().toByte().rename('qa_mask').updateMask(fill.not());
}

function apply(img, key, options) {
  var m = mask(img, key, options);
  return img.updateMask(m.eq(1));
}

function decode(img, key, options) {
  var p = product(key);
  var qa = qaBand(img, p, options);
  var bands = p.fields.map(function (f) { return fieldImage(qa, p, f.name).toByte().rename(f.name); });
  var out = bands[0];
  for (var i = 1; i < bands.length; i++) out = out.addBands(bands[i]);
  return out;
}

function products() { return Object.keys(PRODUCTS); }

function flags(key) {
  var p = product(key);
  return {flags: p.flags.map(function (f) { return f.name; }), presets: p.presets, defaultPreset: p.default_preset,
          collections: p.gee.collections, band: p.gee.band};
}

var QAMask = {PRODUCTS: PRODUCTS, products: products, flags: flags, mask: mask, apply: apply, decode: decode,
              _resolve: resolve};
if (typeof exports !== 'undefined') {
  exports.products = products; exports.flags = flags; exports.mask = mask; exports.apply = apply;
  exports.decode = decode; exports.PRODUCTS = PRODUCTS;
}

// ---- Demo: clear HLS median around Lake Naivasha, Kenya, Jan-Feb 2024 ----
// Set RUN_DEMO to false when you require() this file from another script.
var RUN_DEMO = true;
if (typeof Map === 'undefined' || typeof ee === 'undefined') RUN_DEMO = false;
if (RUN_DEMO) {
  var aoi = ee.Geometry.Rectangle([36.2, -0.95, 36.55, -0.65]);
  var hls = ee.ImageCollection('NASA/HLS/HLSL30/v002').merge(ee.ImageCollection('NASA/HLS/HLSS30/v002'))
    .filterBounds(aoi).filterDate('2024-01-01', '2024-03-01');
  var clean = hls.map(function (img) { return QAMask.apply(img, 'hls_fmask', {drop: ['clear']}); });
  print('HLS scenes', hls.size(), 'flags', QAMask.flags('hls_fmask'));
  Map.centerObject(aoi, 11);
  Map.addLayer(hls.median().clip(aoi), {bands: ['B04', 'B03', 'B02'], min: 0, max: 0.2}, 'HLS median, no mask', false);
  Map.addLayer(clean.median().clip(aoi), {bands: ['B04', 'B03', 'B02'], min: 0, max: 0.2}, 'HLS median, QA masked');
  Map.addLayer(clean.count().select('B04').clip(aoi), {min: 0, max: 20, palette: ['d73027', 'fee08b', '1a9850']}, 'clear observations');

  var l9 = ee.ImageCollection('LANDSAT/LC09/C02/T1_L2').filterBounds(aoi).filterDate('2024-01-01', '2024-03-01').first();
  Map.addLayer(QAMask.mask(l9, 'landsat_c2_qa_pixel', {drop: ['clear'], buffer: 2}).clip(aoi),
               {min: 0, max: 1, palette: ['d73027', '1a9850']}, 'Landsat 9 QA_PIXEL mask', false);
}
