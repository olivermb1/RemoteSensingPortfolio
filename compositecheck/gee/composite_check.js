/**
 * Composite Check for Google Earth Engine (Code Editor script), v0.1
 *
 * The JavaScript twin of the Python tool in ../compositecheck. It reads NASA
 * HLS v2.0 (Landsat L30 + Sentinel-2 S30) for an area and period, builds a
 * composite (or takes yours), and reports per pixel and per scene:
 *   - clear observations and the longest gap with no clear view
 *     (Francini et al. 2023 criterion 1)
 *   - days between each pixel's source observation and the target date
 *     (criterion 4) and their spread (criterion 5)
 *   - which scene each pixel came from and whether one scene dominates (new)
 *   - a robust outlier screen that flags scenes with missed cloud or haze (new)
 *   - Landsat vs Sentinel-2 agreement on near-same-day pairs, against the
 *     HLS v2.0 envelope of < 4.2% for red, NIR, SWIR1, SWIR2 (Ju et al. 2025)
 *
 * Paste into code.earthengine.google.com, edit the settings block, press Run.
 * Results print to the Console, show on the map, and can be exported with the
 * tasks at the bottom.
 *
 * STATUS: written without access to Earth Engine. The logic mirrors the
 * tested Python core but this script has only been syntax-checked. Expect to
 * fix small API slips on first run.
 */

// ---------------------------------------------------------------- settings
var AOI = ee.Geometry.Rectangle([36.00, -0.40, 36.12, -0.28]);  // Nakuru, Kenya
var START = '2024-01-01';
var END = '2024-06-30';         // inclusive
var TARGET = '2024-03-31';
var METHOD = 'medoid';          // 'medoid' | 'median' | 'target' (closest clear date)
var EXTERNAL = null;            // or an ee.Image composite to assess, bands renamed to BANDS
var FMASK_BITS = [0, 1, 2, 3];  // reject cirrus (reserved), cloud, adjacent, shadow; add 4 for snow
var DILATE = 1;                 // grow the cloud mask by N pixels
var DOMINANCE = 0.5;            // flag when one scene supplies more than this share
var PAIR_DAYS = 1;              // Landsat/Sentinel-2 pairs at most this many days apart
var PAIR_MIN_SHARE = 0.5;       // shared clear area for a pair to count as clean
var OUTLIER_Z = 3.5;            // robust z for the outlier screen
var MAD_FLOOR = 0.005;          // reflectance; stops stable pixels producing huge z
var ENVELOPE = 0.042;           // Ju et al. 2025 HLS v2.0 residual difference
var SCALE = 30;
var REFL_SCALE = 1;             // GEE serves HLS v002 as reflectance; set 0.0001 if values look like 0-10000

// ---------------------------------------------------------------- inputs
var BANDS = ['blue', 'green', 'red', 'nir', 'swir1', 'swir2'];
var L30_BANDS = ['B2', 'B3', 'B4', 'B5', 'B6', 'B7'];
var S30_BANDS = ['B2', 'B3', 'B4', 'B8A', 'B11', 'B12'];
var CHECKED = ['red', 'nir', 'swir1', 'swir2'];
var VISIBLE = ['blue', 'green', 'red'];
var LANDSAT = 1, SENTINEL2 = 2;

var start = ee.Date(START);
var end = ee.Date(END).advance(1, 'day');
var targetDay = ee.Date(TARGET).difference(start, 'day').floor();
var periodDays = ee.Date(END).difference(start, 'day');
var maskValue = FMASK_BITS.reduce(function (m, b) { return m + Math.pow(2, b); }, 0);

function prep(sensor, bandList) {
  return function (img) {
    var fm = img.select('Fmask');
    var bad = fm.bitwiseAnd(maskValue).neq(0);
    if (DILATE > 0) {
      bad = bad.focalMax({radius: DILATE, kernelType: 'square', units: 'pixels'});
    }
    var clear = bad.not().and(fm.mask());
    var t = ee.Date(img.get('system:time_start')).difference(start, 'day').floor();
    return img.select(bandList, BANDS).multiply(REFL_SCALE).float()
      .addBands(ee.Image.constant(t).toInt16().rename('t'))
      .addBands(ee.Image.constant(sensor).toByte().rename('sensor'))
      .addBands(fm.rightShift(6).bitwiseAnd(3).eq(3).rename('aer_high'))
      .updateMask(clear)
      .set({sensor: sensor, date: ee.Date(img.get('system:time_start')).format('YYYY-MM-dd'),
            scene_id: img.get('system:index'), 'system:time_start': img.get('system:time_start')});
  };
}

var l30 = ee.ImageCollection('NASA/HLS/HLSL30/v002').filterBounds(AOI).filterDate(start, end)
  .map(prep(LANDSAT, L30_BANDS));
var s30 = ee.ImageCollection('NASA/HLS/HLSS30/v002').filterBounds(AOI).filterDate(start, end)
  .map(prep(SENTINEL2, S30_BANDS));
var merged = l30.merge(s30).sort('system:time_start');
var n = merged.size();
var list = merged.toList(n);
var scenes = ee.ImageCollection(ee.List.sequence(0, n.subtract(1)).map(function (i) {
  var img = ee.Image(list.get(i));
  i = ee.Number(i).int();
  return img.addBands(ee.Image.constant(i).toInt16().rename('idx').updateMask(img.select('blue').mask()))
    .set('idx', i);
}));
var proj = ee.Image(merged.first()).select('blue').projection().atScale(SCALE);
function reduce(img, reducer) {
  return img.reduceRegion({reducer: reducer, geometry: AOI, crs: proj, scale: SCALE, maxPixels: 1e10});
}

// quick scale check: HLS reflectance should be well below 1.5
print('Median red of first scene (expect ~0.02-0.3):',
      reduce(ee.Image(merged.first()).select('red'), ee.Reducer.median()));

// ---------------------------------------------------------------- criterion 1: count and gaps
var nclear = scenes.select('blue').count().rename('nclear');
var tSorted = scenes.select('t').toArray().arraySlice(1, 0, 1).arrayProject([0]).arraySort().toInt32();
var padded = ee.Image.constant(0).toInt32().toArray().arrayCat(tSorted, 0)
  .arrayCat(ee.Image.constant(periodDays).toInt32().toArray(), 0);
var maxGap = padded.arraySlice(0, 1).subtract(padded.arraySlice(0, 0, -1))
  .arrayReduce(ee.Reducer.max(), [0]).arrayGet([0]).rename('max_gap');

// ---------------------------------------------------------------- outlier screen inputs
var med = scenes.select(BANDS).median();
var mad = scenes.map(function (img) {
  return img.select(BANDS).subtract(med).abs();
}).median().multiply(1.4826).max(MAD_FLOOR);
var enough = nclear.gte(5);
var withZ = scenes.map(function (img) {
  var z = img.select(VISIBLE).subtract(med.select(VISIBLE)).divide(mad.select(VISIBLE));
  var zmax = z.abs().reduce(ee.Reducer.max()).updateMask(enough).rename('zmax');
  var zblue = z.select('blue').updateMask(enough).rename('zblue');
  return img.addBands(zmax).addBands(zblue).addBands(zmax.gt(OUTLIER_Z).rename('outlier'));
});

// ---------------------------------------------------------------- the composite and its source scene
function nearestTo(target) {
  return withZ.map(function (img) {
    var d = img.select(BANDS).subtract(target).pow(2).reduce(ee.Reducer.sum());
    return img.addBands(d.multiply(-1).rename('q'));
  }).qualityMosaic('q');
}
var mosaic, composite, exact;
if (EXTERNAL !== null) {
  mosaic = nearestTo(EXTERNAL.select(BANDS));
  composite = EXTERNAL.select(BANDS);
  exact = false;
} else if (METHOD === 'target') {
  mosaic = withZ.map(function (img) {
    return img.addBands(img.select('t').subtract(targetDay).abs().multiply(-1).rename('q'));
  }).qualityMosaic('q');
  composite = mosaic.select(BANDS);
  exact = true;
} else {
  mosaic = nearestTo(med);
  composite = METHOD === 'median' ? med : mosaic.select(BANDS);
  exact = METHOD !== 'median';
}
var srcIdx = mosaic.select('idx').rename('src_scene');
var srcDay = mosaic.select('t').rename('src_day');  // days since START (the Python tool gives DOY)
var doyd = srcDay.subtract(targetDay).abs().rename('doyd');
var srcSensor = mosaic.select('sensor').rename('src_sensor');
var srcOutlier = mosaic.select('outlier').rename('src_outlier');
var landsatShare = scenes.select('sensor').map(function (img) {
  return img.eq(LANDSAT);
}).mean().rename('landsat_share');
var aerosolHigh = scenes.select('aer_high').mean().rename('aerosol_high_share');

// ---------------------------------------------------------------- scene dominance
var hist = ee.Dictionary(reduce(srcIdx, ee.Reducer.frequencyHistogram()).get('src_scene'));
var keys = hist.keys();
var counts = keys.map(function (k) { return ee.Number(hist.get(k)); });
var total = ee.Number(counts.reduce(ee.Reducer.sum()));
var shares = counts.map(function (c) { return ee.Number(c).divide(total); });
var hhi = ee.Number(shares.map(function (s) { return ee.Number(s).pow(2); }).reduce(ee.Reducer.sum()));
var topShare = ee.Number(shares.reduce(ee.Reducer.max()));
var topIdx = ee.Number.parse(keys.get(shares.indexOf(topShare)));
var srcShare = srcIdx.remap(keys.map(function (k) { return ee.Number.parse(k); }), shares)
  .rename('src_scene_share');

// ---------------------------------------------------------------- per-scene table
var gridPixels = ee.Number(reduce(ee.Image(1).rename('n'), ee.Reducer.count()).get('n'));
var sceneTable = ee.FeatureCollection(withZ.map(function (img) {
  var idx = ee.Number(img.get('idx'));
  var c = ee.Number(reduce(img.select('blue'), ee.Reducer.count()).get('blue'));
  var o = reduce(img.select(['outlier', 'zblue']),
                 ee.Reducer.mean().combine(ee.Reducer.median(), null, true));
  var outShare = ee.Algorithms.If(c.gte(100), o.get('outlier_mean'), null);
  var zb = ee.Algorithms.If(c.gte(100), o.get('zblue_median'), null);
  var contrib = ee.Number(hist.get(idx.format('%d'), 0)).divide(total);
  var suspect = ee.Algorithms.If(c.gte(100),
    ee.Number(o.get('outlier_mean', 0)).gt(0.2).or(ee.Number(o.get('zblue_median', 0)).gt(2)), false);
  return ee.Feature(null, {
    index: idx.add(1), scene_id: img.get('scene_id'), date: img.get('date'),
    sensor: ee.Algorithms.If(ee.Number(img.get('sensor')).eq(LANDSAT), 'Landsat', 'Sentinel-2'),
    clear_share: c.divide(gridPixels), contribution_share: contrib,
    outlier_share: outShare, median_z_blue: zb, suspect: suspect
  });
}));

// ---------------------------------------------------------------- Landsat vs Sentinel-2
function sensorMedian(code) {
  var sel = scenes.filter(ee.Filter.eq('sensor', code));
  return sel.select(BANDS).median().updateMask(sel.select('blue').count().gte(3));
}
var medL = sensorMedian(LANDSAT);
var medS = sensorMedian(SENTINEL2);
var lsRelDiff = medS.select(CHECKED).subtract(medL.select(CHECKED)).abs()
  .divide(medS.select(CHECKED).add(medL.select(CHECKED)).divide(2))
  .reduce(ee.Reducer.max()).rename('ls_rel_diff');

function pairStats(l, s) {
  // robust: median |S - L| / median((S + L) / 2), and the signed median bias
  var both = l.select('blue').mask().and(s.select('blue').mask());
  var lb = l.select(BANDS).updateMask(both);
  var sb = s.select(BANDS).updateMask(both);
  var absd = reduce(sb.subtract(lb).abs(), ee.Reducer.median());
  var bias = reduce(sb.subtract(lb), ee.Reducer.median());
  var mean = reduce(sb.add(lb).divide(2), ee.Reducer.median());
  var px = ee.Number(reduce(both.selfMask().rename('n'), ee.Reducer.count()).get('n'));
  var props = {pixels: px, shared_clear_share: px.divide(gridPixels)};
  var ok = ee.Number(1);
  BANDS.forEach(function (b) {
    var rd = ee.Number(absd.get(b)).divide(ee.Number(mean.get(b)));
    props[b + '_rel_diff'] = rd;
    props[b + '_bias'] = ee.Number(bias.get(b)).divide(ee.Number(mean.get(b)));
    if (CHECKED.indexOf(b) >= 0) { ok = ok.and(rd.lt(ENVELOPE)); }
  });
  props.within_envelope = ok;
  props.clean = px.divide(gridPixels).gte(PAIR_MIN_SHARE);
  return props;
}
var joined = ee.Join.inner().apply(
  scenes.filter(ee.Filter.eq('sensor', LANDSAT)),
  scenes.filter(ee.Filter.eq('sensor', SENTINEL2)),
  ee.Filter.maxDifference({difference: PAIR_DAYS * 86400000 + 43200000,
                           leftField: 'system:time_start', rightField: 'system:time_start'}));
var pairs = ee.FeatureCollection(joined.map(function (f) {
  var l = ee.Image(f.get('primary'));
  var s = ee.Image(f.get('secondary'));
  return ee.Feature(null, pairStats(l, s)).set({
    landsat: l.get('scene_id'), sentinel2: s.get('scene_id'),
    days_apart: ee.Date(l.get('system:time_start')).difference(ee.Date(s.get('system:time_start')), 'day').abs().round()
  });
})).filter(ee.Filter.gte('pixels', 1000));
var cleanPairs = pairs.filter(ee.Filter.eq('clean', 1));

// ---------------------------------------------------------------- summary
var qa = nclear.addBands(maxGap).addBands(srcIdx.add(1).rename('src_scene'))
  .addBands(srcDay).addBands(doyd).addBands(srcSensor).addBands(landsatShare)
  .addBands(srcShare).addBands(srcOutlier).addBands(lsRelDiff).addBands(aerosolHigh).toFloat();

var summary = ee.Dictionary({
  scenes: n, landsat_scenes: l30.size(), sentinel2_scenes: s30.size(),
  method: EXTERNAL !== null ? 'external' : METHOD, source_is_exact: exact,
  median_clear: reduce(nclear, ee.Reducer.median()).get('nclear'),
  share_below_5: reduce(nclear.lt(5), ee.Reducer.mean()).get('nclear'),
  median_max_gap_days: reduce(maxGap, ee.Reducer.median()).get('max_gap'),
  mean_doyd: reduce(doyd, ee.Reducer.mean()).get('doyd'),
  doy_spread_sd: reduce(srcDay, ee.Reducer.stdDev()).get('src_day'),
  top_scene: ee.Image(list.get(topIdx)).get('scene_id'),
  top_share: topShare, effective_scenes: ee.Number(1).divide(hhi),
  dominated: topShare.gt(DOMINANCE),
  selected_outlier_share: reduce(srcOutlier, ee.Reducer.mean()).get('src_outlier'),
  composite_from_landsat: reduce(srcSensor.eq(LANDSAT), ee.Reducer.mean()).get('src_sensor'),
  pairs: pairs.size(), clean_pairs: cleanPairs.size(),
  clean_pairs_within_envelope: cleanPairs.filter(ee.Filter.eq('within_envelope', 1)).size(),
  clean_pair_median_rel_diff: ee.Dictionary.fromLists(CHECKED, CHECKED.map(function (b) {
    return cleanPairs.aggregate_array(b + '_rel_diff').reduce(ee.Reducer.median());
  }))
});
print('Composite Check summary', summary);
print('Scenes (contribution, outlier screen)', sceneTable);
print('Landsat vs Sentinel-2 pairs', pairs);

print(ui.Chart.feature.byFeature(sceneTable, 'date', ['contribution_share'])
  .setChartType('ColumnChart')
  .setOptions({title: 'Share of the composite from each scene', legend: {position: 'none'},
               vAxis: {title: 'share'}, colors: ['#2a78d6']}));

// ---------------------------------------------------------------- map
Map.centerObject(AOI, 12);
Map.addLayer(composite, {bands: ['red', 'green', 'blue'], min: 0.01, max: 0.18}, 'Composite');
Map.addLayer(nclear, {min: 0, max: 60, palette: ['#f1f6fd', '#08306b']}, 'Clear observations', false);
Map.addLayer(maxGap, {min: 0, max: 60, palette: ['#fff5eb', '#7f2704']}, 'Longest gap (days)', false);
Map.addLayer(doyd, {min: 0, max: 60, palette: ['#fcfbfd', '#3f007d']}, 'Days from target', false);
Map.addLayer(srcShare, {min: 0, max: 0.8, palette: ['#fff5f0', '#67000d']}, 'Area share of source scene');
Map.addLayer(srcOutlier.selfMask(), {palette: ['#e34948']}, 'Source observation is an outlier', false);
Map.addLayer(srcSensor, {min: 1, max: 2, palette: ['#2a78d6', '#eb6834']}, 'Sensor (blue Landsat, orange S2)', false);
Map.addLayer(lsRelDiff, {min: 0, max: 0.2, palette: ['#f7f7f7', '#e34948']}, 'Landsat vs S2 composite difference', false);

// ---------------------------------------------------------------- exports (start them from the Tasks tab)
Export.image.toDrive({image: qa, description: 'compositecheck_qa_layers', region: AOI, crs: proj.crs(),
                      scale: SCALE, maxPixels: 1e10});
Export.image.toDrive({image: composite.toFloat(), description: 'compositecheck_composite', region: AOI,
                      crs: proj.crs(), scale: SCALE, maxPixels: 1e10});
Export.table.toDrive({collection: sceneTable, description: 'compositecheck_scenes', fileFormat: 'CSV'});
Export.table.toDrive({collection: pairs, description: 'compositecheck_pairs', fileFormat: 'CSV'});
