// Abandoned Fields, Google Earth Engine version (v0.1).
//
// Which normally farmed fields were not farmed in a target season? Same rules as
// the Python tool (fallowcheck/core.py):
//   peak = 90th percentile of clear NDVI in the season window (SCL 4, 5 only)
//   farmed in normal years: median baseline peak >= 0.40
//   not farmed: farmed in normal years AND target peak < 0.30 AND drop >= 0.15
//   reduced:    farmed in normal years AND drop >= 0.15 but target still >= 0.30
// plus the field-pattern check: mean |peak - 50 m local mean| per unit, target
// season divided by the median of the baseline seasons. A ratio well below the
// normal-year spread means the patchwork of separate fields has gone, e.g.
// weeds over everything after a wet season on unmanaged land.
// Per-unit leave-one-out (normal-year floor) is in the Python version only.
// Not run in real Earth Engine (only a Node dry run with a mock ee).

var AOI = ee.Geometry.Rectangle([33.38, 14.20, 33.50, 14.32]);   // Gezira scheme near Wad Madani, Sudan
var BASELINE_YEARS = [2021, 2022, 2023];
var TARGET_YEAR = 2024;
var SEASON = ['07-15', '11-30'];
var CELL_M = 1000;
var MIN_BASE = 0.40, MAX_TARGET = 0.30, MIN_DROP = 0.15;
var EXPORT = false;

var cropland = ee.Image('ESA/WorldCover/v200/2021').eq(40);

function ndvi(img) {
  var scl = img.select('SCL');
  return img.normalizedDifference(['B8', 'B4']).rename('ndvi').updateMask(scl.eq(4).or(scl.eq(5)));
}

function peak(year) {
  var start = ee.Date(year + '-' + SEASON[0]);
  var end = ee.Date(year + '-' + SEASON[1]);
  end = ee.Date(ee.Algorithms.If(end.millis().lt(start.millis()), end.advance(1, 'year'), end));
  return ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(AOI).filterDate(start, end.advance(1, 'day'))
    .map(ndvi).reduce(ee.Reducer.percentile([90])).rename('peak');
}

function contrast(p) {
  return p.subtract(p.reduceNeighborhood(ee.Reducer.mean(), ee.Kernel.square(25, 'meters'))).abs().rename('contrast');
}

var basePeaks = ee.ImageCollection(BASELINE_YEARS.map(peak));
var base = basePeaks.median();
var target = peak(TARGET_YEAR);
var farmed = base.gte(MIN_BASE).and(cropland);
var drop = base.subtract(target);
var cls = ee.Image(0).where(farmed, 1)
  .where(farmed.and(drop.gte(MIN_DROP)), 2)
  .where(farmed.and(drop.gte(MIN_DROP)).and(target.lt(MAX_TARGET)), 3)
  .where(farmed.and(target.mask().not()), 255).rename('class').clip(AOI);

var units = AOI.coveringGrid(ee.Projection('EPSG:3857').atScale(CELL_M));
var area = ee.Image.pixelArea().divide(1e4);
var stack = ee.Image.cat([
  area.updateMask(cls.gte(1).and(cls.lte(3))).rename('farmed_seen_ha'),
  area.updateMask(cls.eq(3)).rename('not_farmed_ha'),
  area.updateMask(cls.eq(2)).rename('reduced_ha'),
  contrast(target).updateMask(cropland).rename('contrast_target'),
  ee.ImageCollection(BASELINE_YEARS.map(function (y) { return contrast(peak(y)); })).median()
    .updateMask(cropland).rename('contrast_base')
]);
var table = stack.reduceRegions({collection: units,
  reducer: ee.Reducer.sum().forEach(['farmed_seen_ha', 'not_farmed_ha', 'reduced_ha'])
    .combine(ee.Reducer.mean().forEach(['contrast_target', 'contrast_base']), null, true),
  scale: 10}).filter(ee.Filter.gt('farmed_seen_ha', 0)).map(function (f) {
  var seen = ee.Number(f.get('farmed_seen_ha'));
  return f.set({
    not_farmed_pct: ee.Number(f.get('not_farmed_ha')).divide(seen).multiply(100),
    pattern_ratio: ee.Number(f.get('contrast_target')).divide(ee.Number(f.get('contrast_base')))
  });
});

Map.centerObject(AOI, 13);
var pal = {min: 0.1, max: 0.8, palette: ['ffffe5', 'addd8e', '238443', '004529']};
Map.addLayer(base.clip(AOI), pal, 'Peak NDVI, baseline median', false);
Map.addLayer(target.clip(AOI), pal, 'Peak NDVI, target');
Map.addLayer(cls.selfMask(), {min: 1, max: 3, palette: ['4daf4a', 'ff9f1c', 'c0392b']}, 'Field classes');
print('Units (worst first)', table.sort('not_farmed_pct', false).limit(30));
print('Mean pattern ratio', table.aggregate_mean('pattern_ratio'));

if (EXPORT) {
  Export.table.toDrive({collection: table, description: 'fallowcheck_units', fileFormat: 'GeoJSON'});
  Export.image.toDrive({image: cls.toByte(), description: 'fallowcheck_classes', region: AOI, scale: 10,
    maxPixels: 1e9});
}
