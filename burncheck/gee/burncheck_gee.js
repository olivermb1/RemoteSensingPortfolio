// Burned Settlement Check, Google Earth Engine version (v0.1).
//
// Which 250 m town blocks show new burn scars inside buildings between two
// dates? Same pixel rules as the Python tool (burncheck/core.py):
//   burned = clear on both composites
//            AND dNBR - local building background >= T_DNBR
//            AND brightness (visible + SWIR mean) fell by >= T_DARK
// Per unit: % of building pixels burned; likely burned >= 20 % and >= 8 px,
// possible >= 7 % and >= 4 px, not enough clear data if < 50 % of building
// pixels were seen on both dates.
//
// Differences from Python: units are a regular 250 m grid (or your own table)
// rather than building clusters; the local background is a 1 km median resampled
// bilinearly (Python adds a 3x3 smoothing of the block grid); buildings come from
// Google Open Buildings v3 (Python uses Overture, which includes them).
// FIRMS gives the number of fire-days in each unit (1 km MODIS pixels).
//
// A burn scar is evidence of fire or removed shelters, not proof of an attack.
// Check every flagged unit against imagery and reporting before using it.

// ---------------- settings ----------------
var AOI = ee.Geometry.Rectangle([22.40, 13.41, 22.49, 13.49]);   // El Geneina, West Darfur
var BEFORE = ['2023-03-28', '2023-04-21'];
var AFTER = ['2023-05-25', '2023-06-21'];
var UNITS = null;            // e.g. ee.FeatureCollection('users/you/blocks'); null = 250 m grid
var CELL_M = 250;
var MIN_BUILDINGS = 5;
var BUILDING_CONFIDENCE = 0.7;
var T_DNBR = 0.10, T_DARK = 0.05;
var LIKELY_PCT = 20, LIKELY_PX = 8, POSSIBLE_PCT = 7, POSSIBLE_PX = 4, MIN_CLEAR_PCT = 50;
var EXPORT = false;

// ---------------- helpers ----------------
function maskS2(img) {
  var scl = img.select('SCL');
  var ok = scl.eq(2).or(scl.eq(4)).or(scl.eq(5)).or(scl.eq(6)).or(scl.eq(7));
  return img.select(['B2', 'B3', 'B4', 'B8', 'B11', 'B12'], ['blue', 'green', 'red', 'nir', 'swir1', 'swir2'])
    .divide(10000).updateMask(ok);
}

function composite(range) {
  return ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
    .filterBounds(AOI).filterDate(range[0], range[1])
    .map(maskS2).median();
}

function nbr(x) { return x.normalizedDifference(['nir', 'swir2']); }
function brightness(x) { return x.select(['blue', 'green', 'red', 'swir1', 'swir2']).reduce(ee.Reducer.mean()); }

// ---------------- pixels ----------------
var before = composite(BEFORE);
var after = composite(AFTER);
var proj = ee.Projection('EPSG:3857').atScale(10);
var s2proj = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(AOI).first().select('B4').projection();

var buildings = ee.FeatureCollection('GOOGLE/Research/open-buildings/v3/polygons')
  .filterBounds(AOI).filter(ee.Filter.gte('confidence', BUILDING_CONFIDENCE));
// a 5 m buffer approximates "any pixel the footprint touches"
var bld = ee.Image(0).paint(buildings.map(function (f) { return f.buffer(5); }), 1)
  .reproject(s2proj).selfMask().rename('bld');

var clear = before.select('nir').mask().and(after.select('nir').mask()).rename('clear');
var dnbr = nbr(before).subtract(nbr(after)).rename('dnbr');
var background = dnbr.updateMask(bld)
  .reduceResolution({reducer: ee.Reducer.median(), maxPixels: 20000})
  .reproject(s2proj.atScale(1000))
  .resample('bilinear').reproject(s2proj);
var overall = ee.Number(dnbr.updateMask(bld).reduceRegion({reducer: ee.Reducer.median(), geometry: AOI,
  scale: 10, maxPixels: 1e9, bestEffort: true}).get('dnbr'));
background = background.unmask(overall);
var anomaly = dnbr.subtract(background).rename('anomaly');
var bb = brightness(before), ba = brightness(after);
var darkening = ba.subtract(bb).divide(bb).rename('darkening');
var burned = anomaly.gte(T_DNBR).and(darkening.lte(-T_DARK)).and(clear).rename('burned');

// ---------------- units ----------------
var units = UNITS ? UNITS : AOI.coveringGrid(ee.Projection('EPSG:3857').atScale(CELL_M));
var withCounts = units.map(function (f) {
  return f.set('n_buildings', buildings.filterBounds(f.geometry()).size());
}).filter(ee.Filter.gte('n_buildings', MIN_BUILDINGS));

var stack = ee.Image.cat([
  bld.unmask(0).rename('bld_px'),
  bld.unmask(0).and(clear.unmask(0)).rename('bld_clear_px'),
  bld.unmask(0).and(burned.unmask(0)).rename('burned_px'),
  anomaly.updateMask(bld).updateMask(clear).rename('mean_anomaly')
]);
var sums = stack.select(['bld_px', 'bld_clear_px', 'burned_px']).reduceRegions({
  collection: withCounts, reducer: ee.Reducer.sum(), scale: 10, crs: s2proj});
var stats = stack.select('mean_anomaly').reduceRegions({
  collection: sums, reducer: ee.Reducer.mean().setOutputs(['mean_anomaly']), scale: 10, crs: s2proj});

// FIRMS fire-days between the end of the before window and the end of the after window
var firms = ee.ImageCollection('FIRMS').filterDate(BEFORE[1], AFTER[1]).select('T21')
  .map(function (i) { return i.gt(0).unmask(0); }).sum().rename('firms_days');
stats = firms.reduceRegions({collection: stats, reducer: ee.Reducer.max().setOutputs(['firms_days']), scale: 1000});

var classified = stats.map(function (f) {
  var bp = ee.Number(f.get('bld_px')), cp = ee.Number(f.get('bld_clear_px')), np_ = ee.Number(f.get('burned_px'));
  var clearPct = ee.Number(ee.Algorithms.If(bp.gt(0), cp.divide(bp).multiply(100), 0));
  var burnedPct = ee.Number(ee.Algorithms.If(cp.gt(0), np_.divide(cp).multiply(100), 0));
  var cls = ee.Algorithms.If(clearPct.lt(MIN_CLEAR_PCT), 'not enough clear data',
    ee.Algorithms.If(burnedPct.gte(LIKELY_PCT).and(np_.gte(LIKELY_PX)), 'likely burned',
      ee.Algorithms.If(burnedPct.gte(POSSIBLE_PCT).and(np_.gte(POSSIBLE_PX)), 'possible', 'no sign')));
  return f.set({clear_pct: clearPct, burned_pct: burnedPct, burned_ha: np_.multiply(0.01), 'class': cls});
});

// ---------------- display ----------------
Map.centerObject(AOI, 13);
var vis = {bands: ['red', 'green', 'blue'], min: 0, max: 0.3};
Map.addLayer(before.clip(AOI), vis, 'Before', false);
Map.addLayer(after.clip(AOI), vis, 'After');
Map.addLayer(anomaly.clip(AOI), {min: -0.2, max: 0.3, palette: ['1a9850', 'ffffbf', 'd73027']}, 'dNBR anomaly', false);
Map.addLayer(burned.selfMask().updateMask(bld).clip(AOI), {palette: ['ff0000']}, 'Burned building pixels');
var styled = classified.map(function (f) {
  var c = ee.Dictionary({'likely burned': 'c0392b', 'possible': 'e67e22', 'no sign': '7f8c8d',
    'not enough clear data': '2980b9'}).get(f.get('class'));
  return f.set('style', {color: c, fillColor: ee.String(c).cat('66'), width: 1});
});
Map.addLayer(styled.style({styleProperty: 'style'}), {}, 'Units by class');
print('Units per class', classified.aggregate_histogram('class'));
print('Likely burned', classified.filter(ee.Filter.eq('class', 'likely burned')).sort('burned_pct', false).limit(50));

if (EXPORT) {
  Export.table.toDrive({collection: classified, description: 'burncheck_units', fileFormat: 'GeoJSON'});
  Export.image.toDrive({image: burned.updateMask(bld).unmask(0).toByte().clip(AOI), description: 'burncheck_burned',
    region: AOI, scale: 10, maxPixels: 1e9});
}
