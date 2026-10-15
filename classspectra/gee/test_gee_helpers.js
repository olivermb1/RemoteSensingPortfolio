// Node tests for the pure-JS helpers in classspectra_gee.js: node gee/test_gee_helpers.js
// fixture_jm.json holds values computed by the Python core (classspectra/core.py).
var assert = require('assert');
var path = require('path');
var h = require('./classspectra_gee.js');
var fx = require(path.join(__dirname, 'fixture_jm.json'));

function close(a, b, tol, msg) { assert.ok(Math.abs(a - b) < tol, msg + ': ' + a + ' vs ' + b); }

// JM and spectral angle match the Python implementation
close(h.jeffriesMatusita(fx.meanA, fx.covA, fx.meanB, fx.covB), fx.jm, 1e-6, 'JM vs Python');
close(h.spectralAngle(fx.meanA, fx.meanB), fx.angle, 1e-9, 'angle vs Python');
close(h.jeffriesMatusita(fx.meanA, fx.covA, fx.meanA, fx.covA), 0, 1e-9, 'JM identical');

// linear algebra
var A = [[4, 2], [2, 3]];
close(h.logDet(A), Math.log(8), 1e-12, 'logDet');
var x = h.solveSPD(A, [2, 1]);
close(4 * x[0] + 2 * x[1], 2, 1e-12, 'solve row 1');
close(2 * x[0] + 3 * x[1], 1, 1e-12, 'solve row 2');

// assembling an Earth Engine grouped result (shape as returned by evaluate)
function g(c, obj) { obj['class'] = c; return obj; }
var raw = {
  total: h.groupsToMap([g(10, {count: 1000}), g(90, {count: 12})]),
  eroded: h.groupsToMap([g(10, {count: 800})]),
  beforeOutliers: h.groupsToMap([g(10, {count: 800}), g(90, {count: 12})]),
  used: h.groupsToMap([g(10, {count: 760}), g(90, {count: 12})]),
  pct: h.groupsToMap([g(10, {p10: [0.02, 0.2, 0.5], p25: [0.03, 0.25, 0.6], p50: [0.04, 0.3, 0.7],
                             p75: [0.05, 0.35, 0.75], p90: [0.06, 0.4, 0.8]})]),
  mean: h.groupsToMap([g(10, {mean: [0.04, 0.3, 0.7]})]),
  std: h.groupsToMap([g(10, {stdDev: [0.01, 0.05, 0.1]})]),
  cov: h.groupsToMap([g(10, {covariance: [[1e-4, 0], [0, 2.5e-3]]})]),
  erosionSkipped: {'10': 0, '90': 1}
};
var cls = h.assembleClasses(raw, 2, 30);
assert.strictEqual(cls[10].nUsed, 760);
close(cls[10].outlierShare, 0.05, 1e-12, 'outlier share');
assert.deepStrictEqual(cls[10].stats.median, [0.04, 0.3]);        // NDVI band dropped from spectra
close(cls[10].ndvi.median, 0.7, 1e-12, 'ndvi');
close(cls[10].spread, ((0.05 - 0.03) / 0.04 + (0.35 - 0.25) / 0.3) / 2, 1e-12, 'spread');
assert.strictEqual(cls[90].stats, null);                           // too few pixels
assert.ok(cls[90].warnings.join(' ').indexOf('erosion skipped') >= 0);

var rows = h.signatureRows(cls, 'worldcover', ['B2', 'B3'], [490, 560], 'WC');
assert.strictEqual(rows.length, 2);
assert.strictEqual(rows[0].class_name, 'Tree cover');
var dt = h.signatureDataTable(cls, 'worldcover', [490, 560]);
assert.strictEqual(dt.cols.length, 4);   // wl + median + 2 interval columns
assert.strictEqual(dt.rows[1].c[1].v, 0.3);

// broad cross-walk covers every non-trivial class of each legend
['worldcover', 'io', 'dynamicworld'].forEach(function (l) {
  Object.keys(h.BROAD[l]).forEach(function (k) { assert.ok(h.LEGENDS.broad[h.BROAD[l][k]], l + ' ' + k); });
});
console.log('all GEE helper tests passed');
