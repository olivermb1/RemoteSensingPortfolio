// Dry run of gee/campwatch_gee.js in Node with a permissive mock of `ee`, Map,
// ui, Export and print. Catches undefined variables, typos in our own helpers
// and the export branch; it does NOT check Earth Engine semantics.
// Usage: node tests/gee_dryrun.js
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', 'gee', 'campwatch_gee.js'), 'utf8');
function mock(name) {
  const f = function () { return mock(name + '()'); };
  return new Proxy(f, {
    get: (t, k) => (k === Symbol.toPrimitive ? () => 1 : k === 'toString' ? () => name : mock(name + '.' + String(k))),
    apply: () => mock(name + '()'),
    construct: () => mock('new ' + name),
  });
}
{
  const code = src.replace('var EXPORT = false;', 'var EXPORT = true;');
  const calls = [];
  const fn = new Function('ee', 'Map', 'ui', 'Export', 'print', code);
  fn(mock('ee'), mock('Map'), mock('ui'), mock('Export'), (...a) => calls.push(a[0]));
  console.log('ok; printed:', calls.filter((x) => typeof x === 'string').join(' | '));
}
