/**
 * Drought Check for the Google Earth Engine Code Editor.
 *
 * Part 1, drought: SPI (gamma) per pixel from CHIRPS monthly rainfall, the latest drought
 *   class map, months in the current drought spell, and charts of area-mean SPI and the
 *   share of the area in drought. (SPEI is in the Python and QGIS versions only.)
 * Part 2, greenness link: MODIS (MOD13A2, NASA) NDVI standardised anomaly vs SPI per
 *   ESA WorldCover class: correlation, a target-month diagnosis (drought-linked browning,
 *   browning without drought, holding up in drought), and "unexplained" browning over the
 *   recent months, the land change candidates.
 *
 * Same method and thresholds as the Python package (droughtcheck/), with two differences:
 *   - the gamma fit uses Thom's approximation, as the built-in Python engine does, but
 *     there is no climate-indices engine here;
 *   - the NDVI anomaly is computed here from MODIS (1 km, 2001-2020 baseline) instead of
 *     DE Africa's Landsat/Sentinel-2 product.
 * Paste into code.earthengine.google.com and press Run. Edit CONFIG first.
 */

var CONFIG = {
  aoi: ee.Geometry.Rectangle([35.82, -0.75, 36.81, 0.0]),   // Nakuru, Kenya (DE Africa tile x217y076)
  calibration: [1991, 2020],
  firstYear: 1981,
  scale: 3,                       // SPI scale (months) for maps, charts and events
  showFrom: '2015-01-01',         // charts start here
  threshold: -1.0,                // drought threshold (McKee moderate drought)
  latestMonth: null,              // 'YYYY-MM'; null = last complete CHIRPS month
  // greenness link
  greenness: true,
  ndviBaseline: [2001, 2020],
  linkFrom: '2017-01-01',
  lag: 1,                         // months NDVI lags SPI (Python demo: 0 for grass/crops, 1 for trees/shrubs)
  recentMonths: 12,
  exportFolder: 'droughtcheck'
};

// ------------------------------------------------------------------ monthly rainfall
var CHIRPS = ee.ImageCollection('UCSB-CHG/CHIRPS/PENTAD');
var START = ee.Date.fromYMD(CONFIG.firstYear, 1, 1);

function monthIndex(date) { return ee.Date(date).difference(START, 'month').round(); }

var lastChirps = ee.Date(CHIRPS.aggregate_max('system:time_start'));
// a month counts only when all six pentads are in
var nMonths = lastChirps.advance(5, 'day').difference(START, 'month').floor();

function monthlyRain(i) {
  i = ee.Number(i);
  var d0 = START.advance(i, 'month');
  return CHIRPS.filterDate(d0, d0.advance(1, 'month')).sum().rename('p')
    .set('idx', i, 'system:time_start', d0.millis(), 'month', d0.get('month'), 'year', d0.get('year'));
}
var monthly = ee.ImageCollection(ee.List.sequence(0, nMonths.subtract(1)).map(monthlyRain));

function accum(i, scale) {
  i = ee.Number(i);
  return monthly.filter(ee.Filter.rangeContains('idx', i.subtract(scale - 1), i)).sum()
    .rename('acc').set('idx', i, 'system:time_start', START.advance(i, 'month').millis());
}

// ------------------------------------------------------------------ gamma SPI
// ee's gammainc argument order is checked at run time: P(a=2, x=1) = 0.264.
var leftIsShape = ee.Number(2).gammainc(1).lt(0.5);
function regGammaP(shape, x) {
  return ee.Image(ee.Algorithms.If(leftIsShape, shape.gammainc(x), x.gammainc(shape)));
}
function normInv(p) {   // inverse standard normal via erfInv, clipped like climate-indices (+/-3.09)
  return p.clamp(1e-7, 1 - 1e-7).multiply(2).subtract(1).erfInv().multiply(Math.SQRT2).clamp(-3.09, 3.09);
}

// gamma parameters (Thom 1958) and probability of zero for each calendar month
function gammaParams(month, scale) {
  var years = ee.List.sequence(CONFIG.calibration[0], CONFIG.calibration[1]);
  var accs = ee.ImageCollection(years.map(function (y) {
    var i = monthIndex(ee.Date.fromYMD(y, month, 1));
    return accum(i, scale);
  }));
  var n = accs.count();
  var pos = accs.map(function (im) { return im.updateMask(im.gt(0)); });
  var q = n.subtract(pos.count()).divide(n);
  var mean = pos.mean();
  var A = mean.log().subtract(pos.map(function (im) { return im.log(); }).mean());
  var alpha = A.multiply(4 / 3).add(1).sqrt().add(1).divide(A.multiply(4));
  var beta = mean.divide(alpha);
  return ee.Image.cat([alpha.rename('alpha'), beta.rename('beta'), q.unmask(0).rename('q')]);
}
var PARAMS = {};
function params(month, scale) {
  var k = month + '_' + scale;
  if (!PARAMS[k]) PARAMS[k] = gammaParams(month, scale);
  return PARAMS[k];
}

var PARAM_LISTS = {};
function paramList(scale) {   // the 12 calendar-month parameter images, built once per scale
  if (!PARAM_LISTS[scale]) {
    var l = [];
    for (var k = 1; k <= 12; k++) l.push(params(k, scale));
    PARAM_LISTS[scale] = ee.List(l);
  }
  return PARAM_LISTS[scale];
}

function spiAt(i, scale) {
  i = ee.Number(i);
  var d = START.advance(i, 'month');
  var acc = accum(i, scale);
  var P = ee.Image(paramList(scale).get(ee.Number(d.get('month')).subtract(1)));
  var g = regGammaP(P.select('alpha'), acc.divide(P.select('beta')).max(0));
  var p = P.select('q').add(ee.Image(1).subtract(P.select('q')).multiply(g.where(acc.lte(0), 0)));
  return normInv(p).rename('spi').set('idx', i, 'system:time_start', d.millis());
}

function spiCollection(fromDate, scale) {
  var i0 = monthIndex(fromDate);
  return ee.ImageCollection(ee.List.sequence(i0, nMonths.subtract(1)).map(function (i) { return spiAt(i, scale); }));
}

// ------------------------------------------------------------------ drought maps
var latestIdx = CONFIG.latestMonth ? monthIndex(ee.Date(CONFIG.latestMonth + '-01')) : nMonths.subtract(1);
var spiLatest = spiAt(latestIdx, CONFIG.scale).clip(CONFIG.aoi);
var cls = ee.Image(0)
  .where(spiLatest.lte(-1), -1).where(spiLatest.lte(-1.5), -2).where(spiLatest.lte(-2), -3)
  .where(spiLatest.gt(1), 1).where(spiLatest.gt(1.5), 2).where(spiLatest.gt(2), 3)
  .updateMask(spiLatest.mask()).rename('class').clip(CONFIG.aoi);

// months in the current drought spell (walk back over the last 24 months)
var recentSpi = ee.ImageCollection(ee.List.sequence(latestIdx.subtract(23), latestIdx)
  .map(function (i) { return spiAt(i, CONFIG.scale); })).sort('idx', false);
var currentRun = ee.Image(recentSpi.iterate(function (im, st) {
  st = ee.Image(st);
  var still = st.select('open');
  var dry = ee.Image(im).lt(CONFIG.threshold);
  return ee.Image.cat([st.select('run').add(still.and(dry)), still.and(dry)]).rename(['run', 'open']);
}, ee.Image.cat([ee.Image(0), ee.Image(1)]).rename(['run', 'open']))).select('run').clip(CONFIG.aoi);

var CLS_PALETTE = ['7f1d12', 'c0392b', 'ec835a', 'f0efec', '86b6ef', '2a78d6', '184f95'];
Map.centerObject(CONFIG.aoi, 9);
Map.addLayer(cls, {min: -3, max: 3, palette: CLS_PALETTE}, 'Drought class (SPI-' + CONFIG.scale + ')');
Map.addLayer(spiLatest, {min: -2.5, max: 2.5, palette: ['7f1d12', 'c0392b', 'f0efec', '2a78d6', '184f95']},
             'SPI-' + CONFIG.scale, false);
Map.addLayer(currentRun.selfMask(), {min: 1, max: 12, palette: ['fde0c5', 'ec835a', '7f1d12']},
             'Months in current drought spell', false);
var latestLabel = START.advance(latestIdx, 'month').format('YYYY-MM');
latestLabel.evaluate(function (s) { print('Latest month:', s); });

// charts: area-mean SPI and % area in drought
var spiSeries = spiCollection(CONFIG.showFrom, CONFIG.scale).map(function (im) {
  return im.addBands(im.lte(-1).multiply(100).rename('pct_moderate'))
           .addBands(im.lte(-1.5).multiply(100).rename('pct_severe'))
           .addBands(im.lte(-2).multiply(100).rename('pct_extreme'));
});
print(ui.Chart.image.series(spiSeries.select('spi'), CONFIG.aoi, ee.Reducer.mean(), 5566)
  .setChartType('ColumnChart')
  .setOptions({title: 'Area-mean SPI-' + CONFIG.scale + ' (mean of pixel SPI)', legend: {position: 'none'},
               colors: ['2a78d6'], vAxis: {viewWindow: {min: -3, max: 3}}}));
print(ui.Chart.image.series(spiSeries.select(['pct_moderate', 'pct_severe', 'pct_extreme']), CONFIG.aoi,
                            ee.Reducer.mean(), 5566)
  .setChartType('AreaChart')
  .setOptions({title: 'Share of area in drought (%)', colors: ['ec835a', 'c0392b', '7f1d12'],
               vAxis: {viewWindow: {min: 0, max: 100}}}));

// ------------------------------------------------------------------ greenness link
if (CONFIG.greenness) {
  var MOD = ee.ImageCollection('MODIS/061/MOD13A2').map(function (im) {
    return im.select('NDVI').updateMask(im.select('SummaryQA').lte(1));   // good or marginal pixels
  });
  function modisMonth(y, m) {
    var d0 = ee.Date.fromYMD(y, m, 1);
    return MOD.filterDate(d0, d0.advance(1, 'month')).mean().multiply(0.0001).rename('ndvi');
  }
  // per calendar month baseline mean and sd
  var BASE = ee.List.sequence(1, 12).map(function (m) {
    var ims = ee.ImageCollection(ee.List.sequence(CONFIG.ndviBaseline[0], CONFIG.ndviBaseline[1])
      .map(function (y) { return modisMonth(y, m); }));
    return ee.Image.cat([ims.mean().rename('mu'), ims.reduce(ee.Reducer.stdDev()).rename('sd')]);
  });
  var linkStart = monthIndex(CONFIG.linkFrom);
  var pairs = ee.ImageCollection(ee.List.sequence(linkStart, latestIdx).map(function (i) {
    i = ee.Number(i);
    var d = START.advance(i, 'month');
    var b = ee.Image(BASE.get(ee.Number(d.get('month')).subtract(1)));
    var anom = modisMonth(d.get('year'), d.get('month')).subtract(b.select('mu')).divide(b.select('sd'))
      .clamp(-4, 4).rename('ndvi_anom');
    var spi = spiAt(i.subtract(CONFIG.lag), CONFIG.scale).rename('spi');
    return anom.addBands(spi).set('idx', i, 'system:time_start', d.millis());
  }));
  var recent0 = latestIdx.subtract(CONFIG.recentMonths - 1);
  var baseline = pairs.filter(ee.Filter.lt('idx', recent0));
  var recent = pairs.filter(ee.Filter.gte('idx', recent0));

  var r = baseline.select(['spi', 'ndvi_anom']).reduce(ee.Reducer.pearsonsCorrelation()).select('correlation');
  var fit = baseline.select(['spi', 'ndvi_anom']).reduce(ee.Reducer.linearFit());   // offset, scale
  var unexplained = recent.map(function (im) {
    return im.select('ndvi_anom').subtract(fit.select('offset').add(fit.select('scale').multiply(im.select('spi'))));
  }).mean().rename('unexplained');
  var diag = function (im) {
    var n = im.select('ndvi_anom'), z = im.select('spi');
    return ee.Image(0)
      .where(n.lte(-1).and(z.lte(-1)), 1)
      .where(n.lte(-1).and(z.gt(-0.5)), 2)
      .where(z.lte(-1).and(n.gte(-0.5)), 3)
      .where(n.lte(-1).and(z.gt(-1)).and(z.lte(-0.5)), 4)
      .updateMask(n.mask().and(z.mask())).rename('diagnosis');
  };
  var target = ee.Image(pairs.filter(ee.Filter.eq('idx', latestIdx)).first());
  var diagnosis = diag(target);
  var nonClimatic = recent.map(function (im) { return diag(im).eq(2); }).sum().rename('nonclimatic_months');
  var WC = ee.ImageCollection('ESA/WorldCover/v200').first().rename('lc');
  var skip = WC.eq(50).or(WC.eq(70)).or(WC.eq(80));
  var landChange = nonClimatic.gte(3).and(unexplained.lte(-1)).updateMask(skip.not()).selfMask();

  Map.addLayer(diagnosis.updateMask(skip.not()).clip(CONFIG.aoi),
               {min: 0, max: 4, palette: ['e4e3df', 'c0392b', '7b3fa0', '2a78d6', 'eb9f6c']},
               'Diagnosis: 1 drought browning, 2 browning w/o drought, 3 holding up, 4 mild');
  Map.addLayer(unexplained.clip(CONFIG.aoi), {min: -2, max: 2, palette: ['b2182b', 'f7f7f7', '2166ac']},
               'Unexplained greenness (recent months)', false);
  Map.addLayer(r.clip(CONFIG.aoi), {min: -0.2, max: 0.8, palette: ['440154', '21918c', 'fde725']},
               'Rain sensitivity (r)', false);
  Map.addLayer(landChange.clip(CONFIG.aoi), {palette: ['ff00ff']}, 'Land change candidates');

  // per class: mean NDVI anomaly and SPI over time, for the classes in the AOI
  var classes = {10: 'Tree cover', 20: 'Shrubland', 30: 'Grassland', 40: 'Cropland'};
  Object.keys(classes).forEach(function (c) {
    var m = WC.eq(parseInt(c, 10));
    print(ui.Chart.image.series(pairs.map(function (im) { return im.updateMask(m); }), CONFIG.aoi,
                                ee.Reducer.mean(), 1000)
      .setOptions({title: classes[c] + ': NDVI anomaly vs SPI-' + CONFIG.scale + ' (lag ' + CONFIG.lag + ')',
                   series: {0: {color: '0b0b0b'}, 1: {color: 'c0392b', type: 'bars'}}, seriesType: 'line'}));
  });
  print('Class summary (target month)', ee.Image.cat([r.rename('r'), unexplained, target.select('ndvi_anom'),
    target.select('spi'), landChange.unmask(0).rename('landchange'), WC])
    .reduceRegion({reducer: ee.Reducer.mean().group({groupField: 5, groupName: 'class'}),
                   geometry: CONFIG.aoi, scale: 1000, maxPixels: 1e9, bestEffort: true}));

  Export.image.toDrive({image: ee.Image.cat([r.rename('r'), unexplained, nonClimatic, diagnosis,
                                             landChange.unmask(0).rename('landchange')]).toFloat(),
                        description: 'greenness_layers', folder: CONFIG.exportFolder,
                        region: CONFIG.aoi, scale: 1000, maxPixels: 1e9});
}

Export.image.toDrive({image: ee.Image.cat([spiLatest, cls, currentRun.rename('current_run')]).toFloat(),
                      description: 'drought_latest', folder: CONFIG.exportFolder,
                      region: CONFIG.aoi, scale: 5566, maxPixels: 1e9});
