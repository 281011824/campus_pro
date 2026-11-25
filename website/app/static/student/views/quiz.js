/* 答题：一屏一题、进度、上一题/下一题、自动暂存、提交二次确认、可续答 */
(function () {
  'use strict';
  var A = window.App;
  var $ = function (s, h) { return (h || document).querySelector(s); };
  var $all = function (s, h) {
    return Array.prototype.slice.call((h || document).querySelectorAll(s));
  };

  function optText(opt) {
    if (typeof opt === 'string') { return opt; }
    if (opt && typeof opt === 'object') { return opt.label || opt.text || opt.title || String(opt.value || ''); }
    return String(opt == null ? '' : opt);
  }

  function render(el, params) {
    var code = params && params.code;
    if (!code) {
      el.innerHTML = '<div class="card"><div class="error"><div class="etitle">未指定量表</div>' +
        '<p>请从测评中心选择一项量表。</p><a class="btn ghost" href="#/assess">回测评中心</a></div></div>';
      return;
    }
    el.innerHTML = A.skeleton(3);

    var state = {
      aid: null, title: '', items: [], answers: {}, idx: 0,
      timer: null, busy: false, exited: false
    };

    A.post('/api/v1/student/assess/' + encodeURIComponent(code) + '/start').then(function (start) {
      if (!start || !start.assessment_id) { throw { message: '无法开始作答，请稍后重试' }; }
      state.aid = start.assessment_id;
      return A.get('/api/v1/student/assess/' + state.aid + '/items');
    }).then(function (d) {
      d = d || {};
      state.title = d.title || '量表';
      state.items = d.items || [];
      var ans = d.answers || {};
      Object.keys(ans).forEach(function (k) { state.answers[k] = ans[k]; });
      if (!state.items.length) {
        el.innerHTML = '<div class="card"><div class="empty"><div class="eic">📝</div>' +
          '<p>本量表暂无题目</p><a class="btn ghost" href="#/assess" style="margin-top:12px">回测评中心</a></div></div>';
        return;
      }
      for (var i = 0; i < state.items.length; i++) {
        if (state.answers[state.items[i].no] == null) { state.idx = i; break; }
      }
      paintShell();
    }).catch(function (err) {
      A.renderError(el, err, function () { render(el, params); });
    });

    function answeredCount() {
      var n = 0;
      state.items.forEach(function (it) {
        if (state.answers[it.no] != null) { n++; }
      });
      return n;
    }
    function remaining() { return state.items.length - answeredCount(); }

    function setHint(text) {
      var h = $('#q-hint', el);
      if (h) { h.textContent = text || ''; }
    }

    function flush() {
      if (!state.aid || state.exited) { return Promise.resolve(); }
      return A.put('/api/v1/student/assess/' + state.aid + '/answers', {
        answers: state.answers
      }).then(function () {
        var d = new Date();
        var hh = ('0' + d.getHours()).slice(-2);
        var mm = ('0' + d.getMinutes()).slice(-2);
        setHint('已暂存 · ' + hh + ':' + mm + '（退出后可继续作答）');
      });
    }

    function scheduleSave() {
      clearTimeout(state.timer);
      setHint('正在暂存…');
      state.timer = setTimeout(function () {
        flush().catch(function (err) {
          setHint('暂存失败：' + ((err && err.message) || '请检查网络'));
        });
      }, 700);
    }

    function updateProgress() {
      var total = state.items.length;
      var done = answeredCount();
      var noEl = $('#q-no', el);
      if (noEl) { noEl.textContent = String(state.idx + 1); }
      var countEl = $('#q-count', el);
      if (countEl) { countEl.textContent = '第 ' + (state.idx + 1) + '/' + total + ' 题'; }
      var leftEl = $('#q-left', el);
      if (leftEl) { leftEl.textContent = '已答 ' + done + '/' + total; }
      var bar = $('#q-bar', el);
      if (bar) { bar.style.width = (total ? done / total * 100 : 0) + '%'; }
      var prev = $('#q-prev', el);
      var next = $('#q-next', el);
      if (prev) { prev.disabled = state.idx === 0; }
      if (next) {
        if (state.idx >= total - 1) {
          next.textContent = remaining() > 0 ? '还差 ' + remaining() + ' 题' : '提交';
          next.classList.toggle('primary', remaining() === 0);
        } else {
          next.textContent = '下一题';
          next.classList.add('primary');
        }
      }
    }

    function paintQuestion() {
      var item = state.items[state.idx];
      var area = $('#qarea', el);
      if (!item || !area) { return; }
      var current = state.answers[item.no];
      var opts = (item.options || []).map(function (opt, i) {
        var val = i + 1;
        var on = Number(current) === val;
        return '<button type="button" class="opt' + (on ? ' on' : '') + '" data-opt="' + val + '">' +
          A.esc(optText(opt)) + '</button>';
      }).join('');
      area.innerHTML = '<div class="stem">' + A.esc(item.no) + '. ' + A.esc(item.stem) + '</div>' +
        '<div class="opts">' + opts + '</div>';
      $all('.opt', area).forEach(function (btn) {
        btn.addEventListener('click', function () {
          state.answers[item.no] = Number(btn.getAttribute('data-opt'));
          $all('.opt', area).forEach(function (b) { b.classList.remove('on'); });
          btn.classList.add('on');
          updateProgress();
          scheduleSave();
        });
      });
      updateProgress();
    }

    function paintShell() {
      el.innerHTML = '<div class="card">' +
        '<div class="card-h"><h2>' + A.esc(state.title) + '</h2><span class="meta" id="q-count"></span></div>' +
        '<div class="card-b">' +
        '<div class="quiz-progress"><span>第 <b id="q-no">1</b>/' + state.items.length + ' 题</span>' +
        '<span id="q-left"></span></div>' +
        '<div class="bar"><i id="q-bar" style="width:0%"></i></div>' +
        '<div id="qarea"></div>' +
        '<div class="save-hint" id="q-hint"></div>' +
        '<div class="quiz-nav">' +
        '<button type="button" class="btn" id="q-prev">上一题</button>' +
        '<button type="button" class="btn primary" id="q-next">下一题</button>' +
        '</div>' +
        '<p class="tiny" style="margin-top:10px;text-align:center">' +
        '<a href="#/assess" id="q-exit">保存进度，稍后继续</a></p>' +
        '</div></div>' +
        '<p class="tiny" style="text-align:center">每答一题自动暂存；真实作答、没有对错，结果先给你自己看。</p>';

      paintQuestion();

      $('#q-prev', el).addEventListener('click', function () {
        if (state.idx > 0) {
          state.idx--;
          paintQuestion();
        }
      });

      $('#q-next', el).addEventListener('click', function () {
        if (state.idx < state.items.length - 1) {
          flush().catch(function () {});
          state.idx++;
          paintQuestion();
          return;
        }
        if (remaining() > 0) {
          A.toast('还有 ' + remaining() + ' 题未作答');
          return;
        }
        submit();
      });

      $('#q-exit', el).addEventListener('click', function (e) {
        e.preventDefault();
        clearTimeout(state.timer);
        flush().catch(function () {}).then(function () {
          state.exited = true;
          A.go('#/assess');
        });
      });
    }

    function submit() {
      if (state.busy) { return; }
      if (!window.confirm('确认提交？提交后不能再修改。')) { return; }
      state.busy = true;
      clearTimeout(state.timer);
      setHint('正在提交…');
      A.put('/api/v1/student/assess/' + state.aid + '/answers', { answers: state.answers })
        .then(function () {
          return A.post('/api/v1/student/assess/' + state.aid + '/submit');
        })
        .then(function (result) {
          state.exited = true;
          el.innerHTML = '<div class="card"><div class="card-b" style="text-align:center;padding:26px 16px">' +
            '<div style="font-size:40px;line-height:1">🎉</div>' +
            '<h2 style="margin-top:10px;font-size:17px">提交完成，已计入画像</h2>' +
            '<p class="tiny" style="margin-top:6px">' + A.esc(state.title) + '</p>' +
            scoreChips(result) +
            '<div class="row" style="justify-content:center;margin-top:16px">' +
            '<a class="btn primary" href="#/profile">看画像</a>' +
            '<a class="btn ghost" href="#/assess">回测评</a></div></div></div>';
        })
        .catch(function (err) {
          state.busy = false;
          setHint('提交失败：' + ((err && err.message) || '请稍后重试'));
          A.toast((err && err.message) || '提交失败，请稍后重试');
        });
    }

    function scoreChips(result) {
      var scores = result && result.scores;
      if (!scores || typeof scores !== 'object') { return ''; }
      var keys = Object.keys(scores);
      if (!keys.length) { return ''; }
      return '<div class="row" style="justify-content:center;margin-top:12px">' +
        keys.map(function (k) {
          return '<span class="chip pos">' + A.esc(k) + ' ' + A.esc(scores[k]) + '</span>';
        }).join('') + '</div>';
    }
  }

  window.Views = window.Views || {};
  window.Views.quiz = { render: render };
})();
