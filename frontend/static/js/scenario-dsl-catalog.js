// Shared live catalog for editor completion, lint and the DSL reference.
(function () {
  var metadata = {spiders: [], families: [], triggers: [], param_types: []};
  var node = document.getElementById('scenario-dsl-metadata');
  if (node) {
    try { metadata = JSON.parse(node.textContent) || metadata; }
    catch (error) { console.warn('[scenario-editor] invalid initial DSL metadata', error); }
  }
  window.arachneDslCatalog = {
    get: function () { return metadata; },
    set: function (value) { if (value) metadata = value; }
  };
})();
