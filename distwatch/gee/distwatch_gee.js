/**
 * DIST Watch for Google Earth Engine: new vegetation loss since your last run.
 *
 * Earth Engine does not carry NASA OPERA DIST-ALERT, so this script rebuilds
 * a simplified alert from the same source data, NASA HLS (Landsat + Sentinel-2,
 * 30 m), which is in the Earth Engine catalog:
 *   - baseline: median NDVI of the same season in the 3 previous years;
 *   - an observation is anomalous when NDVI has dropped by at least MIN_LOSS %
 *     of the baseline (DIST-ALERT uses vegetation fraction, not NDVI);
 *   - a pixel is "confirmed" after MIN_ANOMALOUS_OBS anomalous clear views.
 * It then removes everything reported on earlier runs (a state image you
 * export each run) and summarises the rest per area.
 *
 * This is an approximation of DIST-ALERT, not the product. For the real alerts
 * use the Python tool or the QGIS script. Untested in the Code Editor: it was
 * written where Earth Engine was not available.
 *
 * How to use
 *   1. Set AREAS to your polygons (an asset path) or draw geometries.
 *   2. First run: leave PREVIOUS_STATE = null. Run, then start the
 *      "distwatch_state" export task in the Tasks tab.
 *   3. Next run: set PREVIOUS_STATE to the asset that export made and move
 *      END_DATE forward. Only loss not reported before is shown as new.
 */

// ---------------------------------------------------------------- settings
var AREAS = null;              // e.g. 'projects/your-project/assets/cocoa_farms'; null = demo boxes in Ghana
var NAME_FIELD = 'name';
var END_DATE = '2025-03-15';   // the "as of" date of this run
var WINDOW_DAYS = 120;         // look this far back for anomalous observations
var MIN_LOSS = 50;             // % NDVI drop against the baseline
var MIN_ANOMALOUS_OBS = 2;     // clear anomalous views needed to confirm
var MIN_BASELINE_NDVI = 0.5;   // only pixels that were well vegetated
var MIN_PATCH_PX = 3;          // smallest patch, 30 m pixels
var USE_FOREST_MASK = true;    // keep only loss inside JRC Global Forest Cover 2020 (EUDR baseline)
var PREVIOUS_STATE = null;     // e.g. 'projects/your-project/assets/distwatch_state_run1'
var RUN_NUMBER = 1;            // stored in the state so you can tell runs apart
var EXPORT_FOLDER = 'distwatch';
var ASSET_ROOT = 'projects/your-project/assets/'; // where the state image is saved

// ---------------------------------------------------------------- inputs
var demoAreas = ee.FeatureCollection([
  ee.Feature(ee.Geometry.Rectangle([-2.55, 6.26, -2.45, 6.31]), {name: 'Forest block'}),
  ee.Feature(ee.Geometry.Rectangle([-2.58, 6.20, -2.54, 6.23]), {name: 'Cooperative A'}),
  ee.Feature(ee.Geometry.Rectangle([-2.45, 6.20, -2.40, 6.23]), {name: 'Cooperative B'})
]);
var areas = AREAS ? ee.FeatureCollection(AREAS) : demoAreas;
var region = areas.geometry().bounds().buffer(500);

var end = ee.Date(END_DATE);
var start = end.advance(-WINDOW_DAYS, 'day');

// Fmask bits 1 cloud, 2 adjacent to cloud, 3 shadow, 4 snow/ice, 5 water.
function clearMask(img) {
  var fm = img.select('Fmask');
  var bad = fm.bitwiseAnd(1 << 1).or(fm.bitwiseAnd(1 << 2)).or(fm.bitwiseAnd(1 << 3))
    .or(fm.bitwiseAnd(1 << 4)).or(fm.bitwiseAnd(1 << 5));
  return bad.eq(0);
}

function ndviL30(img) {
  return img.normalizedDifference(['B5', 'B4']).rename('ndvi').updateMask(clearMask(img))
    .copyProperties(img, ['system:time_start']);
}

function ndviS30(img) {
  return img.normalizedDifference(['B8A', 'B4']).rename('ndvi').updateMask(clearMask(img))
    .copyProperties(img, ['system:time_start']);
}

function hlsNdvi(s, e) {
  var l = ee.ImageCollection('NASA/HLS/HLSL30/v002').filterBounds(region).filterDate(s, e).map(ndviL30);
  var t = ee.ImageCollection('NASA/HLS/HLSS30/v002').filterBounds(region).filterDate(s, e).map(ndviS30);
  return l.merge(t).map(function (i) { return ee.Image(i).clip(region); });
}

// Baseline: the same season in each of the three previous years, padded by 30 days.
var baselineCol = ee.ImageCollection(ee.List([1, 2, 3]).iterate(function (k, acc) {
  var s = start.advance(ee.Number(k).multiply(-1), 'year').advance(-30, 'day');
  var e = end.advance(ee.Number(k).multiply(-1), 'year').advance(30, 'day');
  return ee.ImageCollection(acc).merge(hlsNdvi(s, e));
}, ee.ImageCollection([])));
var baseline = baselineCol.median().rename('base');

// Per observation in the window: % drop, anomalous flag, and day of year 2020-based like DIST-DATE.
var epoch = ee.Date('2020-12-31');
var obs = hlsNdvi(start, end).map(function (img) {
  var drop = baseline.subtract(img).divide(baseline).multiply(100).rename('loss');
  var anomalous = drop.gte(MIN_LOSS).rename('anom');
  var day = ee.Image.constant(ee.Date(img.get('system:time_start')).difference(epoch, 'day')).toInt16()
    .rename('day').updateMask(anomalous);
  return drop.addBands(anomalous).addBands(day);
});

var count = obs.select('anom').sum().rename('n_anom');
var maxLoss = obs.select('loss').max().rename('max_loss');
var firstDay = obs.select('day').min().rename('first_day');

var qualifying = count.gte(MIN_ANOMALOUS_OBS).and(baseline.gte(MIN_BASELINE_NDVI));
if (USE_FOREST_MASK) {
  // JRC GFC2020: 1 = forest on 31 Dec 2020. Check the collection id in the catalog if this fails.
  var forest = ee.ImageCollection('JRC/GFC2020/V2').mosaic().select('Map').eq(1);
  qualifying = qualifying.and(forest.unmask(0));
}
var patchPx = qualifying.selfMask().connectedPixelCount(256, true);
qualifying = qualifying.and(patchPx.gte(MIN_PATCH_PX)).unmask(0);

// ---------------------------------------------------------------- new since last run
var reported = PREVIOUS_STATE ? ee.Image(PREVIOUS_STATE).select('reported_run').unmask(0)
                              : ee.Image.constant(0).rename('reported_run');
var isNew = qualifying.and(reported.eq(0)).rename('new');
var newState = reported.where(isNew, RUN_NUMBER).rename('reported_run').toUint16();

// ---------------------------------------------------------------- per-area summary
var haImg = ee.Image.pixelArea().divide(1e4);
var stack = haImg.updateMask(isNew).rename('new_loss_ha')
  .addBands(haImg.updateMask(qualifying).rename('total_loss_ha'))
  .addBands(haImg.rename('area_ha'));
var summary = stack.reduceRegions({collection: areas, reducer: ee.Reducer.sum(), scale: 30})
  .map(function (f) {
    var newHa = ee.Number(f.get('new_loss_ha'));
    return f.set({
      new_loss_pct_of_area: newHa.divide(ee.Number(f.get('area_ha'))).multiply(100),
      flag: ee.Algorithms.If(newHa.gt(0), 'NEW LOSS', ''),
      run: RUN_NUMBER, as_of: END_DATE
    });
  });

var patches = isNew.selfMask().addBands(maxLoss).addBands(firstDay).reduceToVectors({
  geometry: region, scale: 30, geometryType: 'polygon', eightConnected: true,
  labelProperty: 'new', reducer: ee.Reducer.mean(), maxPixels: 1e9
}).map(function (f) {
  return f.set('area_ha', f.geometry().area(1).divide(1e4),
               'first_detected', epoch.advance(ee.Number(f.get('first_day')).round(), 'day').format('YYYY-MM-dd'));
});

// ---------------------------------------------------------------- display and exports
Map.centerObject(areas, 12);
Map.addLayer(baseline, {min: 0, max: 0.9, palette: ['white', 'green']}, 'Baseline NDVI', false);
Map.addLayer(qualifying.selfMask(), {palette: ['808080']}, 'Loss reported earlier or now');
Map.addLayer(isNew.selfMask(), {palette: ['d62728']}, 'NEW loss this run');
Map.addLayer(ee.Image().byte().paint(areas, 1, 2), {palette: ['1f5f8b']}, 'Areas');

print('Window', start.format('YYYY-MM-dd'), 'to', END_DATE);
print('HLS observations in window', obs.size());
print('Per-area summary', summary.select(['.*_ha', 'new_loss_pct_of_area', 'flag', NAME_FIELD]));
print('New patches (first 50)', patches.limit(50));

Export.table.toDrive({collection: summary, description: 'distwatch_area_summary_run' + RUN_NUMBER,
                      folder: EXPORT_FOLDER, fileFormat: 'CSV'});
Export.table.toDrive({collection: patches, description: 'distwatch_new_loss_run' + RUN_NUMBER,
                      folder: EXPORT_FOLDER, fileFormat: 'GeoJSON'});
Export.image.toAsset({image: newState.clip(region), description: 'distwatch_state',
                      assetId: ASSET_ROOT + 'distwatch_state_run' + RUN_NUMBER, region: region, scale: 30,
                      maxPixels: 1e10, pyramidingPolicy: {reported_run: 'max'}});
