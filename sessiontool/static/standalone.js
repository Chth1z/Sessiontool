(function () {
  'use strict';
  var only = document.getElementById('onlychat');
  only.onchange = function () { document.body.classList.toggle('chat', only.checked); };
  document.querySelector('[data-act="tools"]').onclick = function () {
    var all = [].slice.call(document.querySelectorAll('details.tools'));
    var open = !all.some(function (x) { return x.open; });
    all.forEach(function (x) { x.open = open; });
  };
})();
