/* 我的待办：按类型分组、完成/忽略、空态 */
(function () {
  'use strict';
  var A = window.App;
  var $all = function (s, h) {
    return Array.prototype.slice.call((h || document).querySelectorAll(s));
  };

  var TYPE_NAME = {
    assess: '测评', homework: '作业', attendance: '考勤', plan: '计划',
    moral: '德育', remind: '提醒'
  };
  var ORDER = ['assess', 'homework', 'attendance', 'plan', 'moral', 'remind'];

  function typeLabel(t) { return TYPE_NAME[t] || '其他'; }
  function stateText(s) {
    if (s === 'done' || s === 'completed') { return { text: '已完成', cls: 'ok' }; }
    if (s === 'ignored') { return { text: '已忽略', cls: 'none' }; }
    return { text: '待完成', cls: 'warn' };
  }

  function render(el) {
    el.innerHTML = '<div class="hello"><h1>我的待办</h1>' +
      '<div class="id">老师催办与系统任务都在这里；完成后自动消卡。</div></div>' +
      '<div id="todo-body">' + A.skeleton(2) + '</div>';

    function paint(items) {
      var body = document.getElementById('todo-body');
      if (!body) { return; }
      if (!items.length) {
        body.innerHTML = '<div class="card"><div class="empty"><div class="eic">✅</div>' +
          '<p>今天没有待办</p><p class="tiny" style="margin-top:4px">去定个小目标，或完成一项测评吧。</p>' +
          '<a class="btn ghost" href="#/plan" style="margin-top:12px">去计划</a></div></div>';
        return;
      }
      var groups = {};
      items.forEach(function (it) {
        var t = it.type || 'other';
        if (!groups[t]) { groups[t] = []; }
        groups[t].push(it);
      });
      var keys = Object.keys(groups).sort(function (a, b) {
        var ia = ORDER.indexOf(a); var ib = ORDER.indexOf(b);
        if (ia < 0) { ia = 99; }
        if (ib < 0) { ib = 99; }
        return ia - ib;
      });
      var html = '';
      keys.forEach(function (t) {
        var list = groups[t];
        html += '<div class="card"><div class="card-h"><h2>' + A.esc(typeLabel(t)) + '</h2>' +
          '<span class="meta">' + list.length + ' 项</span></div><div class="card-b">' +
          list.map(function (it) {
            var stt = stateText(it.state);
            var pending = stt.text === '待完成';
            return '<div class="todo-item t-' + A.esc(it.type || 'other') + (pending ? '' : ' done') + '">' +
              '<span class="tl-bar"></span><div class="tbody">' +
              '<div class="between"><b>' + A.esc(it.title || '待办事项') + '</b>' +
              '<span class="badge ' + stt.cls + '">' + stt.text + '</span></div>' +
              (it.meta ? '<p>' + A.esc(it.meta) + '</p>' : '') +
              (it.due ? '<p>截止 ' + A.esc(A.fmtDT(it.due)) + '</p>' : '') +
              (pending ? '<div class="tacts">' +
                '<button type="button" class="btn primary sm" data-act="done" data-id="' + A.esc(it.id) + '">完成</button>' +
                '<button type="button" class="btn sm" data-act="ignore" data-id="' + A.esc(it.id) + '">忽略</button>' +
                '</div>' : '') +
              '</div></div>';
          }).join('') + '</div></div>';
      });
      body.innerHTML = html;

      $all('[data-act]', body).forEach(function (btn) {
        btn.addEventListener('click', function () {
          var act = btn.getAttribute('data-act');
          var id = btn.getAttribute('data-id');
          if (!id) { return; }
          btn.disabled = true;
          A.post('/api/v1/student/todos/' + encodeURIComponent(id) + '/' + act)
            .then(function () {
              A.toast(act === 'done' ? '已完成' : '已忽略');
              load();
            })
            .catch(function (err) {
              btn.disabled = false;
              A.toast((err && err.message) || '操作失败');
            });
        });
      });
    }

    function load() {
      A.get('/api/v1/student/todos').then(function (d) {
        paint((d && d.items) || []);
      }).catch(function (err) {
        var body = document.getElementById('todo-body');
        if (body) { A.renderError(body, err, load); }
      });
    }

    load();
  }

  window.Views = window.Views || {};
  window.Views.todo = { render: render };
})();
