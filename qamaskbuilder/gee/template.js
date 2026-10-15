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

var PRODUCTS = /*@@PRODUCTS@@*/{};

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
