// 放在 <head> 里同步执行的一小段：在页面绘制前就要定下来的事
(function () {
  // 应用上次手动选的主题；没选过就跟随系统
  try {
    var t = localStorage.getItem('theme');
    if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t;
  } catch (e) {}
  // 页面切换的过渡被浏览器跳过时（比如标签页在后台），会留下一条没人接的错误，这里接住
  function quiet(e) {
    var vt = e.viewTransition;
    if (!vt) return;
    [vt.ready, vt.finished, vt.updateCallbackDone].forEach(function (p) { if (p && p.catch) p.catch(function () {}); });
  }
  window.addEventListener('pagereveal', quiet);
  window.addEventListener('pageswap', quiet);
})();
