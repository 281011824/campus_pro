/* 批次进度：历史批次与完成度 */
(function () {
  'use strict';
  var A = window.App;

  function doneOf(s) {
    var raw = s.status;
    var answered = Number(s.answered) || 0;
    var total = Number(s.total) || 0;
    return raw === 2 || raw === 'done' || raw === 'completed' || raw === 'finished' ||
      (total > 0 && answered >= total);
  }

  function batchCard(b) {
    var scales = b.scales || [];
    var done = 0;
    scales.forEach(function (s) { if (doneOf(s)) { done++; } });
    var pct = scales.length ? Math.round(done / scales.length * 100) : 0;
    var rows = scales.map(function (s) {
      var ok = doneOf(s);
      return '<div class="rowitem"><div class="body"><b>' + A.esc(s.title || s.code) + '</b>' +
        '<p>' + (s.total ? '已答 ' + (Number(s.answered) || 0) + '/' + s.total : '未开始作答') + '</p></div>' +
        '<span class="badge ' + (ok ? 'ok' : 'info') + '">' + (ok ? '已完成' : '未完成') + '</span></div>';
    }).join('');
    return '<div class="card"><div class="card-h"><h2>' + A.esc(b.name || '施测批次') + '</h2>' +
      '<span class="meta">' + done + '/' + scales.length + '</span></div>' +
      '<div class="card-b"><div class="sub">' + A.esc(A.fmtDate(b.start_at)) + ' 至 ' +
      A.esc(A.fmtDate(b.end_at)) + ' · 完成度 ' + pct + '%</div>' +
      '<div class="bar"><i style="width:' + pct + '%"></i></div>' +
      (rows || A.emptyHTML('本批次暂无量表')) + '</div></div>';
  }

  function render(el) {
    el.innerHTML = A.skeleton(3);

    function load() {
      A.get('/api/v1/student/assess').then(function (d) {
        var batches = (d && d.batches) || [];
        if (!batches.length) {
          el.innerHTML = '<div class="card"><div class="empty"><div class="eic">📅</div>' +
            '<p>暂无历史批次</p><p class="tiny" style="margin-top:4px">学校开放测评后，这里会记录每批的完成情况。</p>' +
            '</div></div>';
          return;
        }
        var html = '<div class="hello"><h1>批次进度</h1>' +
          '<div class="id">' + A.esc((d && d.term) || '本学期') +
          ' · 按批次查看量表完成度</div></div>';
        batches.forEach(function (b) { html += batchCard(b); });
        html += '<div class="row" style="justify-content:center;margin:4px 0 10px">' +
          '<a class="btn ghost" href="#/assess">去测评中心</a></div>';
        el.innerHTML = html;
      }).catch(function (err) {
        A.renderError(el, err, load);
      });
    }

    load();
  }

  window.Views = window.Views || {};
  window.Views.batch = { render: render };
})();
