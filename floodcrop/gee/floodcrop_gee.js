/**** Flooded Cropland Calculator — Google Earth Engine Code Editor script ****
 *
 * Hectares of cropland newly under water per area, for one flood event.
 * Paste into https://code.earthengine.google.com, edit SETTINGS, press Run.
 *
 * Water sources:
 *   'S1'   Sentinel-1 GRD VV: threshold (Otsu) OR backscatter drop vs a
 *          same-orbit pre-event median (stand-in for OPERA DSWx-S1)
 *   'HLS'  NASA HLS v002 (Landsat + Sentinel-2) with the five DSWx-HLS / DSWE
 *          tests and the Fmask cloud mask (stand-in for OPERA DSWx-HLS)
 *   'DSWX' an OPERA DSWx WTR ImageCollection you uploaded as an asset
 * Cropland: ESA WorldCover v200 class 40, or your own 0/1 asset (e.g. the
 *   Digital Earth Africa crop mask). Permanent water: JRC GSW occurrence.
 * Areas: FAO GAUL level 2 by default, or any FeatureCollection asset (FEWS
 *   NET livelihood zones uploaded as a shapefile, geoBoundaries, ...).
 *
 * Same rules as the Python/QGIS versions (floodcrop/core.py); NOT run in real
 * Earth Engine by its author — see README "What is untested".
 */

// ------------------------------------------------------------- SETTINGS
var SOURCE = 'S1';                 // 'S1' | 'HLS' | 'DSWX'
var EVENT_DATE = '2024-05-01';     // flood date; event window = EVENT_DATE .. + EVENT_DAYS
var EVENT_DAYS = 12;
var BASELINE_START = '2024-02-01'; // pre-event window (same season if you can)
var BASELINE_END = '2024-03-15';
// Areas: default = FAO GAUL 2015 level-2 units (old Kenyan districts) touching the Kano Plains
var AOI = ee.Geometry.Rectangle([34.70, -0.42, 35.20, -0.05]);
var ZONES = ee.FeatureCollection('FAO/GAUL/2015/level2')
  .filter(ee.Filter.eq('ADM0_NAME', 'Kenya')).filterBounds(AOI)
  .map(function (f) { return f.intersection(AOI, 10); });  // clip to the AOI so areas match what is mapped
var NAME_FIELD = 'ADM2_NAME';
var CROPLAND_ASSET = null;         // e.g. 'users/you/deafrica_cropmask' (1 = crop); null = WorldCover class 40
var DSWX_ASSET = null;             // SOURCE 'DSWX': ImageCollection of WTR layers with system:time_start
var PERMANENT_OCCURRENCE = 80;     // JRC GSW occurrence (%) treated as permanent water
var SCALE = 20;                    // metres for the area sums
// Sentinel-1
var S1_THRESHOLD = null;           // VV dB; null = Otsu on the event scene, clamped to [-22, -15]
var S1_DROP_DB = 3;                // backscatter drop vs baseline that counts as new water ...
var S1_LOOSE_DB = -14;             // ... when the event VV is also below this
var S1_SMOOTH_PX = 2;              // square kernel radius in pixels (2 => 5x5 mean, as in Python)
// HLS
var HLS_SCALE = 10000;             // GEE serves HLS as 0-1 reflectance; DSWx thresholds use 0-10000

// ------------------------------------------------------------- constants
var DRY = 0, WATER = 1, PARTIAL = 2, NODATA = 255;
var evStart = ee.Date(EVENT_DATE), evEnd = evStart.advance(EVENT_DAYS, 'day');

// ------------------------------------------------------------- helpers
// Otsu threshold from a histogram dictionary (standard GEE recipe)
function otsu(histogram) {
  var counts = ee.Array(ee.Dictionary(histogram).get('histogram'));
  var means = ee.Array(ee.Dictionary(histogram).get('bucketMeans'));
  var size = means.length().get([0]);
  var total = counts.reduce(ee.Reducer.sum(), [0]).get([0]);
  var sum = means.multiply(counts).reduce(ee.Reducer.sum(), [0]).get([0]);
  var mean = sum.divide(total);
  var indices = ee.List.sequence(1, size);
  var bss = indices.map(function (i) {
    var aCounts = counts.slice(0, 0, i);
    var aCount = aCounts.reduce(ee.Reducer.sum(), [0]).get([0]);
    var aMeans = means.slice(0, 0, i);
    var aMean = aMeans.multiply(aCounts).reduce(ee.Reducer.sum(), [0]).get([0]).divide(aCount);
    var bCount = total.subtract(aCount);
    var bMean = sum.subtract(aCount.multiply(aMean)).divide(bCount);
    return aCount.multiply(aMean.subtract(mean).pow(2)).add(bCount.multiply(bMean.subtract(mean).pow(2)));
  });
  return means.sort(bss).get([-1]);
}

// DSWx-HLS / DSWE diagnostic tests -> class (1 high, 2 moderate, 3/4 partial, 0 not water)
var T = {wigt: 0.124, awgt: 0, p1_mndwi: -0.44, p1_nir: 1500, p1_swir1: 900, p1_ndvi: 0.7,
         p2_mndwi: -0.5, p2_blue: 1000, p2_nir: 2500, p2_swir1: 3000, p2_swir2: 1000};
var HIGH = [1111, 10111, 11011, 11101, 11110, 11111];
var MOD = [111, 1011, 1101, 1110, 10011, 10101, 10110, 11001, 11010, 11100];
var PSW = [11000, 11, 101, 110, 1001, 1010, 1100, 10000, 10001, 10010, 10100];
function dswxTests(img) {  // img bands: blue green red nir swir1 swir2 on 0-10000
  var b = img.select('blue'), g = img.select('green'), r = img.select('red');
  var n = img.select('nir'), s1 = img.select('swir1'), s2 = img.select('swir2');
  var mndwi = g.subtract(s1).divide(g.add(s1));
  var ndvi = n.subtract(r).divide(n.add(r));
  var mbsrv = g.add(r), mbsrn = n.add(s1);
  var awesh = b.add(g.multiply(2.5)).subtract(mbsrn.multiply(1.5)).subtract(s2.multiply(0.25));
  var t1 = mndwi.gt(T.wigt);
  var t2 = mbsrv.gt(mbsrn);
  var t3 = awesh.gt(T.awgt);
  var t4 = mndwi.gt(T.p1_mndwi).and(s1.lt(T.p1_swir1)).and(n.lt(T.p1_nir)).and(ndvi.lt(T.p1_ndvi));
  var t5 = mndwi.gt(T.p2_mndwi).and(b.lt(T.p2_blue)).and(s1.lt(T.p2_swir1)).and(s2.lt(T.p2_swir2)).and(n.lt(T.p2_nir));
  var code = t1.add(t2.multiply(10)).add(t3.multiply(100)).add(t4.multiply(1000)).add(t5.multiply(10000));
  var water = code.remap(HIGH.concat(MOD), ee.List.repeat(1, HIGH.length + MOD.length), 0);
  var partial = code.remap(PSW, ee.List.repeat(1, PSW.length), 0);
  return ee.Image(DRY).where(partial, PARTIAL).where(water, WATER).toByte();
}

function hlsClasses(start, end) {
  var bandsL = ['B2', 'B3', 'B4', 'B5', 'B6', 'B7'], bandsS = ['B2', 'B3', 'B4', 'B8A', 'B11', 'B12'];
  var names = ['blue', 'green', 'red', 'nir', 'swir1', 'swir2'];
  function prep(bands) {
    return function (img) {
      var fm = img.select('Fmask');
      var bad = fm.bitwiseAnd(2).neq(0).or(fm.bitwiseAnd(4).neq(0)).or(fm.bitwiseAnd(8).neq(0)); // cloud, adjacent, shadow
      var cls = dswxTests(img.select(bands, names).multiply(HLS_SCALE));
      return cls.where(bad, NODATA).updateMask(img.select('B2').mask())
        .rename('cls').copyProperties(img, ['system:time_start']);
    };
  }
  var l = ee.ImageCollection('NASA/HLS/HLSL30/v002').filterBounds(AOI).filterDate(start, end).map(prep(bandsL));
  var s = ee.ImageCollection('NASA/HLS/HLSS30/v002').filterBounds(AOI).filterDate(start, end).map(prep(bandsS));
  return l.merge(s);
}

// Combine dates: water if water on any observed date (as core.combine 'any')
function combineAny(coll) {
  var c = coll.map(function (i) { return i.unmask(NODATA); });
  var nObs = c.map(function (i) { return i.neq(NODATA); }).sum();
  var nW = c.map(function (i) { return i.eq(WATER); }).sum();
  var nP = c.map(function (i) { return i.eq(PARTIAL); }).sum();
  return ee.Image(NODATA).where(nObs.gt(0), DRY).where(nP.gt(0), PARTIAL).where(nW.gt(0), WATER)
    .where(nObs.eq(0), NODATA).toByte();
}

// ------------------------------------------------------------- water
var eventCls, baseCls, info = {};
if (SOURCE === 'S1') {
  var s1 = ee.ImageCollection('COPERNICUS/S1_GRD').filterBounds(AOI)
    .filter(ee.Filter.eq('instrumentMode', 'IW'))
    .filter(ee.Filter.listContains('transmitterReceiverPolarisation', 'VV')).select('VV');
  var evImg = ee.Image(s1.filterDate(evStart, evEnd).sort('system:time_start').first());
  var orbit = evImg.get('relativeOrbitNumber_start');
  var evDay = ee.Date(evImg.get('system:time_start')).format('YYYY-MM-dd');
  // same orbit, same day = one pass (mosaic its slices)
  var evPass = s1.filterDate(evDay, ee.Date(evDay).advance(1, 'day'))
    .filter(ee.Filter.eq('relativeOrbitNumber_start', orbit)).mosaic();
  var base = s1.filterDate(BASELINE_START, BASELINE_END).filter(ee.Filter.eq('relativeOrbitNumber_start', orbit));
  var smooth = function (i) { return i.focalMean(S1_SMOOTH_PX, 'square', 'pixels'); };
  var ev = smooth(evPass);  // GEE S1_GRD is already in dB
  var blMed = smooth(base.median());
  var thr = S1_THRESHOLD !== null ? ee.Number(S1_THRESHOLD) : ee.Number(otsu(ev.reduceRegion({
    reducer: ee.Reducer.histogram(255, 0.1), geometry: AOI, scale: 40, maxPixels: 1e10, bestEffort: true
  }).get('VV'))).max(-22).min(-15);
  var evWater = ev.lt(thr).or(ev.subtract(blMed).lt(-S1_DROP_DB).and(ev.lt(S1_LOOSE_DB)));
  eventCls = ee.Image(DRY).where(evWater, WATER).updateMask(ev.mask()).unmask(NODATA).toByte();
  baseCls = combineAny(base.map(function (i) {
    var d = smooth(i);
    return ee.Image(DRY).where(d.lt(thr), WATER).updateMask(d.mask()).toByte();
  }));
  info = {orbit: orbit, eventDate: evDay, baselineScenes: base.size(), thresholdDb: thr};
} else if (SOURCE === 'HLS') {
  eventCls = combineAny(hlsClasses(evStart, evEnd));
  baseCls = combineAny(hlsClasses(BASELINE_START, BASELINE_END));
  info = {eventScenes: hlsClasses(evStart, evEnd).size(), baselineScenes: hlsClasses(BASELINE_START, BASELINE_END).size()};
} else {
  var dswx = ee.ImageCollection(DSWX_ASSET).filterBounds(AOI);
  var decode = function (i) {
    return ee.Image(NODATA).where(i.eq(0), DRY).where(i.eq(1), WATER).where(i.eq(2), PARTIAL)
      .where(i.eq(254), WATER).updateMask(i.mask()).toByte();
  };
  eventCls = combineAny(dswx.filterDate(evStart, evEnd).map(decode));
  baseCls = combineAny(dswx.filterDate(BASELINE_START, BASELINE_END).map(decode));
}

// ------------------------------------------------------------- flood
var permanent = ee.Image('JRC/GSW1_4/GlobalSurfaceWater').select('occurrence').gte(PERMANENT_OCCURRENCE).unmask(0);
var before = baseCls.eq(WATER).or(baseCls.eq(PARTIAL)).or(permanent);
var newWater = eventCls.eq(WATER).and(before.not());
var newPartial = eventCls.eq(PARTIAL).and(before.not());
var observed = eventCls.neq(NODATA);

var crop = CROPLAND_ASSET ? ee.Image(CROPLAND_ASSET).eq(1)
  : ee.ImageCollection('ESA/WorldCover/v200').first().eq(40);
crop = crop.unmask(0);

var ha = ee.Image.pixelArea().divide(1e4);
var stack = ee.Image.cat([
  ha.rename('zone_ha'),
  ha.updateMask(observed).rename('observed_ha'),
  ha.multiply(crop).rename('crop_ha'),
  ha.multiply(crop).updateMask(observed).rename('crop_observed_ha'),
  ha.multiply(crop).updateMask(newWater).rename('flooded_crop_ha'),
  ha.multiply(crop).updateMask(newPartial).rename('flooded_crop_partial_ha'),
  ha.updateMask(newWater).rename('flooded_all_ha')
]);
var table = stack.reduceRegions({collection: ZONES, reducer: ee.Reducer.sum(), scale: SCALE, tileScale: 4})
  .map(function (f) {
    var co = ee.Number(f.get('crop_observed_ha'));
    return f.set({
      zone: f.get(NAME_FIELD),
      flooded_crop_pct: ee.Number(f.get('flooded_crop_ha')).divide(co.max(1e-9)).multiply(100),
      crop_observed_pct: co.divide(ee.Number(f.get('crop_ha')).max(1e-9)).multiply(100)
    });
  }).sort('flooded_crop_ha', false);

// ------------------------------------------------------------- display
Map.centerObject(AOI, 10);
Map.addLayer(crop.selfMask(), {palette: ['#c9dba3']}, 'Cropland');
Map.addLayer(before.selfMask(), {palette: ['#2c5d8f']}, 'Water before event / permanent');
Map.addLayer(newWater.and(crop.not()).selfMask(), {palette: ['#86b9e0']}, 'New water, not cropland');
Map.addLayer(newPartial.and(crop).selfMask(), {palette: ['#f2a7c0']}, 'Partial water on cropland', false);
Map.addLayer(newWater.and(crop).selfMask(), {palette: ['#d6336c']}, 'Flooded cropland');
Map.addLayer(eventCls.eq(NODATA).selfMask(), {palette: ['#bdbdbd']}, 'Not observed', false);
Map.addLayer(ee.Image().paint(ZONES, 0, 1), {palette: ['#333333']}, 'Areas');
print('Run info', info);
print('Flooded cropland per area (ha)', table.select(['zone', 'flooded_crop_ha', 'flooded_crop_partial_ha',
  'flooded_crop_pct', 'crop_ha', 'crop_observed_pct', 'flooded_all_ha']));
print(ui.Chart.feature.byFeature(table.limit(15), 'zone', ['flooded_crop_ha', 'flooded_crop_partial_ha'])
  .setChartType('BarChart').setOptions({title: 'Flooded cropland (ha)', isStacked: true,
    colors: ['#d6336c', '#f2a7c0'], hAxis: {title: 'ha'}}));
Export.table.toDrive({collection: table, description: 'floodcrop_summary', fileFormat: 'CSV',
  selectors: ['zone', 'zone_ha', 'observed_ha', 'crop_ha', 'crop_observed_ha', 'crop_observed_pct',
              'flooded_crop_ha', 'flooded_crop_partial_ha', 'flooded_crop_pct', 'flooded_all_ha']});
