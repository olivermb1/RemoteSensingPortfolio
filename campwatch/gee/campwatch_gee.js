// Camp Growth Watch, Google Earth Engine version (v0.1).
//
// When and how fast do new shelter areas (refugee/IDP camps, informal
// extensions) appear? Same rules as the Python tool (campwatch/core.py):
//   for each dry-season month, compared with the same calendar month of a
//   baseline year, after removing the area-wide median change:
//     shelter = blue/red rose >= 0.07 AND blue rose >= 0.015 AND NDVI <= 0.30
//   each month is then smoothed with its neighbours (majority of 3), and a
//   pixel's first-seen month is the first shelter month after which it stays
//   shelter in at least half of the later months.
// Outputs: first-seen month image, footprint (ha) per area per month as a chart
// and a table, and detected areas as polygons (connected new pixels >= 5 ha).
//
// Differences from Python: polygons come from reduceToVectors at 10 m without
// the gap-closing buffer; months with no clear image are skipped the same way.
// Not run in real Earth Engine (only a Node dry run with a mock ee).

// ---------------- settings ----------------
var AOI = ee.Geometry.Rectangle([21.56, 13.04, 21.74, 13.23]);  // Alacha and Arkoum camps, eastern Chad
var BASELINE = ['2021-11-01', '2022-06-01'];
var PERIOD = ['2023-01-01', '2025-04-01'];
var DRY_MONTHS = [11, 12, 1, 2, 3, 4, 5];
var T_RATIO = 0.07, T_BLUE = 0.015, MAX_NDVI = 0.30, PERSIST = 0.5, MIN_AREA_HA = 5;
var UNITS = null;  // e.g. ee.FeatureCollection('users/you/camp_outlines'); null = detected areas
var EXPORT = false;

// ---------------- helpers ----------------
var S2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(AOI);

function indices(img) {
  var scl = img.select('SCL');
  var ok = scl.eq(2).or(scl.eq(4)).or(scl.eq(5)).or(scl.eq(6)).or(scl.eq(7));
  var x = img.select(['B2', 'B4', 'B8']).divide(10000);
  var ratio = x.select('B2').divide(x.select('B4')).rename('ratio');
  var ndvi = x.normalizedDifference(['B8', 'B4']).rename('ndvi');
  return ee.Image.cat([ratio, x.select('B2').rename('blue'), ndvi]).updateMask(ok)
    .copyProperties(img, ['system:time_start']);
}

function monthsBetween(a, b) {
  var start = ee.Date(a), n = ee.Date(b).difference(start, 'month').floor();
  return ee.List.sequence(0, n.subtract(1)).map(function (k) { return start.advance(k, 'month'); });
}

var dry = ee.List(DRY_MONTHS);
function isDry(d) { return dry.contains(ee.Date(d).get('month')); }

// baseline per calendar month (median over the baseline window)
var baseCol = S2.filterDate(BASELINE[0], BASELINE[1]).map(indices);
function baselineFor(month) {
  var m = ee.Date(month).get('month');
  return baseCol.filter(ee.Filter.calendarRange(m, m, 'month')).median();
}

var months = monthsBetween(PERIOD[0], PERIOD[1]).map(function (d) {
  return ee.Algorithms.If(isDry(d), d, null);
}, true);

var shelter = ee.ImageCollection.fromImages(months.map(function (d) {
  d = ee.Date(d);
  var cur = S2.filterDate(d, d.advance(1, 'month')).map(indices).median();
  var base = baselineFor(d);
  var dr = cur.select('ratio').subtract(base.select('ratio'));
  var db = cur.select('blue').subtract(base.select('blue'));
  var med = ee.Image.cat([dr, db]).reduceRegion({reducer: ee.Reducer.median(), geometry: AOI, scale: 20,
    maxPixels: 1e9, bestEffort: true});
  dr = dr.subtract(ee.Number(med.get('ratio')));
  db = db.subtract(ee.Number(med.get('blue')));
  var s = dr.gte(T_RATIO).and(db.gte(T_BLUE)).and(cur.select('ndvi').lte(MAX_NDVI));
  return s.rename('s').set('system:time_start', d.millis())
    .set('n_images', S2.filterDate(d, d.advance(1, 'month')).size());
})).filter(ee.Filter.gt('n_images', 0)).sort('system:time_start');

// smoothing: majority with neighbouring months
var list = shelter.toList(200);
var n = list.size();
var smoothed = ee.ImageCollection.fromImages(ee.List.sequence(0, n.subtract(1)).map(function (i) {
  i = ee.Number(i);
  var lo = i.subtract(1).max(0), hi = i.add(1).min(n.subtract(1));
  var w = ee.ImageCollection.fromImages(list.slice(lo, hi.add(1)));
  var img = ee.Image(list.get(i));
  return w.mean().gt(0.5).updateMask(img.mask()).rename('p')
    .set('system:time_start', img.get('system:time_start'));
}));

// first-seen month: first p = 1 with mean of later months >= PERSIST
var plist = smoothed.toList(200);
var firstSeen = ee.ImageCollection.fromImages(ee.List.sequence(0, n.subtract(1)).map(function (i) {
  i = ee.Number(i);
  var img = ee.Image(plist.get(i));
  var later = ee.ImageCollection.fromImages(plist.slice(i)).mean();
  var month = ee.Date(img.get('system:time_start')).format('YYYYMM');
  return ee.Image.constant(ee.Number.parse(month)).toInt32()
    .updateMask(img.eq(1).and(later.gte(PERSIST))).rename('first');
})).min();

// areas
var newPix = firstSeen.mask().selfMask();
var areas = UNITS ? UNITS : newPix.reduceToVectors({geometry: AOI, scale: 10, eightConnected: true,
  geometryType: 'polygon', maxPixels: 1e9})
  .map(function (f) { return f.set('area_ha', f.geometry().area(1).divide(1e4)); })
  .filter(ee.Filter.gte('area_ha', MIN_AREA_HA));
areas = ee.FeatureCollection(areas).map(function (f) { return f.set('label', f.id()); });

// footprint (ha) per area per month
var footprint = ee.FeatureCollection(smoothed.map(function (img) {
  var m = ee.Number.parse(ee.Date(img.get('system:time_start')).format('YYYYMM'));
  var foot = firstSeen.lte(m).unmask(0).multiply(ee.Image.pixelArea()).divide(1e4).rename('footprint_ha');
  return foot.reduceRegions({collection: areas, reducer: ee.Reducer.sum().setOutputs(['footprint_ha']), scale: 10})
    .map(function (f) { return f.set('month', m); });
}).flatten());

// ---------------- display ----------------
Map.centerObject(AOI, 12);
Map.addLayer(S2.filterDate(ee.Date(PERIOD[1]).advance(-2, 'month'), PERIOD[1]).median().clip(AOI),
  {bands: ['B4', 'B3', 'B2'], min: 0, max: 3000}, 'Latest', false);
Map.addLayer(firstSeen.clip(AOI), {min: 202301, max: 202503, palette: ['0d0887', '9c179e', 'ed7953', 'f0f921']},
  'First seen (YYYYMM)');
Map.addLayer(areas.style({color: '00ffff', fillColor: '00000000'}), {}, 'Areas');
print('Months used', smoothed.aggregate_array('system:time_start').map(function (t) { return ee.Date(t).format('YYYY-MM'); }));
print(ui.Chart.feature.groups(footprint, 'month', 'footprint_ha', 'label')
  .setOptions({title: 'New shelter footprint (ha)'}));

if (EXPORT) {
  Export.table.toDrive({collection: footprint, description: 'campwatch_timeseries', fileFormat: 'CSV'});
  Export.table.toDrive({collection: areas, description: 'campwatch_areas', fileFormat: 'GeoJSON'});
  Export.image.toDrive({image: firstSeen.unmask(0).clip(AOI), description: 'campwatch_first_seen', region: AOI,
    scale: 10, maxPixels: 1e9});
}
