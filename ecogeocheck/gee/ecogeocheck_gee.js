// ECOSTRESS Geo Check for Google Earth Engine (Code Editor script).
//
// Earth Engine carries ECOSTRESS tiled LST (NASA/ECOSTRESS/L2T_LSTE/V2) but not NASA's
// GeolocationAccuracyQA flag, so a badly placed scene (2 to 7 km off) looks like any other.
// This script does two things for each image over your area:
//   1. Joins NASA's flag from a table you upload (geo_flags.csv from `python -m ecogeocheck
//      fetch`, or NASA's summary file turned into a CSV with orbit, scene and
//      GeolocationAccuracyQA columns), matching on orbit and scene number.
//   2. Measures the image's offset: edges in LST (lake shores, coasts) against edges in the
//      image's own `water` band, with ee.Image.displacement. The water band comes from a static
//      map, so it sits in the right place even when the LST is shifted (an inference, see README).
// It then keeps images that pass both, charts mean LST of kept vs all images, and exports
// a per-image table.
//
// UNTESTED IN EARTH ENGINE. In particular: the image ID format (the orbit and scene are read
// from system:index with ID_REGEX), whether `water` is populated in every image, and how
// ee.Image.displacement behaves on 70 m edge images. Check the printed first image first.

// ---------------------------------------------------------------- settings
var AOI = ee.Geometry.Rectangle([36.0, -0.95, 36.45, -0.12]);   // Kenyan Rift lakes: Nakuru to Naivasha
var START = '2025-01-01', END = '2025-09-01';
var FLAG_TABLE = null;            // e.g. 'projects/your-project/assets/geo_flags' (orbit, scene, GeolocationAccuracyQA)
var ACCEPT = ['best', 'good'];    // NASA flags to keep
var TOLERANCE_M = 140;            // largest measured offset to accept (2 pixels)
var MAX_OFFSET_M = 7700;          // search radius; NASA's worst case is 7 km
var MEASURE = true;               // measure offsets (slow on long date ranges)
var KEEP_UNFLAGGED_IF_MEASURED_OK = true;  // no flag found, but measured within tolerance: keep
var ID_REGEX = '_(\\d{5})_(\\d{3})_';       // orbit and scene inside system:index

// ---------------------------------------------------------------- data
var col = ee.ImageCollection('NASA/ECOSTRESS/L2T_LSTE/V2').filterBounds(AOI).filterDate(START, END);

function withIds(img) {
  var m = ee.String(img.get('system:index')).match(ID_REGEX);
  var ok = m.length().gte(3);
  var orbit = ee.Algorithms.If(ok, ee.Number.parse(ee.String(m.get(1))), -1);
  var scene = ee.Algorithms.If(ok, ee.Number.parse(ee.String(m.get(2))), -1);
  return img.set({orbit: orbit, scene: scene, key: ee.String(ee.Number(orbit).format('%d')).cat('_')
    .cat(ee.Number(scene).format('%d'))});
}
col = col.map(withIds);
print('First image (check orbit/scene parsed from the ID):', col.first());

// ---------------------------------------------------------------- 1. NASA flag
if (FLAG_TABLE) {
  var table = ee.FeatureCollection(FLAG_TABLE).map(function (f) {
    return f.set('key', ee.String(ee.Number.parse(ee.String(f.get('orbit'))).format('%d')).cat('_')
      .cat(ee.Number.parse(ee.String(f.get('scene'))).format('%d')));
  });
  var joined = ee.Join.saveFirst('flag').apply(col, table, ee.Filter.equals({leftField: 'key', rightField: 'key'}));
  col = ee.ImageCollection(joined).map(function (img) {
    var f = ee.Feature(img.get('flag'));
    return img.set('geo_qa', ee.String(f.get('GeolocationAccuracyQA')).toLowerCase());
  });
  // Images with no match in the table drop out of a saveFirst join; add them back as unflagged.
  var flaggedIds = col.aggregate_array('system:index');
  var unflagged = ee.ImageCollection('NASA/ECOSTRESS/L2T_LSTE/V2').filterBounds(AOI).filterDate(START, END)
    .map(withIds).filter(ee.Filter.inList('system:index', flaggedIds).not()).map(function (img) {
      return img.set('geo_qa', 'none');
    });
  col = col.merge(unflagged);
} else {
  col = col.map(function (img) { return img.set('geo_qa', 'none'); });
}

// ---------------------------------------------------------------- 2. measured offset
function edgeStrength(img) {
  var s = img.focalMean({radius: 1, units: 'pixels'});
  var g = s.gradient();
  return g.select('x').hypot(g.select('y')).focalMean({radius: 2, units: 'pixels'});
}

function measure(img) {
  var clear = img.select('cloud').neq(1);
  var lst = img.select('LST').updateMask(clear.and(img.select('LST').gt(150)));
  var water = img.select('water').eq(1);
  var region = AOI.intersection(img.geometry(), 100);
  var waterFrac = water.reduceRegion({reducer: ee.Reducer.mean(), geometry: region, scale: 70,
                                      maxPixels: 1e9, bestEffort: true}).get('water');
  var disp = edgeStrength(lst).displacement({
    referenceImage: edgeStrength(water.toFloat()), maxOffset: MAX_OFFSET_M, patchWidth: 2000
  });
  var med = disp.reduceRegion({reducer: ee.Reducer.median(), geometry: region, scale: 140,
                               maxPixels: 1e9, bestEffort: true});
  var dx = ee.Number(med.get('dx')), dy = ee.Number(med.get('dy'));
  var usable = ee.Number(ee.Algorithms.If(waterFrac, waterFrac, 0)).gt(0.005);
  // displacement() returns how far to move the image to match the reference, so the content
  // sits at minus that; we report the content's offset, east and north positive.
  return img.set({
    water_fraction: waterFrac,
    measured: usable,
    offset_east_m: ee.Algorithms.If(usable, dx.multiply(-1), null),
    offset_north_m: ee.Algorithms.If(usable, dy.multiply(-1), null),
    offset_m: ee.Algorithms.If(usable, dx.hypot(dy), null)
  });
}
if (MEASURE) col = col.map(measure);

// ---------------------------------------------------------------- decision
function decide(img) {
  var qa = ee.String(img.get('geo_qa'));
  var flagged = ee.List(['best', 'good', 'suspect', 'poor']).contains(qa);
  var accepted = ee.List(ACCEPT).contains(qa);
  var measured = MEASURE ? ee.Number(ee.Algorithms.If(img.get('measured'), 1, 0)).eq(1) : ee.Number(0).eq(1);
  var off = ee.Number(ee.Algorithms.If(measured, img.get('offset_m'), 0));
  var big = measured.and(off.gt(TOLERANCE_M));
  var decision = ee.Algorithms.If(big, 'drop',
    ee.Algorithms.If(accepted, 'keep',
      ee.Algorithms.If(flagged, 'drop',
        ee.Algorithms.If(measured.and(KEEP_UNFLAGGED_IF_MEASURED_OK), 'keep', 'check'))));
  return img.set('decision', decision);
}
col = col.map(decide);
var kept = col.filter(ee.Filter.eq('decision', 'keep'));

print('Images per decision:', col.aggregate_histogram('decision'));
print('Images per NASA flag:', col.aggregate_histogram('geo_qa'));

// ---------------------------------------------------------------- map, chart, export
Map.centerObject(AOI, 10);
var vis = {min: 285, max: 320, palette: ['#313695', '#74add1', '#ffffbf', '#f46d43', '#a50026']};
Map.addLayer(col.select('LST').mean().clip(AOI), vis, 'Mean LST, all images', false);
Map.addLayer(kept.select('LST').mean().clip(AOI), vis, 'Mean LST, kept images');
Map.addLayer(ee.Image(col.first()).select('water').selfMask().clip(AOI), {palette: ['#2166ac']}, 'Water band', false);

print(ui.Chart.feature.byFeature(col.map(function (img) {
  return ee.Feature(null, {time: img.date().millis(), offset_m: img.get('offset_m')});
}), 'time', ['offset_m']).setOptions({title: 'Measured offset per image (m)', pointSize: 4, lineWidth: 0}));

Export.table.toDrive({
  collection: col.map(function (img) {
    return ee.Feature(null, img.toDictionary(['orbit', 'scene', 'geo_qa', 'decision', 'offset_m', 'offset_east_m',
      'offset_north_m', 'water_fraction'])).set('id', img.get('system:index')).set('time', img.date().format());
  }),
  description: 'ecostress_geocheck', fileFormat: 'CSV'
});
