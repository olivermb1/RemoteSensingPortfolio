/**
 * ClassSpectra for Google Earth Engine (Code Editor JavaScript).
 *
 * Per-class spectral signatures (median and spread) from a multispectral
 * composite and a land cover map, with the same cleaning as the Python tool:
 * cloud masking, class-border erosion (skipped for thin/rare classes),
 * purity for 30 m images on 10 m maps, robust outlier trimming (MAD z-score),
 * then percentiles. Optional second map for a map-vs-map comparison.
 *
 * Paste into https://code.earthengine.google.com, edit SETTINGS, press Run.
 * Charts and tables appear in the Console; CSVs go to Tasks (Drive export).
 *
 * Same maths as classspectra/core.py. The pure-JS helpers below (no `ee`)
 * are unit-tested in Node: node gee/test_gee_helpers.js
 */

// ============================== SETTINGS ===================================
var SETTINGS = {
  // Area: [west, south, east, north] in degrees. Default: Nakuru, Kenya.
  bbox: [35.98, -0.42, 36.18, -0.20],
  start: '2024-01-15',
  end: '2024-03-01',
  // 's2'      Sentinel-2 L2A harmonized, 10 m, Cloud Score+ masked
  // 'hls_s30' NASA HLS S30 v002, 30 m, Fmask
  // 'hls_l30' NASA HLS L30 v002, 30 m, Fmask
  sensor: 's2',
  cloudScoreMin: 0.6,          // s2 only: Cloud Score+ cs threshold
  // 'worldcover2021' | 'worldcover2020' | 'dynamicworld' | 'io'
  map: 'worldcover2021',
  compareMap: 'worldcover2020', // second map, or null to skip the comparison
  erosion: 1,                   // pixels; 0 = off
  minPurity: 0.75,              // only used when the image is coarser than 10 m
  outlierZ: 3.5,                // robust z threshold; 0 = off
  minPixels: 30,
  tileScale: 4,
  exportCsv: true,              // queue Drive exports in the Tasks tab
  exportPrefix: 'classspectra_nakuru'
};

// ============================ LEGENDS & SENSORS ============================
var LEGENDS = {
  worldcover: {
    10: ['Tree cover', '#006400'], 20: ['Shrubland', '#ffbb22'], 30: ['Grassland', '#ffff4c'],
    40: ['Cropland', '#f096ff'], 50: ['Built-up', '#fa0000'], 60: ['Bare / sparse vegetation', '#b4b4b4'],
    70: ['Snow and ice', '#f0f0f0'], 80: ['Permanent water bodies', '#0064c8'],
    90: ['Herbaceous wetland', '#0096a0'], 95: ['Mangroves', '#00cf75'], 100: ['Moss and lichen', '#fae6a0']
  },
  io: {
    1: ['Water', '#419bdf'], 2: ['Trees', '#397d49'], 4: ['Flooded vegetation', '#7a87c6'],
    5: ['Crops', '#e49635'], 7: ['Built area', '#c4281b'], 8: ['Bare ground', '#a59b8f'],
    9: ['Snow/ice', '#a8ebff'], 10: ['Clouds', '#616161'], 11: ['Rangeland', '#e3e2c3']
  },
  dynamicworld: {
    0: ['Water', '#419bdf'], 1: ['Trees', '#397d49'], 2: ['Grass', '#88b053'],
    3: ['Flooded vegetation', '#7a87c6'], 4: ['Crops', '#e49635'], 5: ['Shrub and scrub', '#dfc35a'],
    6: ['Built', '#c4281b'], 7: ['Bare', '#a59b8f'], 8: ['Snow and ice', '#b39fe1']
  },
  broad: {
    1: ['Water', '#419bdf'], 2: ['Trees', '#397d49'], 3: ['Grass', '#c9c94d'], 4: ['Shrub', '#dfa35a'],
    5: ['Crops', '#d65fd6'], 6: ['Built', '#c4281b'], 7: ['Bare', '#a59b8f'], 8: ['Wetland', '#0096a0']
  }
};

// Native class value -> broad class code, for comparing two different maps.
var BROAD = {
  worldcover: {10: 2, 20: 4, 30: 3, 40: 5, 50: 6, 60: 7, 80: 1, 90: 8, 95: 2},
  io: {1: 1, 2: 2, 4: 8, 5: 5, 7: 6, 8: 7, 11: 3},
  dynamicworld: {0: 1, 1: 2, 2: 3, 3: 8, 4: 5, 5: 4, 6: 6, 7: 7}
};

var SENSORS = {
  s2: {
    bands: ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12'],
    wavelengths: [490, 560, 665, 705, 740, 783, 842, 865, 1610, 2190],
    red: 'B4', nir: 'B8', scale: 10
  },
  hls_s30: {
    bands: ['B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12'],
    wavelengths: [443, 490, 560, 665, 705, 740, 783, 842, 865, 1610, 2190],
    red: 'B4', nir: 'B8A', scale: 30
  },
  hls_l30: {
    bands: ['B1', 'B2', 'B3', 'B4', 'B5', 'B6', 'B7'],
    wavelengths: [443, 482, 561, 655, 865, 1609, 2201],
    red: 'B4', nir: 'B5', scale: 30
  }
};

// ================== PURE JS HELPERS (no ee; tested in Node) ================

function className(legend, v) {
  var e = (LEGENDS[legend] || {})[v];
  return e ? e[0] : 'Class ' + v;
}

function classColour(legend, v) {
  var e = (LEGENDS[legend] || {})[v];
  return e ? e[1] : '#555555';
}

/** Turn an Earth Engine grouped-reducer result ({groups: [...]}) into {class: {key: value}}. */
function groupsToMap(groups) {
  var out = {};
  (groups || []).forEach(function (g) {
    var c = g['class'];
    out[c] = {};
    Object.keys(g).forEach(function (k) { if (k !== 'class') out[c][k] = g[k]; });
  });
  return out;
}

/** Cholesky factor of a symmetric positive-definite matrix (array of rows). */
function cholesky(a) {
  var n = a.length, L = [];
  for (var i = 0; i < n; i++) { L.push([]); for (var j = 0; j < n; j++) L[i].push(0); }
  for (i = 0; i < n; i++) {
    for (j = 0; j <= i; j++) {
      var s = a[i][j];
      for (var k = 0; k < j; k++) s -= L[i][k] * L[j][k];
      if (i === j) {
        if (s <= 0) throw new Error('matrix not positive definite');
        L[i][i] = Math.sqrt(s);
      } else {
        L[i][j] = s / L[j][j];
      }
    }
  }
  return L;
}

function logDet(a) {
  var L = cholesky(a), s = 0;
  for (var i = 0; i < L.length; i++) s += Math.log(L[i][i]);
  return 2 * s;
}

/** Solve a x = b for symmetric positive-definite a. */
function solveSPD(a, b) {
  var L = cholesky(a), n = b.length, y = [], x = [], i, k, s;
  for (i = 0; i < n; i++) {
    s = b[i];
    for (k = 0; k < i; k++) s -= L[i][k] * y[k];
    y.push(s / L[i][i]);
  }
  for (i = n - 1; i >= 0; i--) {
    s = y[i];
    for (k = i + 1; k < n; k++) s -= L[k][i] * x[k];
    x[i] = s / L[i][i];
  }
  return x;
}

function addRidge(c, eps) {
  return c.map(function (row, i) {
    return row.map(function (v, j) { return i === j ? v + eps : v; });
  });
}

/** Jeffries-Matusita distance (0..2) between two Gaussian classes. */
function jeffriesMatusita(meanA, covA, meanB, covB) {
  var ca = addRidge(covA, 1e-6), cb = addRidge(covB, 1e-6);
  var cm = ca.map(function (row, i) { return row.map(function (v, j) { return (v + cb[i][j]) / 2; }); });
  var d = meanA.map(function (v, i) { return v - meanB[i]; });
  var x = solveSPD(cm, d);
  var t1 = d.reduce(function (s, v, i) { return s + v * x[i]; }, 0) / 8;
  var t2 = 0.5 * (logDet(cm) - 0.5 * (logDet(ca) + logDet(cb)));
  return 2 * (1 - Math.exp(-(t1 + t2)));
}

function spectralAngle(a, b) {
  var dot = 0, na = 0, nb = 0;
  for (var i = 0; i < a.length; i++) { dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; }
  var c = Math.max(-1, Math.min(1, dot / Math.sqrt(na * nb)));
  return Math.acos(c) * 180 / Math.PI;
}

/**
 * Combine the evaluated per-pass results into one record per class.
 * r: {total, eroded, used, pct, mean, std, cov} each a groupsToMap() result.
 * nSpectral: number of spectral bands (the extra last band is NDVI).
 */
function assembleClasses(r, nSpectral, minPixels) {
  var out = {};
  Object.keys(r.total).forEach(function (c) {
    var rec = {
      cls: Number(c),
      nTotal: r.total[c].count || 0,
      nAfterErosion: (r.eroded[c] || {}).count || 0,
      nUsed: (r.used[c] || {}).count || 0,
      warnings: []
    };
    if (r.erosionSkipped && r.erosionSkipped[c]) rec.warnings.push('erosion skipped: class too small or thin');
    rec.outlierShare = r.beforeOutliers && r.beforeOutliers[c] && r.beforeOutliers[c].count ?
      1 - rec.nUsed / r.beforeOutliers[c].count : 0;
    if (rec.nUsed < minPixels || !r.pct[c]) {
      rec.stats = null;
      rec.warnings.push('only ' + rec.nUsed + ' clean pixels (< ' + minPixels + ')');
    } else {
      var p = r.pct[c];
      var take = function (arr) { return arr.slice(0, nSpectral); };
      rec.stats = {
        p10: take(p.p10), p25: take(p.p25), median: take(p.p50), p75: take(p.p75), p90: take(p.p90),
        mean: take(r.mean[c].mean), std: take(r.std[c].stdDev)
      };
      rec.ndvi = {median: p.p50[nSpectral], p25: p.p25[nSpectral], p75: p.p75[nSpectral]};
      var spreads = rec.stats.median.map(function (m, i) {
        return (rec.stats.p75[i] - rec.stats.p25[i]) / Math.max(Math.abs(m), 1e-3);
      }).sort(function (a, b) { return a - b; });
      var mid = Math.floor(spreads.length / 2);
      rec.spread = spreads.length % 2 ? spreads[mid] : (spreads[mid - 1] + spreads[mid]) / 2;
      if (r.cov && r.cov[c]) rec.cov = firstValue(r.cov[c]);
    }
    out[c] = rec;
  });
  return out;
}

/** Round for display; null when missing or not a number (e.g. an all-masked band). */
function fmt(v, digits) {
  return typeof v === 'number' && isFinite(v) ? Number(v.toFixed(digits)) : null;
}

function firstValue(obj) {
  var k = Object.keys(obj)[0];
  return obj[k];
}

/** Pairwise JM for classes with stats and covariance. Returns {classes, matrix}. */
function separability(classes) {
  var ok = Object.keys(classes).filter(function (c) { return classes[c].stats && classes[c].cov; });
  var m = ok.map(function (ci, i) {
    return ok.map(function (cj, j) {
      if (i === j) return 0;
      try {
        return jeffriesMatusita(classes[ci].stats.mean, classes[ci].cov, classes[cj].stats.mean, classes[cj].cov);
      } catch (e) { return NaN; }
    });
  });
  return {classes: ok.map(Number), matrix: m};
}

/** Long-format rows like the Python signatures.csv. */
function signatureRows(classes, legend, bands, wavelengths, mapLabel) {
  var rows = [];
  Object.keys(classes).forEach(function (c) {
    var r = classes[c];
    if (!r.stats) return;
    bands.forEach(function (b, i) {
      rows.push({
        map: mapLabel || '', 'class': r.cls, class_name: className(legend, r.cls), band: b,
        wavelength_nm: wavelengths[i], n_used: r.nUsed,
        median: r.stats.median[i], p10: r.stats.p10[i], p25: r.stats.p25[i], p75: r.stats.p75[i],
        p90: r.stats.p90[i], mean: r.stats.mean[i], std: r.stats.std[i]
      });
    });
  });
  return rows;
}

/** Google Charts DataTable: median line per class with an IQR interval band. */
function signatureDataTable(classes, legend, wavelengths, only) {
  var keys = Object.keys(classes).filter(function (c) {
    return classes[c].stats && (only === undefined || String(only) === c);
  });
  var cols = [{id: 'wl', label: 'Wavelength (nm)', type: 'number'}];
  keys.forEach(function (c) {
    cols.push({id: 'm' + c, label: className(legend, Number(c)), type: 'number'});
    cols.push({id: 'lo' + c, type: 'number', role: 'interval'});
    cols.push({id: 'hi' + c, type: 'number', role: 'interval'});
  });
  var rows = wavelengths.map(function (wl, i) {
    var cells = [{v: wl}];
    keys.forEach(function (c) {
      var s = classes[c].stats;
      cells.push({v: s.median[i]}, {v: s.p25[i]}, {v: s.p75[i]});
    });
    return {c: cells};
  });
  return {cols: cols, rows: rows, colours: keys.map(function (c) { return classColour(legend, Number(c)); })};
}

// ============================ EARTH ENGINE PART ============================

function runClassSpectra(S) {
  var aoi = ee.Geometry.Rectangle(S.bbox);
  var sensor = SENSORS[S.sensor];
  var specBands = sensor.bands;
  var nSpec = specBands.length;
  var allBands = specBands.concat(['NDVI']);

  // ---- image ----
  var col, proj;
  if (S.sensor === 's2') {
    var csPlus = ee.ImageCollection('GOOGLE/CLOUD_SCORE_PLUS/V1/S2_HARMONIZED');
    col = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED')
      .filterBounds(aoi).filterDate(S.start, S.end)
      .linkCollection(csPlus, ['cs'])
      .map(function (im) {
        return im.select(specBands).multiply(0.0001)
          .updateMask(im.select('cs').gte(S.cloudScoreMin))
          .copyProperties(im, ['system:time_start']);
      });
  } else {
    var id = S.sensor === 'hls_s30' ? 'NASA/HLS/HLSS30/v002' : 'NASA/HLS/HLSL30/v002';
    col = ee.ImageCollection(id).filterBounds(aoi).filterDate(S.start, S.end)
      .map(function (im) {
        // Fmask bits 0-3: cirrus, cloud, adjacent to cloud, shadow
        var clear = im.select('Fmask').bitwiseAnd(15).eq(0);
        return im.select(specBands).updateMask(clear).copyProperties(im, ['system:time_start']);
      });
  }
  var first = ee.Image(col.first());
  proj = first.select(sensor.red).projection().atScale(sensor.scale);
  var img = col.median();
  if (S.sensor !== 's2') {
    // HLS in Earth Engine may be stored as scaled integers; normalise to 0-1 if so.
    var redMed = ee.Number(img.select(sensor.red).reduceRegion({
      reducer: ee.Reducer.median(), geometry: aoi, scale: 300, maxPixels: 1e9
    }).get(sensor.red));
    img = ee.Image(ee.Algorithms.If(redMed.gt(2), img.multiply(0.0001), img));
  }
  img = img.addBands(img.normalizedDifference([sensor.nir, sensor.red]).rename('NDVI'))
    .select(allBands).reproject(proj);

  // ---- maps ----
  var labels = loadMap(S.map, S, aoi);
  var aligned = alignLabels(labels.image, proj, sensor.scale);
  var valid = img.select(specBands).mask().reduce(ee.Reducer.min()).and(aligned.labels.gt(0));

  var main = signaturesFor(img, aligned.labels, aligned.purity, valid, S, aoi, proj, nSpec);

  var cmp = null;
  if (S.compareMap) {
    var other = loadMap(S.compareMap, S, aoi);
    var otherAligned = alignLabels(other.image, proj, sensor.scale);
    var ba = toBroad(aligned.labels, labels.legend);
    var bb = toBroad(otherAligned.labels, other.legend);
    var v2 = valid.and(ba.gt(0)).and(bb.gt(0));
    var agreeLabels = ba.where(ba.neq(bb), 0);
    cmp = {
      a: signaturesFor(img, ba, null, v2, S, aoi, proj, nSpec),
      b: signaturesFor(img, bb, null, v2, S, aoi, proj, nSpec),
      agreed: signaturesFor(img, agreeLabels, null, v2.and(agreeLabels.gt(0)), S, aoi, proj, nSpec),
      countA: groupedCount(v2, ba, aoi, proj, S),
      countB: groupedCount(v2, bb, aoi, proj, S),
      countAgree: groupedCount(v2.and(ba.eq(bb)), ba, aoi, proj, S),
      legendA: labels.legend, legendB: other.legend
    };
  }

  // ---- map display ----
  Map.centerObject(aoi, 12);
  var vis = S.sensor === 'hls_l30' ? ['B4', 'B3', 'B2'] : [sensor.red, 'B3', 'B2'];
  Map.addLayer(img.clip(aoi), {bands: vis, min: 0, max: 0.2}, 'Composite (true colour)');
  Map.addLayer(labels.image.clip(aoi).randomVisualizer(), {}, 'Land cover: ' + S.map, false);
  Map.addLayer(main.keep.selfMask().clip(aoi), {palette: ['00ffff']}, 'Pixels used for signatures', false);

  // ---- evaluate once, then build charts client-side ----
  var payload = {main: main.results};
  if (cmp) {
    payload.a = cmp.a.results; payload.b = cmp.b.results; payload.agreed = cmp.agreed.results;
    payload.countA = cmp.countA; payload.countB = cmp.countB; payload.countAgree = cmp.countAgree;
  }
  print('Computing signatures... (this can take a minute)');
  ee.Dictionary(payload).evaluate(function (res, err) {
    if (err) { print('Error: ' + err); return; }
    var legend = labels.legend;
    var classes = assembleClasses(unpack(res.main), nSpec, S.minPixels);
    report(classes, legend, sensor, S, 'Signatures: ' + S.map);
    var sep = separability(classes);
    printSeparability(sep, legend);
    if (cmp) {
      var A = assembleClasses(unpack(res.a), nSpec, S.minPixels);
      var B = assembleClasses(unpack(res.b), nSpec, S.minPixels);
      var G = assembleClasses(unpack(res.agreed), nSpec, S.minPixels);
      printComparison(A, B, G, groupsToMap(res.countA), groupsToMap(res.countB),
        groupsToMap(res.countAgree), S, sensor);
    }
    if (S.exportCsv) {
      var rows = signatureRows(classes, legend, specBands, sensor.wavelengths, S.map);
      Export.table.toDrive({
        collection: ee.FeatureCollection(rows.map(function (r) { return ee.Feature(null, r); })),
        description: S.exportPrefix + '_signatures', fileFormat: 'CSV'
      });
      print('CSV export queued in the Tasks tab.');
    }
  });
}

function loadMap(key, S, aoi) {
  var year = S.start.slice(0, 4);
  if (key === 'worldcover2021') return {image: ee.ImageCollection('ESA/WorldCover/v200').first().select('Map').rename('lc'), legend: 'worldcover'};
  if (key === 'worldcover2020') return {image: ee.ImageCollection('ESA/WorldCover/v100').first().select('Map').rename('lc'), legend: 'worldcover'};
  if (key === 'dynamicworld') {
    return {
      image: ee.ImageCollection('GOOGLE/DYNAMICWORLD/V1').filterBounds(aoi).filterDate(S.start, S.end)
        .select('label').mode().add(100).rename('lc'),  // shift so class 0 (water) is not treated as nodata
      legend: 'dynamicworld_shifted'
    };
  }
  if (key === 'io') {
    // Impact Observatory / Esri 10 m annual LULC, Earth Engine community catalog
    return {
      image: ee.ImageCollection('projects/sat-io/open-datasets/landcover/ESRI_Global-LULC_10m_TS')
        .filterDate(year + '-01-01', (Number(year) + 1) + '-01-01').mosaic().select(0).rename('lc'),
      legend: 'io'
    };
  }
  throw new Error('Unknown map: ' + key);
}

// Dynamic World codes are shifted by +100 inside Earth Engine so 0 can mean "no data".
LEGENDS.dynamicworld_shifted = {};
Object.keys(LEGENDS.dynamicworld).forEach(function (k) { LEGENDS.dynamicworld_shifted[Number(k) + 100] = LEGENDS.dynamicworld[k]; });
BROAD.dynamicworld_shifted = {};
Object.keys(BROAD.dynamicworld).forEach(function (k) { BROAD.dynamicworld_shifted[Number(k) + 100] = BROAD.dynamicworld[k]; });

/** Map on the image grid. For coarse images: majority class plus purity. */
function alignLabels(lc, proj, scale) {
  lc = lc.unmask(0).toInt();
  if (scale <= 10) {
    return {labels: lc.reproject(proj).rename('lc'), purity: null};
  }
  var lcNative = lc.reproject(lc.projection().atScale(10));
  var labels = lcNative.reduceResolution({reducer: ee.Reducer.mode(), maxPixels: 1024})
    .reproject(proj).toInt().rename('lc');
  // purity = share of the coarse pixel covered by its majority class
  var purity = lcNative.eq(labels).reduceResolution({reducer: ee.Reducer.mean(), maxPixels: 1024})
    .reproject(proj).rename('purity');
  return {labels: labels, purity: purity};
}

function toBroad(labels, legend) {
  var m = BROAD[legend];
  var from = Object.keys(m).map(Number);
  var to = from.map(function (k) { return m[k]; });
  return labels.remap(from, to, 0).toInt().rename('lc');
}

function reduceGroups(img, labels, reducer, nInputs, aoi, proj, S) {
  // class 0 means no data (or, for agreement labels, the maps disagree)
  return img.addBands(labels.selfMask()).reduceRegion({
    reducer: reducer.group({groupField: nInputs, groupName: 'class'}),
    geometry: aoi, crs: proj, maxPixels: 1e10, tileScale: S.tileScale
  }).get('groups');
}

function groupedCount(mask, labels, aoi, proj, S) {
  return reduceGroups(ee.Image(1).rename('one').updateMask(mask), labels, ee.Reducer.count(), 1, aoi, proj, S);
}

/** Grouped sums (repeat) -> list of {class, count} for band index i. */
function splitSums(groups, i) {
  return ee.List(groups).map(function (g) {
    g = ee.Dictionary(g);
    return ee.Dictionary({'class': g.get('class'), count: ee.List(g.get('sum')).get(i)});
  });
}

function countsToDict(list) {
  return ee.Dictionary(ee.List(list).iterate(function (g, acc) {
    g = ee.Dictionary(g);
    return ee.Dictionary(acc).set(ee.Number(g.get('class')).toInt().format('%d'), g.get('count'));
  }, ee.Dictionary({})));
}

/** Per-class image built from a server-side grouped result: value_i per class. */
function perClassImage(labels, groups, key, nBands, names) {
  groups = ee.List(groups);
  var classes = groups.map(function (g) { return ee.Dictionary(g).get('class'); });
  var bands = ee.List.sequence(0, nBands - 1).map(function (i) {
    var vals = groups.map(function (g) {
      // fixed point so remap stays integer
      return ee.Number(ee.List(ee.Dictionary(g).get(key)).get(i)).multiply(1e5).round().toInt();
    });
    return labels.remap(classes, vals).toFloat().divide(1e5);
  });
  return ee.ImageCollection.fromImages(bands).toBands().rename(names);
}

/** All the server-side passes for one map. Returns {results, keep}. */
function signaturesFor(img, labels, purity, valid, S, aoi, proj, nSpec) {
  var spec = img.select(ee.List.sequence(0, nSpec - 1));
  var specNames = spec.bandNames();
  var r = S.erosion;

  // 1. erosion: keep pixels whose square neighbourhood has a single class
  var interior = r > 0 ?
    labels.focalMax({radius: r, kernelType: 'square', units: 'pixels'})
      .eq(labels.focalMin({radius: r, kernelType: 'square', units: 'pixels'})) :
    ee.Image(1);
  // one pass for both counts: sums of 0/1 bands per class
  var counts1 = reduceGroups(valid.rename('total').addBands(valid.and(interior).rename('eroded')).toInt(),
    labels, ee.Reducer.sum().unweighted().repeat(2), 2, aoi, proj, S);
  var total = splitSums(counts1, 0);
  var eroded = splitSums(counts1, 1);
  var totalMap = countsToDict(total);
  var erodedMap = countsToDict(eroded);
  var classKeys = totalMap.keys();
  var skip = classKeys.map(function (k) {
    var nt = ee.Number(totalMap.get(k));
    var ne = ee.Number(erodedMap.get(k, 0));
    return ee.Number(r > 0 ? 1 : 0).and(ne.lt(S.minPixels)).and(nt.gte(S.minPixels));
  });
  var skipImg = labels.remap(classKeys.map(function (k) { return ee.Number.parse(k); }), skip, 0);
  var keep = valid.and(interior.or(skipImg));
  if (purity) keep = keep.and(purity.gte(S.minPurity));

  // 2. robust outlier trimming: RMS of (x - class median) / (1.4826 * class MAD)
  var keepBefore = keep;
  if (S.outlierZ > 0) {
    var med = reduceGroups(spec.updateMask(keep), labels, ee.Reducer.median().repeat(nSpec), nSpec, aoi, proj, S);
    var medImg = perClassImage(labels, med, 'median', nSpec, specNames);
    var absDev = spec.subtract(medImg).abs();
    var mad = reduceGroups(absDev.updateMask(keep), labels, ee.Reducer.median().repeat(nSpec), nSpec, aoi, proj, S);
    var madImg = perClassImage(labels, mad, 'median', nSpec, specNames).multiply(1.4826).max(1e-6);
    var z = spec.subtract(medImg).divide(madImg).pow(2).reduce(ee.Reducer.mean()).sqrt();
    keep = keep.and(z.lte(S.outlierZ));
  }

  // 3. statistics on the cleaned pixels (spectral bands + NDVI)
  var n = nSpec + 1;
  var clean = img.updateMask(keep);
  var counts2 = reduceGroups(keepBefore.rename('before').addBands(keep.rename('used')).toInt(),
    labels, ee.Reducer.sum().unweighted().repeat(2), 2, aoi, proj, S);
  var results = {
    total: total,
    eroded: eroded,
    erosionSkipped: ee.Dictionary.fromLists(classKeys, skip),
    beforeOutliers: splitSums(counts2, 0),
    used: splitSums(counts2, 1),
    pct: reduceGroups(clean, labels, ee.Reducer.percentile([10, 25, 50, 75, 90]).repeat(n), n, aoi, proj, S),
    mean: reduceGroups(clean, labels, ee.Reducer.mean().repeat(n), n, aoi, proj, S),
    std: reduceGroups(clean, labels, ee.Reducer.stdDev().repeat(n), n, aoi, proj, S),
    cov: reduceGroups(spec.updateMask(keep).toArray(), labels, ee.Reducer.covariance(), 1, aoi, proj, S)
  };
  return {results: results, keep: keep};
}

/** Evaluated results -> plain maps keyed by class. */
function unpack(r) {
  var out = {};
  ['total', 'eroded', 'beforeOutliers', 'used', 'pct', 'mean', 'std', 'cov'].forEach(function (k) {
    out[k] = groupsToMap(r[k]);
  });
  out.erosionSkipped = r.erosionSkipped || {};
  return out;
}

function lineChart(dt, title, colours, dashed) {
  var series = {};
  colours.forEach(function (c, i) {
    series[i] = {color: c, lineWidth: 2};
    if (dashed && dashed[i]) series[i].lineDashStyle = [4, 4];
  });
  return ui.Chart({cols: dt.cols, rows: dt.rows}, 'LineChart', {
    title: title, intervals: {style: 'area', fillOpacity: 0.15}, series: series,
    hAxis: {title: 'Wavelength (nm)'}, vAxis: {title: 'Surface reflectance', viewWindow: {min: 0}},
    legend: {position: 'right'}, height: 380
  });
}

function report(classes, legend, sensor, S, title) {
  var dt = signatureDataTable(classes, legend, sensor.wavelengths);
  print(lineChart(dt, title + ' (median, shaded IQR)', dt.colours));
  Object.keys(classes).forEach(function (c) {
    if (!classes[c].stats) return;
    var one = signatureDataTable(classes, legend, sensor.wavelengths, c);
    var r = classes[c];
    print(lineChart(one, className(legend, r.cls) + ': n=' + r.nUsed + ', outliers ' +
      fmt(100 * r.outlierShare, 1) + '%', one.colours));
  });
  var rows = [['Class', 'Pixels', 'After erosion', 'Used', 'Outlier %', 'Spread', 'NDVI median', 'Warnings']];
  Object.keys(classes).forEach(function (c) {
    var r = classes[c];
    rows.push([className(legend, r.cls), r.nTotal, r.nAfterErosion, r.nUsed,
      fmt(100 * r.outlierShare, 1), fmt(r.spread, 3),
      r.ndvi ? fmt(r.ndvi.median, 3) : null, r.warnings.join('; ')]);
  });
  print(ui.Chart(rows, 'Table', {title: 'Class summary'}));
}

function printSeparability(sep, legend) {
  var names = sep.classes.map(function (c) { return className(legend, c); });
  var rows = [[''].concat(names)];
  sep.matrix.forEach(function (row, i) {
    rows.push([names[i]].concat(row.map(function (v) { return fmt(v, 2); })));
  });
  print('Jeffries-Matusita separability (0 = identical, 2 = fully separable)');
  print(ui.Chart(rows, 'Table'));
}

function printComparison(A, B, G, cA, cB, cAgree, S, sensor) {
  var la = S.map, lb = S.compareMap;
  var rows = [['Broad class', 'Pixels ' + la, 'Pixels ' + lb, 'Share agreed', 'Angle A vs B (deg)',
    'NDVI ' + la, 'NDVI ' + lb, 'NDVI agreed']];
  Object.keys(cA).forEach(function (c) {
    var a = A[c], b = B[c], g = G[c];
    var nA = cA[c].count, agree = (cAgree[c] || {}).count || 0;
    rows.push([className('broad', Number(c)), nA, (cB[c] || {}).count || 0, fmt(agree / nA, 3),
      a && b && a.stats && b.stats ? fmt(spectralAngle(a.stats.median, b.stats.median), 2) : null,
      a && a.ndvi ? fmt(a.ndvi.median, 3) : null,
      b && b.ndvi ? fmt(b.ndvi.median, 3) : null,
      g && g.ndvi ? fmt(g.ndvi.median, 3) : null]);
  });
  print('Map comparison on the same pixels: ' + la + ' vs ' + lb);
  print(ui.Chart(rows, 'Table'));
  // overlay: A solid, B dashed, per broad class
  Object.keys(A).forEach(function (c) {
    if (!A[c].stats || !B[c] || !B[c].stats) return;
    var both = {};
    both['a'] = A[c];
    both['b'] = {cls: A[c].cls, stats: B[c].stats};
    var dt = {cols: [{id: 'wl', label: 'Wavelength (nm)', type: 'number'},
      {id: 'a', label: la, type: 'number'}, {id: 'alo', type: 'number', role: 'interval'},
      {id: 'ahi', type: 'number', role: 'interval'}, {id: 'b', label: lb, type: 'number'}],
      rows: sensor.wavelengths.map(function (wl, i) {
        return {c: [{v: wl}, {v: A[c].stats.median[i]}, {v: A[c].stats.p25[i]}, {v: A[c].stats.p75[i]},
          {v: B[c].stats.median[i]}]};
      })};
    var col = classColour('broad', Number(c));
    print(lineChart(dt, className('broad', Number(c)) + ': ' + la + ' (solid, IQR) vs ' + lb + ' (dashed)',
      [col, '#222222'], [false, true]));
  });
}

// ================================= RUN =====================================
if (typeof ee !== 'undefined' && typeof ui !== 'undefined') {
  runClassSpectra(SETTINGS);
}
if (typeof module !== 'undefined') {
  module.exports = {
    groupsToMap: groupsToMap, cholesky: cholesky, logDet: logDet, solveSPD: solveSPD,
    jeffriesMatusita: jeffriesMatusita, spectralAngle: spectralAngle, assembleClasses: assembleClasses,
    separability: separability, signatureRows: signatureRows, signatureDataTable: signatureDataTable,
    className: className, LEGENDS: LEGENDS, BROAD: BROAD, SENSORS: SENSORS
  };
}
