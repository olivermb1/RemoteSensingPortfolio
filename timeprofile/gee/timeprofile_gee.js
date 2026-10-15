// Time Profile for Google Earth Engine
// Click the map (or draw polygons) and get a cloud-masked chart of an index through
// time from NASA HLS (Landsat L30 + Sentinel-2 S30 together) or Sentinel-2 L2A.
// Same rules as the Python/QGIS tool: quality-mask each image, keep a polygon's
// observation only when MIN_CLEAR % of its pixels are clear, one row per place and date.
// Paste into the Code Editor (code.earthengine.google.com) and press Run.
// Untested in Earth Engine itself: only a Node mock run (gee/test_gee_mock.js).

// ---- settings (the panel can change most of these) -----------------------------------
var DATASET = 'HLS';            // 'HLS' (L30 + S30) or 'S2' (COPERNICUS/S2_SR_HARMONIZED)
var INDEX = 'NDVI';
var START = '2023-01-01';
var END = '2024-12-31';
var MIN_CLEAR = 50;             // % of a polygon's pixels that must be clear
var SEASON_START = 1;           // month the season view starts (10 = Oct-Sep)
var CENTER = [37.343, -0.655, 13]; // Mwea irrigation scheme, Kenya
var PALETTE = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'];

var INDICES = {
  NDVI: '(nir - red) / (nir + red)',
  EVI: '2.5 * (nir - red) / (nir + 6 * red - 7.5 * blue + 1)',
  SAVI: '1.5 * (nir - red) / (nir + red + 0.5)',
  NDWI: '(green - nir) / (green + nir)',
  MNDWI: '(green - swir1) / (green + swir1)',
  NDMI: '(nir - swir1) / (nir + swir1)',
  NBR: '(nir - swir2) / (nir + swir2)',
  BSI: '((swir1 + red) - (nir + blue)) / ((swir1 + red) + (nir + blue))'
};
var COMMON = ['blue', 'green', 'red', 'nir', 'swir1', 'swir2'];

// ---- datasets: common band names, reflectance 0-1, a 0/1 'clear' band ----------------
function bit(img, start, n) {
  return img.rightShift(start).bitwiseAnd(Math.pow(2, n) - 1);
}

function hlsClear(fmask) {
  // Fmask v2: bit 1 cloud, 2 adjacent to cloud/shadow, 3 cloud shadow, 4 snow/ice, 6-7 aerosol (3 = high)
  return bit(fmask, 1, 1).eq(0).and(bit(fmask, 2, 1).eq(0)).and(bit(fmask, 3, 1).eq(0))
    .and(bit(fmask, 4, 1).eq(0)).and(bit(fmask, 6, 2).neq(3));
}

function hlsPrep(bands, sensor) {
  return function (img) {
    var refl = img.select(bands, COMMON);
    // GEE may store HLS as scaled integers or as floats; scale only integers.
    var precision = ee.Dictionary(ee.Dictionary(img.bandTypes()).get(bands[2])).get('precision');
    refl = ee.Image(ee.Algorithms.If(ee.String(precision).equals('int'), refl.multiply(0.0001), refl));
    return refl.addBands(hlsClear(img.select('Fmask')).rename('clear'))
      .copyProperties(img, ['system:time_start']).set('SENSOR', sensor);
  };
}

function s2Prep(img) {
  var scl = img.select('SCL');
  var clear = scl.eq(2).or(scl.eq(4)).or(scl.eq(5)).or(scl.eq(6)).or(scl.eq(7));
  return img.select(['B2', 'B3', 'B4', 'B8', 'B11', 'B12'], COMMON).multiply(0.0001)
    .addBands(clear.rename('clear'))
    .copyProperties(img, ['system:time_start']).set('SENSOR', img.get('SPACECRAFT_NAME'));
}

function collection(region) {
  if (DATASET === 'S2') {
    return ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(region).filterDate(START, END)
      .map(s2Prep);
  }
  var l30 = ee.ImageCollection('NASA/HLS/HLSL30/v002').filterBounds(region).filterDate(START, END)
    .map(hlsPrep(['B2', 'B3', 'B4', 'B5', 'B6', 'B7'], 'HLS.L30'));
  var s30 = ee.ImageCollection('NASA/HLS/HLSS30/v002').filterBounds(region).filterDate(START, END)
    .map(hlsPrep(['B2', 'B3', 'B4', 'B8A', 'B11', 'B12'], 'HLS.S30'));
  return l30.merge(s30).sort('system:time_start');
}

// One feature per place and image: mean index over clear pixels, and the clear fraction.
function observations(places) {
  var scale = DATASET === 'S2' ? 10 : 30;
  var expr = INDICES[INDEX] || INDEX;
  return collection(places.geometry()).map(function (img) {
    var bands = {};
    COMMON.forEach(function (b) { bands[b] = img.select(b); });
    var valid = img.select('red').mask();
    var value = img.expression(expr, bands).rename('index').updateMask(img.select('clear'));
    var clear = img.select('clear').updateMask(valid).rename('clear');
    var date = img.date();
    return value.addBands(clear).reduceRegions({collection: places, reducer: ee.Reducer.mean(), scale: scale})
      .map(function (f) {
        var s0 = ee.Date.fromYMD(date.get('year').subtract(date.get('month').lt(SEASON_START)), SEASON_START, 1);
        var y0 = ee.Number(s0.get('year'));
        var season = SEASON_START === 1 ? y0.format('%d')
          : y0.format('%d').cat('-').cat(y0.add(1).mod(100).format('%02d'));
        return f.set({'system:time_start': date.millis(), date: date.format('YYYY-MM-dd'),
                      season: season, day: date.difference(s0, 'day').floor(),
                      sensor: img.get('SENSOR'), index_name: INDEX});
      });
  }).flatten()
    .filter(ee.Filter.notNull(['index']))
    .filter(ee.Filter.gte('clear', MIN_CLEAR / 100));
}

// ---- UI --------------------------------------------------------------------------------
var places = [];  // ee.Feature list with a 'name'
var markers = ui.Map.Layer(ee.FeatureCollection([]), {}, 'places');
var chartBox = ui.Panel();
var status = ui.Label('Click the map or draw a polygon.');
var keep = ui.Checkbox('Keep earlier places', true);
var view = ui.Select({items: ['Through time', 'Season by season'], value: 'Through time'});
var which = ui.Select({items: [], placeholder: 'place for the season view'});

function placesFc() {
  return ee.FeatureCollection(places);
}

function draw() {
  chartBox.clear();
  if (!places.length) return;
  status.setValue('Computing ' + INDEX + ' for ' + places.length + ' place(s)...');
  var obs = observations(placesFc());
  var chart;
  if (view.getValue() === 'Season by season') {
    var name = which.getValue() || places[places.length - 1].get('name');
    chart = ui.Chart.feature.groups({features: obs.filter(ee.Filter.eq('name', name)),
                                     xProperty: 'day', yProperty: 'index', seriesProperty: 'season'})
      .setOptions({title: INDEX + ' by season', hAxis: {title: 'days since season start'}});
  } else {
    chart = ui.Chart.feature.groups({features: obs, xProperty: 'system:time_start', yProperty: 'index',
                                     seriesProperty: 'name'})
      .setOptions({title: INDEX + ' through time (' + DATASET + ', clouds masked)'});
  }
  chart.setChartType('ScatterChart').setOptions({
    colors: PALETTE, pointSize: 4, lineWidth: 1, vAxis: {title: INDEX},
    legend: {position: 'top'}, interpolateNulls: false});
  chartBox.add(chart);
  status.setValue(places.length + ' place(s). Hover the chart for values.');
}

function addPlace(geom, label) {
  if (!keep.getValue()) places = [];
  var name = label + ' ' + (places.length + 1);
  places.push(ee.Feature(geom, {name: name}));
  markers.setEeObject(placesFc().style({color: '2a78d6', fillColor: '2a78d633', pointSize: 6}));
  which.items().reset(places.map(function (p, i) { return label + ' ' + (i + 1); }));
  draw();
}

Map.onClick(function (coords) {
  addPlace(ee.Geometry.Point([coords.lon, coords.lat]), 'Point');
});

var tools = Map.drawingTools();
tools.setShape('polygon');
tools.onDraw(function (geom) {
  addPlace(geom, 'Polygon');
  tools.layers().reset();
});

function exportCsv() {
  if (!places.length) return;
  Export.table.toDrive({collection: observations(placesFc()), description: 'timeprofile_' + INDEX,
                        fileFormat: 'CSV', selectors: ['name', 'date', 'sensor', 'index_name', 'index', 'clear',
                                                       'season', 'day']});
  status.setValue('Export queued: open the Tasks tab to run it.');
}

var indexSel = ui.Select({items: Object.keys(INDICES), value: INDEX, onChange: function (v) { INDEX = v; draw(); }});
var dataSel = ui.Select({items: ['HLS', 'S2'], value: DATASET, onChange: function (v) { DATASET = v; draw(); }});
var startBox = ui.Textbox({value: START, onChange: function (v) { START = v; draw(); }});
var endBox = ui.Textbox({value: END, onChange: function (v) { END = v; draw(); }});
var clearSl = ui.Slider({min: 0, max: 100, step: 5, value: MIN_CLEAR,
                         onChange: function (v) { MIN_CLEAR = v; draw(); }});
var seasonSel = ui.Select({items: ['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12'],
                           value: String(SEASON_START),
                           onChange: function (v) { SEASON_START = Number(v); draw(); }});
view.onChange(draw);
which.onChange(draw);

var panel = ui.Panel({style: {width: '440px'}});
panel.add(ui.Label('Time Profile', {fontWeight: 'bold', fontSize: '18px'}));
panel.add(ui.Label('Click the map or draw a polygon (pencil tool, top left of the map).'));
panel.add(ui.Panel([ui.Label('Data'), dataSel, ui.Label('Index'), indexSel], ui.Panel.Layout.flow('horizontal')));
panel.add(ui.Panel([ui.Label('From'), startBox, ui.Label('to'), endBox], ui.Panel.Layout.flow('horizontal')));
panel.add(ui.Label('Polygons: % of pixels that must be clear'));
panel.add(clearSl);
panel.add(ui.Panel([view, ui.Label('season starts in month'), seasonSel], ui.Panel.Layout.flow('horizontal')));
panel.add(which);
panel.add(ui.Panel([keep, ui.Button('Clear', function () { places = []; which.items().reset([]); draw();
                                                           markers.setEeObject(ee.FeatureCollection([])); }),
                    ui.Button('Export CSV', exportCsv)], ui.Panel.Layout.flow('horizontal')));
panel.add(status);
panel.add(chartBox);
ui.root.insert(0, panel);
Map.layers().add(markers);
Map.setCenter(CENTER[0], CENTER[1], CENTER[2]);
