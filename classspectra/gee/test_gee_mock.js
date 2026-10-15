// Runs the whole Code Editor script in Node against a stand-in `ee`/`ui`/`Map`.
// It cannot check Earth Engine itself; it checks the script's own control flow:
// every function is reachable, and the client-side reporting runs on
// results shaped like Earth Engine's grouped-reducer output.
// Usage: node gee/test_gee_mock.js
var fs = require('fs'), vm = require('vm'), path = require('path'), assert = require('assert');
var src = fs.readFileSync(path.join(__dirname, 'classspectra_gee.js'), 'utf8');

var calls = [];
function fake(name) {
  var fn = function () { calls.push(name); return fake(name + '()'); };
  return new Proxy(fn, {
    get: function (t, k) {
      if (k === 'evaluate') return function (cb) { cb(fakeResult(), undefined); };
      if (typeof k === 'symbol' || k === 'then' || k === 'prototype') return undefined;
      return fake(name + '.' + String(k));
    },
    apply: function () { calls.push(name); return fake(name + '()'); },
    construct: function () { return fake('new ' + name); }
  });
}

function groups(nb) {
  function arr(base) { var a = []; for (var i = 0; i < nb; i++) a.push(base + 0.01 * i); return a; }
  function cov() { var m = []; for (var i = 0; i < nb - 1; i++) { m.push([]); for (var j = 0; j < nb - 1; j++) m[i].push(i === j ? 1e-3 * (1 + i) : 2e-4); } return m; }
  function grp(key, f) { return [{'class': 10}, {'class': 40}, {'class': 2}, {'class': 5}].map(function (g) { var o = {'class': g['class']}; o[key] = f(g['class']); return o; }); }
  var pct = [{'class': 10}, {'class': 40}, {'class': 2}, {'class': 5}].map(function (g) {
    var b = g['class'] / 400;
    return {'class': g['class'], p10: arr(b), p25: arr(b + 0.01), p50: arr(b + 0.02), p75: arr(b + 0.03), p90: arr(b + 0.04)};
  });
  return {
    total: grp('count', function () { return 5000; }), eroded: grp('count', function () { return 4000; }),
    beforeOutliers: grp('count', function () { return 4000; }), used: grp('count', function () { return 3900; }),
    pct: pct, mean: grp('mean', function (c) { return arr(c / 400 + 0.02); }),
    std: grp('stdDev', function () { return arr(0.01); }), cov: grp('covariance', cov),
    erosionSkipped: {'10': 0, '40': 0}
  };
}
var NB = 11;
function fakeResult() {
  var nb = NB, g = groups(nb);
  return {main: g, a: g, b: g, agreed: g, countA: g.total, countB: g.total, countAgree: g.used};
}

var printed = [];
var ctx = {
  ee: fake('ee'), ui: {Chart: function (data, type, opts) { printed.push({type: type || 'chart', opts: opts, data: data}); return {}; }},
  Map: fake('Map'), Export: fake('Export'), print: function (x) { printed.push(x); }, console: console
};
vm.createContext(ctx);
['s2', 'hls_s30', 'hls_l30'].forEach(function (sensor) {
  ['worldcover2021', 'dynamicworld', 'io'].forEach(function (m) {
    printed.length = 0;
    NB = { s2: 10, hls_s30: 11, hls_l30: 7 }[sensor] + 1;
    vm.runInContext(src.replace("sensor: 's2'", "sensor: '" + sensor + "'").replace("map: 'worldcover2021'", "map: '" + m + "'"), ctx);
    var charts = printed.filter(function (p) { return p && p.type; });
    assert.ok(charts.some(function (c) { return c.type === 'LineChart'; }), sensor + '/' + m + ': no line chart');
    assert.ok(charts.some(function (c) { return c.type === 'Table'; }), sensor + '/' + m + ': no table');
    var nb = ctx.SENSORS[sensor].bands.length;
    var lc = charts.filter(function (c) { return c.type === 'LineChart'; })[0];
    assert.strictEqual(lc.data.rows.length, nb, 'one chart row per band');
    console.log('ok', sensor, m, '-', charts.length, 'charts/tables printed');
  });
});
assert.ok(calls.some(function (c) { return c.indexOf('Export.table.toDrive') === 0; }), 'CSV export queued');
console.log('mock run passed');
