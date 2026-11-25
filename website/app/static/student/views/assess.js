/* 测评中心：本学期批次 + 量表状态徽标 + 入口 */
(function () {
  'use strict';
  var A = window.App;

  function statusOf(s) {
    var raw = s.status;
    var answered = Number(s.answered) || 0;
    var total = Number(s.total) || 0;
    var done = raw === 2 || raw === 'done' || raw === 'completed' || raw === 'finished' ||
      (total > 0 && answered >= total);
    if (done) { return { text: '已完成', cls: 'ok' }; }
    var doing = raw === 1 || raw === 'doing' || raw === 'in_progress' || raw === 'saved' ||
      answered > 0 || !!s.assessment_id;
    if (doing) { return { text: '进行中', cls: 'warn' }; }
    return { text: '未开始', cls: 'info' };
  }

  function scaleRow(s) {
    var st = statusOf(s);
    var progress = '';
    if (s.total) {
      progress = ' · 已答 ' + (Number(s.answered) || 0) + '/' + s.total;
    } else if (s.minutes) {
      progress = ' · 约 ' + s.minutes + ' 分钟';
    }
    var action = st.text === '已完成'
      ? '<span class="tiny">已计入画像</span>'
      : '<a class="btn ghost sm" href="#/quiz/' + encodeURIComponent(s.code) + '">' +
        (st.text === '进行中' ? '继续作答' : '开始测评') + '</a>';
    return '<div class="scale"><div class="between">' +
      '<div><div class="st">' + A.esc(s.title || s.code) + '</div>' +
      '<div class="sd">' + A.esc(String(progress).replace(/^ · /, '')) + '</div></div>' +
      '<span class="badge ' + st.cls + '">' + st.text + '</span></div>' +
      '<div class="sa">' + action + '</div></div>';
  }

  function batchCard(b) {
    var scales = b.scales || [];
    var done = 0;
    scales.forEach(function (s) { if (statusOf(s).text === '已完成') { done++; } });
    var pct = scales.length ? Math.round(done / scales.length * 100) : 0;
    return '<div class="card"><div class="card-h"><h2>' + A.esc(b.name || '施测批次') + '</h2>' +
      '<span class="meta">' + done + '/' + scales.length + ' 完成</span></div>' +
      '<div class="card-b"><div class="sub">' +
      A.esc(A.fmtDate(b.start_at)) + ' 至 ' + A.esc(A.fmtDate(b.end_at)) + '</div>' +
      '<div class="bar"><i style="width:' + pct + '%"></i></div>' +
      '<div style="margin-top:6px">' + (scales.length ? scales.map(scaleRow).join('') :
        A.emptyHTML('本批次暂无量表')) + '</div></div></div>';
  }

  function render(el) {
    el.innerHTML = A.skeleton(3);

    function load() {
      A.get('/api/v1/student/assess').then(function (d) {
        var batches = (d && d.batches) || [];
        if (!batches.length) {
          el.innerHTML = '<div class="card"><div class="empty"><div class="eic">📋</div>' +
            '<p>本学期暂无测评</p><p class="tiny" style="margin-top:4px">老师开放后，这里会出现待完成的量表。</p>' +
            '</div></div>';
          return;
        }
        var html = '<div class="hello"><h1>测评中心</h1>' +
          '<div class="id">' + A.esc((d && d.term) || '本学期') +
          ' · 真实作答，没有对错；结果先给你自己看</div></div>';
        batches.forEach(function (b) { html += batchCard(b); });
        html += '<div class="foot-note">兴趣与多元智能为校本自编简版；量表结果只用于生成你自己的画像，不公开排名。</div>';
        el.innerHTML = html;
      }).catch(function (err) {
        A.renderError(el, err, load);
      });
    }

    load();
  }

  window.Views = window.Views || {};
  window.Views.assess = { render: render };
})();
