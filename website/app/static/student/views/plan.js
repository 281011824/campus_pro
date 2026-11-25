/* 计划：学期目标（≤3，编辑/删除）、周计划、今日打卡 */
(function () {
  'use strict';
  var A = window.App;
  var $ = function (s, h) { return (h || document).querySelector(s); };
  var $all = function (s, h) {
    return Array.prototype.slice.call((h || document).querySelectorAll(s));
  };

  function pctOf(v) {
    var n = Number(v) || 0;
    if (n > 0 && n <= 1) { return Math.round(n * 100); }
    return Math.max(0, Math.min(100, Math.round(n)));
  }

  function render(el) {
    el.innerHTML = '<div class="hello"><h1>计划与打卡</h1>' +
      '<div class="id">目标不用多：最多三条，配上每周行动和今天的一小步。</div></div>' +
      '<div id="plan-body">' + A.skeleton(3) + '</div>';

    function paint(d) {
      d = d || {};
      var goals = d.goals || [];
      var checks = d.checks || [];
      var today = A.todayISO();
      var todayChecks = checks.filter(function (c) { return String(c.date || '').slice(0, 10) === today; });

      var html = '<div class="card"><div class="card-h"><h2>学期目标</h2>' +
        '<span class="meta">' + goals.length + '/3</span></div><div class="card-b">' +
        '<p class="sub" style="margin-bottom:8px">' + A.esc(d.term || '本学期') +
        ' · 目标少而具体，进度自己更新。</p>';

      if (goals.length) {
        html += goals.map(function (g) {
          var pct = pctOf(g.progress);
          return '<div class="goal"><div class="between"><div class="gtext">' + A.esc(g.text) + '</div>' +
            '<span class="chip">' + pct + '%</span></div>' +
            '<div class="bar"><i style="width:' + pct + '%"></i></div>' +
            '<div class="gacts">' +
            '<button type="button" class="btn sm" data-edit="' + A.esc(g.id) + '">编辑</button>' +
            '<button type="button" class="btn danger sm" data-del="' + A.esc(g.id) + '">删除</button>' +
            '</div></div>';
        }).join('');
      } else {
        html += '<p class="tiny">还没有学期目标，先写一条想做到的事。</p>';
      }

      if (goals.length < 3) {
        html += '<div class="form-row" style="margin-top:12px">' +
          '<input class="field" id="goal-input" maxlength="60" placeholder="一条本学期的目标（≤60 字）">' +
          '<button type="button" class="btn primary" id="goal-add">添加</button></div>';
      } else {
        html += '<p class="tiny" style="margin-top:10px">已满 3 条；想换目标请先删除一条。</p>';
      }
      html += '</div></div>';

      html += '<div class="card"><div class="card-h"><h2>周计划</h2>' +
        '<span class="meta">' + checks.length + ' 条</span></div><div class="card-b">' +
        (checks.length ? checks.map(function (c) {
          return '<div class="check' + (c.done ? ' done' : '') + '">' +
            '<span class="dot">' + (c.done ? '✓' : '') + '</span>' +
            '<div style="flex:1;min-width:0"><div class="ctext">' + A.esc(c.text || '计划事项') + '</div>' +
            '<div class="cdate">' + A.esc(A.fmtDate(c.date)) + '</div></div></div>';
        }).join('') : A.emptyHTML('本周还没有计划', '<p class="tiny" style="margin-top:4px">在下面写一句今天的行动，就是开始。</p>')) +
        '</div></div>';

      html += '<div class="card"><div class="card-h"><h2>今日打卡</h2>' +
        '<span class="meta">' + A.esc(today) + '</span></div><div class="card-b">' +
        (todayChecks.length ? '<div class="row" style="margin-bottom:8px">' +
          todayChecks.map(function (c) {
            return '<span class="chip ' + (c.done ? 'pos' : '') + '">' +
              A.esc(c.text) + (c.done ? ' ✓' : '') + '</span>';
          }).join('') + '</div>' : '') +
        '<div class="form-row"><input class="field" id="check-input" maxlength="40" ' +
        'placeholder="今天做了什么？例如：背完 20 个单词">' +
        '<button type="button" class="btn primary" id="check-add">打卡</button></div>' +
        '<p class="foot-note">打卡是给自己看的记录，不做公开比较。</p>' +
        '</div></div>';

      document.getElementById('plan-body').innerHTML = html;
      bind(goals);
    }

    function bind(goals) {
      var body = document.getElementById('plan-body');
      var add = $('#goal-add', body);
      if (add) {
        add.addEventListener('click', function () {
          var input = $('#goal-input', body);
          var text = (input.value || '').trim();
          if (text.length < 2) { A.toast('目标至少写 2 个字'); return; }
          add.disabled = true;
          A.post('/api/v1/student/plan/goals', { text: text }).then(function () {
            A.toast('已添加目标');
            load();
          }).catch(function (err) {
            add.disabled = false;
            A.toast((err && err.message) || '添加失败');
          });
        });
      }

      $all('[data-del]', body).forEach(function (btn) {
        btn.addEventListener('click', function () {
          if (!window.confirm('删除这条学期目标？')) { return; }
          btn.disabled = true;
          A.del('/api/v1/student/plan/goals/' + encodeURIComponent(btn.getAttribute('data-del')))
            .then(function () { A.toast('已删除'); load(); })
            .catch(function (err) {
              btn.disabled = false;
              A.toast((err && err.message) || '删除失败');
            });
        });
      });

      $all('[data-edit]', body).forEach(function (btn) {
        btn.addEventListener('click', function () {
          var id = btn.getAttribute('data-edit');
          var goal = null;
          goals.forEach(function (g) { if (String(g.id) === String(id)) { goal = g; } });
          if (!goal) { return; }
          var next = window.prompt('修改目标（保存后将替换原目标）', goal.text || '');
          if (next === null) { return; }
          next = next.trim();
          if (next.length < 2) { A.toast('目标至少写 2 个字'); return; }
          if (next === goal.text) { return; }
          btn.disabled = true;
          A.del('/api/v1/student/plan/goals/' + encodeURIComponent(id))
            .then(function () { return A.post('/api/v1/student/plan/goals', { text: next }); })
            .then(function () { A.toast('目标已更新'); load(); })
            .catch(function (err) {
              btn.disabled = false;
              A.toast((err && err.message) || '更新失败，请重试');
            });
        });
      });

      var checkAdd = $('#check-add', body);
      if (checkAdd) {
        checkAdd.addEventListener('click', function () {
          var input = $('#check-input', body);
          var text = (input.value || '').trim();
          if (!text) { A.toast('写一句今天做了什么'); return; }
          checkAdd.disabled = true;
          A.post('/api/v1/student/plan/checkin', { date: A.todayISO(), text: text })
            .then(function () {
              A.toast('打卡成功');
              load();
            })
            .catch(function (err) {
              checkAdd.disabled = false;
              A.toast((err && err.message) || '打卡失败');
            });
        });
      }
    }

    function load() {
      A.get('/api/v1/student/plan').then(function (d) {
        paint(d);
      }).catch(function (err) {
        var body = document.getElementById('plan-body');
        if (body) { A.renderError(body, err, load); }
      });
    }

    load();
  }

  window.Views = window.Views || {};
  window.Views.plan = { render: render };
})();
