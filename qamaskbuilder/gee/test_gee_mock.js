// Runs qamask_gee.js in Node against a tiny pixel-array stand-in for ee.Image
// and checks its masks match the Python core's, pixel for pixel, on real
// HLS, Landsat and DSWx crops (gee/fixture.json from tests/make_gee_fixture.py).
// It cannot check Earth Engine itself.
// Usage: node gee/test_gee_mock.js
var fs = require('fs'), path = require('path'), assert = require('assert');

function map2(a, f) { return a.map(function (r, i) { return r.map(function (v, j) { return f(v, i, j); }); }); }
function Img(data, masked) { this.d = data; this.m = masked || map2(data, function () { return false; }); }
function bin(name, f) {
  Img.prototype[name] = function (o) {
    return new Img(map2(this.d, function (v, i, j) { return f(v, o instanceof Img ? o.d[i][j] : o); }), this.m);
  };
}
bin('rightShift', function (a, b) { return Math.floor(a / Math.pow(2, b)); });
bin('bitwiseAnd', function (a, b) { return Number(BigInt(a) & BigInt(b)); });
bin('eq', function (a, b) { return a === b ? 1 : 0; });
bin('or', function (a, b) { return (a || b) ? 1 : 0; });
bin('and', function (a, b) { return (a && b) ? 1 : 0; });
bin('multiply', function (a, b) { return a * b; });
Img.prototype.not = function () { return new Img(map2(this.d, function (v) { return v ? 0 : 1; }), this.m); };
Img.prototype.toInt64 = Img.prototype.toByte = Img.prototype.rename = Img.prototype.select = function () { return this; };
Img.prototype.updateMask = function (m) { return new Img(this.d, map2(this.m, function (v, i, j) { return v || !m.d[i][j]; })); };
Img.prototype.addBands = function () { return this; };
Img.prototype.focalMax = function (o) {
  var d = this.d, r = o.radius, h = d.length, w = d[0].length;
  return new Img(map2(d, function (v, i, j) {
    var mx = 0;
    for (var y = Math.max(0, i - r); y <= Math.min(h - 1, i + r); y++)
      for (var x = Math.max(0, j - r); x <= Math.min(w - 1, j + r); x++) mx = Math.max(mx, d[y][x]);
    return mx;
  }), this.m);
};

var QAMask = require(path.join(__dirname, 'qamask_gee.js'));
var cases = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixture.json'), 'utf8'));
cases.forEach(function (c) {
  var m = QAMask.mask(new Img(c.qa), c.product, c.options);
  var got = map2(m.d, function (v, i, j) { return m.m[i][j] ? 255 : v; });
  var bad = 0;
  got.forEach(function (r, i) { r.forEach(function (v, j) { if (v !== c.mask[i][j]) bad++; }); });
  assert.strictEqual(bad, 0, c.product + ' ' + JSON.stringify(c.options) + ': ' + bad + ' pixels differ');
  console.log('ok', c.product, JSON.stringify(c.options));
});
assert.throws(function () { QAMask.mask(new Img([[0]]), 'hls_fmask', {drop: ['nope']}); });
assert.deepStrictEqual(QAMask.products().length, Object.keys(QAMask.PRODUCTS).length);
console.log('all', cases.length, 'cases match the Python core');
