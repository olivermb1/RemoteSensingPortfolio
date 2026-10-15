// Dry run of gee/floodcrop_gee.js in Node with a permissive mock of `ee`, Map,
// ui, Export and print. Catches undefined variables, typos in our own helpers
// and branch errors for each SOURCE; it does NOT check Earth Engine semantics.
// Usage: node tests/gee_dryrun.js
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', 'gee', 'floodcrop_gee.js'), 'utf8');
function mock(name) {
  const f = function () { return mock(name + '()'); };
  return new Proxy(f, {
    get: (t, k) => (k === Symbol.toPrimitive ? () => 1 : k === 'toString' ? () => name : mock(name + '.' + String(k))),
    apply: () => mock(name + '()'),
    construct: () => mock('new ' + name),
  });
}
for (const source of ['S1', 'HLS', 'DSWX']) {
  const code = src.replace(/var SOURCE = '[A-Z0-9]+';/, `var SOURCE = '${source}';`);
  const calls = [];
  const fn = new Function('ee', 'Map', 'ui', 'Export', 'print', code);
  fn(mock('ee'), mock('Map'), mock('ui'), mock('Export'), (...a) => calls.push(a[0]));
  console.log(source, 'ok; printed:', calls.filter((x) => typeof x === 'string').join(' | '));
}
