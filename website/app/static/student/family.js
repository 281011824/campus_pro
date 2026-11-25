/* 家长端：绑定/登录 + 四页（首页 / 时间轴 / 画像 / 待办）
   - 家长会话独立，401 不回学生登录页，直接渲染登录/绑定表单
   - 只呈现正向成长与协同事项，不提供实时定位/聊天监看 */
(function () {
  'use strict';
  var A = window.App;
  var $ = function (s, h) { return (h || document).querySelector(s); };
  var $all = function (s, h) {
    return Array.prototype.slice.call((h || document).querySelectorAll(s));
  };

  var TITLES = {
    home: ['家长端', '孩子本周概况'],
    timeline: ['成长时间轴', '只收录正向记录'],
    profile: ['画像摘要', '需孩子授权'],
    todos: ['待配合事项', '学校的协同提醒']
  };
  var TYPE_NAME = {
    assess: '测评', homework: '作业', attendance: '考勤', plan: '计划',
    moral: '德育', remind: '提醒', positive: '正向记录', milestone: '里程碑'
  };

  var state = { authed: false, parentName: '' };

  function fapi(path, opts) {
    opts = opts || {};
    var method = opts.method || (opts.body !== undefined ? 'POST' : 'GET');
    var init = {
      method: method,
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' }
    };
    if (opts.body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(opts.body);
    }
    return fetch(path, init).then(function (res) {
      return res.text().then(function (raw) {
        var body = null;
        if (raw) {
          try { body = JSON.parse(raw); } catch (e) { body = null; }
        }
        if (res.status === 401) {
          return Promise.reject({ code: 401, message: '请先登录家长端' });
        }
        if (res.status === 403) {
          return Promise.reject({
            code: 403,
            message: (body && (body.message || body.error)) || '暂无权限查看'
          });
        }
        if (body && typeof body.code === 'number') {
          if (body.code !== 0) {
            return Promise.reject({ code: body.code, message: body.message || '请求失败' });
          }
          return body.data;
        }
        if (!res.ok) {
          return Promise.reject({ code: res.status, message: '请求失败（' + res.status + '）' });
        }
        return body;
      });
    }, function () {
      return Promise.reject({ code: 0, message: '网络异常，请检查连接后重试' });
    });
  }

  function chrome(on) {
    var bar = document.getElementById('tabbar');
    var foot = document.getElementById('family-foot');
    var out = document.getElementById('fam-logout');
    if (bar) { bar.hidden = !on; }
    if (foot) { foot.hidden = !on; }
    if (out) { out.hidden = !on; }
  }

  function setTitle(name) {
    var pair = TITLES[name] || TITLES.home;
    document.getElementById('app-title').textContent = pair[0];
    document.getElementById('app-sub').textContent = pair[1];
    document.title = pair[0] + ' · 京山市中等职业技术学校';
    A.setTab(name);
  }

  function first(obj, keys, fallback) {
    if (!obj) { return fallback; }
    for (var i = 0; i < keys.length; i++) {
      if (obj[keys[i]] !== undefined && obj[keys[i]] !== null) { return obj[keys[i]]; }
    }
    return fallback;
  }

  /* ---------------- 未登录：绑定 / 登录 ---------------- */
  function showLogin() {
    state.authed = false;
    chrome(false);
    setTitle('home');
    var el = document.getElementById('view');
    el.innerHTML = '<div class="hello"><h1>家长端</h1>' +
      '<div class="id">绑定孩子后，看到的是正向成长与协同事项；画像等增强内容需孩子授权。</div></div>' +
      '<div class="card"><div class="card-b">' +
      '<div class="seg" id="fam-mode">' +
      '<button type="button" data-mode="login" class="on">登录</button>' +
      '<button type="button" data-mode="bind">绑定孩子</button></div>' +
      '<div id="fam-form"></div>' +
      '<div id="fam-msg"></div>' +
      '</div></div>' +
      '<div class="card"><div class="card-b">' +
      '<h2 style="font-size:15px;margin-bottom:6px">怎么绑定孩子？</h2>' +
      '<p class="tiny">1. 孩子在「隐私与数据权利」页生成绑定码（短时有效）；</p>' +
      '<p class="tiny">2. 您在这个页面选择「绑定孩子」，填写学号、绑定码并设置密码；</p>' +
      '<p class="tiny">3. 绑定成功后，用学号 + 密码登录即可。</p>' +
      '<p class="foot-note">家长端只呈现正向成长信息与协同事项，不提供实时定位、聊天记录等监看功能。</p>' +
      '</div></div>';

    function formFor(mode) {
      var box = document.getElementById('fam-form');
      if (mode === 'bind') {
        box.innerHTML = '<form id="fam-form-el" autocomplete="off">' +
          '<div style="margin-bottom:10px"><input class="field" name="student_no" ' +
          'placeholder="孩子学号" inputmode="numeric" maxlength="20" required></div>' +
          '<div style="margin-bottom:10px"><input class="field" name="code" ' +
          'placeholder="绑定码" maxlength="12" required></div>' +
          '<div style="margin-bottom:10px"><input class="field" name="password" type="password" ' +
          'placeholder="设置登录密码（至少 6 位）" minlength="6" required></div>' +
          '<button type="submit" class="btn primary block">绑定并登录</button></form>';
      } else {
        box.innerHTML = '<form id="fam-form-el" autocomplete="off">' +
          '<div style="margin-bottom:10px"><input class="field" name="student_no" ' +
          'placeholder="孩子学号" inputmode="numeric" maxlength="20" required></div>' +
          '<div style="margin-bottom:10px"><input class="field" name="password" type="password" ' +
          'placeholder="登录密码" required></div>' +
          '<button type="submit" class="btn primary block">登录</button></form>';
      }
      document.getElementById('fam-form-el').addEventListener('submit', function (e) {
        e.preventDefault();
        submit(mode, e.target);
      });
    }

    function submit(mode, form) {
      var msg = document.getElementById('fam-msg');
      var btn = $('button[type="submit"]', form);
      var studentNo = (form.student_no.value || '').trim();
      var password = form.password.value || '';
      if (!studentNo) { msg.innerHTML = '<div class="hintbox">请填写孩子学号</div>'; return; }
      if (mode === 'bind') {
        var code = (form.code.value || '').trim();
        if (!code) { msg.innerHTML = '<div class="hintbox">请填写孩子提供的绑定码</div>'; return; }
        if (password.length < 6) { msg.innerHTML = '<div class="hintbox">密码至少 6 位</div>'; return; }
      }
      btn.disabled = true;
      msg.innerHTML = '<p class="tiny" style="margin-top:10px">正在提交…</p>';

      var req = mode === 'bind'
        ? fapi('/api/v1/family/bind', { body: { student_no: studentNo, code: code, password: password } })
        : fapi('/api/v1/family/login', { body: { student_no: studentNo, password: password } });

      req.then(function (d) {
        state.authed = true;
        state.parentName = (d && (d.parent_name || d.name)) || '';
        chrome(true);
        try { history.replaceState(null, '', '#/home'); } catch (e) { location.hash = '#/home'; }
        renderRoute('home');
        A.toast(mode === 'bind' ? '绑定成功' : '登录成功');
      }).catch(function (err) {
        btn.disabled = false;
        msg.innerHTML = '<div class="hintbox">' + A.esc((err && err.message) || '提交失败，请重试') + '</div>';
      });
    }

    $all('#fam-mode button', el).forEach(function (btn) {
      btn.addEventListener('click', function () {
        var mode = btn.getAttribute('data-mode');
        $all('#fam-mode button', el).forEach(function (b) { b.classList.remove('on'); });
        btn.classList.add('on');
        formFor(mode);
      });
    });
    formFor('login');
  }

  /* ---------------- 首页 ---------------- */
  function pageHome() {
    var el = document.getElementById('view');
    el.innerHTML = A.skeleton(3);
    fapi('/api/v1/family/home').then(function (d) {
      d = d || {};
      var child = d.student || d.child || d.profile || {};
      var week = d.week || d;
      var assess = d.assess || d.assessment || {};
      var moralDelta = first(week, ['moral_delta', 'week_delta', 'moral_score'], null);
      var attendance = first(week, ['attendance_rate', 'attend_rate'], null);
      var homework = first(week, ['homework_rate', 'submit_rate'], null);
      var assessDone = first(assess, ['done', 'completed'], first(d, ['assess_done'], null));
      var assessTotal = first(assess, ['total', 'count'], first(d, ['assess_total'], null));
      var todoCount = first(d, ['todos_count', 'todo_count', 'pending_todos'], null);
      var name = child.name || d.student_name || '孩子';
      var cls = child.class_name || d.class_name || '';

      var html = '<div class="hello"><h1>' + A.esc(name) + ' 的成长概况</h1>' +
        '<div class="id">' + A.esc(cls || '班级待同步') +
        (state.parentName ? ' · ' + A.esc(state.parentName) : '') + '</div>' +
        '<div class="date"><span class="chip outline">' + A.todayISO() + '</span></div></div>';

      html += '<div class="grid2">' +
        '<div class="chan"><div class="ch-name">本周德育净分</div>' +
        '<div class="ch-val">' + A.na(moralDelta, ' 分') + '</div></div>' +
        '<div class="chan"><div class="ch-name">本周出勤率</div>' +
        '<div class="ch-val">' + A.na(attendance, '%') + '</div></div>' +
        '<div class="chan"><div class="ch-name">作业提交率</div>' +
        '<div class="ch-val">' + A.na(homework, '%') + '</div></div>' +
        '<div class="chan"><div class="ch-name">测评进度</div>' +
        '<div class="ch-val">' + A.na(assessDone, '') + '<small>/ ' + A.na(assessTotal, '') + '</small></div></div>' +
        '</div>';

      html += '<div class="card"><div class="card-h"><h2>本周协同</h2></div><div class="card-b">' +
        '<div class="between" style="padding:8px 0;border-bottom:1px solid var(--line)">' +
        '<span class="tiny">待配合事项</span><b>' + (todoCount == null ? '暂不可用' : todoCount + ' 项') + '</b></div>' +
        '<p class="tiny" style="margin-top:10px">家长端只呈现正向成长与协同事项；孩子的画像等增强内容需孩子本人授权。</p>' +
        '<div class="row" style="margin-top:12px">' +
        '<a class="btn ghost sm" href="#/timeline">成长时间轴</a>' +
        '<a class="btn ghost sm" href="#/profile">画像摘要</a>' +
        '<a class="btn ghost sm" href="#/todos">待配合</a>' +
        '</div></div></div>';

      el.innerHTML = html;
    }).catch(function (err) {
      if (err && err.code === 401) { showLogin(); return; }
      A.renderError(el, err, pageHome);
    });
  }

  /* ---------------- 时间轴 ---------------- */
  function pageTimeline() {
    var el = document.getElementById('view');
    el.innerHTML = A.skeleton(3);
    fapi('/api/v1/family/timeline').then(function (d) {
      d = d || {};
      var items = d.items || d.records || d.events || [];
      var html = '<div class="hello"><h1>成长时间轴</h1>' +
        '<div class="id">只收录孩子的正向成长记录（表扬、进步、获奖、志愿服务等）。</div></div>';
      if (!items.length) {
        html += '<div class="card"><div class="empty"><div class="eic">🌱</div>' +
          '<p>还没有正向记录</p><p class="tiny" style="margin-top:4px">孩子仍在稳步前行，有新的闪光点会出现在这里。</p></div></div>';
      } else {
        html += '<div class="card"><div class="card-b">' + items.map(function (it) {
          var title = it.title || it.fact || TYPE_NAME[it.type] || '成长记录';
          return '<div class="rowitem"><div class="body"><div class="between"><b>' +
            A.esc(title) + '</b><span class="tiny">' + A.esc(A.fmtDate(it.date || it.at)) + '</span></div>' +
            (it.detail ? '<p>' + A.esc(it.detail) + '</p>' : '') +
            '<div class="tiny" style="margin-top:2px">' + A.esc(TYPE_NAME[it.type] || '记录') + '</div>' +
            '</div></div>';
        }).join('') + '</div></div>';
      }
      el.innerHTML = html;
    }).catch(function (err) {
      if (err && err.code === 401) { showLogin(); return; }
      A.renderError(el, err, pageTimeline);
    });
  }

  /* ---------------- 画像摘要 ---------------- */
  function pageProfile() {
    var el = document.getElementById('view');
    el.innerHTML = A.skeleton(3);
    fapi('/api/v1/family/profile').then(function (d) {
      d = d || {};
      var content = d.content || d;
      var tags = Array.isArray(content.tags) ? content.tags : [];
      var radar = content.radar || content.dimensions || null;
      var advice = Array.isArray(content.advice) ? content.advice : [];
      var plain = content.plain || [];
      if (!Array.isArray(plain)) { plain = plain ? [String(plain)] : []; }

      if (!tags.length && !radar && !advice.length && !plain.length) {
        el.innerHTML = '<div class="card"><div class="empty"><div class="eic">🔒</div>' +
          '<p>孩子尚未向您开放画像</p>' +
          '<p class="tiny" style="margin-top:4px">画像由孩子决定是否开放、开放哪些部分、开放多久；' +
          '基础情况（测评进度、正向记录、待配合）不受影响。</p></div></div>';
        return;
      }

      var rangeNames = d.range_names || content.range_names || d.rangeNames || content.rangeNames;
      var rangeText = Array.isArray(rangeNames) ? rangeNames.join('＋') :
        (rangeNames ? String(rangeNames) : '');
      var masked = d.student_masked || content.student_masked || d.name || content.name || '孩子';

      var html = '<div class="hello"><h1>画像摘要</h1>' +
        '<div class="id">' + A.esc(masked) +
        (rangeText ? ' · 已授权：' + A.esc(rangeText) : '') + '</div>' +
        (d.expires_at ? '<div class="date"><span class="chip outline">授权至 ' +
          A.esc(A.fmtDate(d.expires_at)) + '</span></div>' : '') + '</div>';

      if (plain.length) {
        html += '<div class="card"><div class="card-h"><h2>白话版</h2></div><div class="card-b">' +
          plain.map(function (s) { return '<p class="tiny" style="margin-bottom:4px">' + A.esc(s) + '</p>'; }).join('') +
          '</div></div>';
      }

      if (tags.length) {
        html += '<div class="card"><div class="card-h"><h2>成长标签</h2></div><div class="card-b"><div class="row">' +
          tags.map(function (t) {
            var name = String(t.dim || t.name || t.key || '').split(':').pop();
            var isDev = t.type === 'develop' || t.type === 'weak';
            return '<span class="chip ' + (isDev ? 'warn' : 'pos') + '">' +
              (isDev ? '待发展 · ' : '优势 · ') + A.esc(name) + '</span>';
          }).join('') + '</div></div></div>';
      }

      if (radar) {
        var keys = Object.keys(radar);
        html += '<div class="card"><div class="card-h"><h2>维度概览</h2></div><div class="card-b">' +
          keys.map(function (k) {
            var v = Math.max(0, Math.min(100, Number(radar[k]) || 0));
            return '<div class="dim"><span class="name">' + A.esc(String(k).split(':').pop()) + '</span>' +
              '<div class="bar"><i style="width:' + v + '%"></i></div>' +
              '<span class="val">' + v + '</span></div>';
          }).join('') + '</div></div>';
      }

      if (advice.length) {
        html += '<div class="card"><div class="card-h"><h2>发展建议</h2></div><div class="card-b">' +
          advice.slice(0, 5).map(function (a) {
            var text = typeof a === 'string' ? a : (a.text || a.content || '');
            return '<div class="rowitem"><div class="body"><p>' + A.esc(text) + '</p></div></div>';
          }).join('') + '</div></div>';
      }

      html += '<p class="foot-note">以上内容由孩子授权展示，孩子可随时撤销。</p>';
      el.innerHTML = html;
    }).catch(function (err) {
      if (err && err.code === 401) { showLogin(); return; }
      if (err && err.code === 403) {
        el.innerHTML = '<div class="card"><div class="empty"><div class="eic">🔒</div>' +
          '<p>孩子尚未向您开放画像</p>' +
          '<p class="tiny" style="margin-top:4px">这是孩子的数据权利；基础情况仍可正常查看。</p>' +
          '<a class="btn ghost" href="#/home" style="margin-top:12px">回首页</a></div></div>';
        return;
      }
      A.renderError(el, err, pageProfile);
    });
  }

  /* ---------------- 待配合事项 ---------------- */
  function pageTodos() {
    var el = document.getElementById('view');
    el.innerHTML = A.skeleton(2);
    fapi('/api/v1/family/todos').then(function (d) {
      d = d || {};
      var items = d.items || [];
      var html = '<div class="hello"><h1>待配合事项</h1>' +
        '<div class="id">学校发起的协同提醒；危机类只显示固定提示文案。</div></div>';
      if (!items.length) {
        html += '<div class="card"><div class="empty"><div class="eic">✅</div>' +
          '<p>暂无待配合事项</p></div></div>';
      } else {
        html += '<div class="card"><div class="card-b">' + items.map(function (it) {
          var crisis = it.kind === 'crisis' || it.type === 'crisis';
          return '<div class="todo-item' + (crisis ? '' : ' t-plan') + '"><span class="tl-bar"></span>' +
            '<div class="tbody"><div class="between"><b>' +
            A.esc(crisis ? '请尽快联系班主任' : (it.title || '待配合')) + '</b>' +
            (it.state ? '<span class="badge ' + (it.state === 'done' ? 'ok' : 'warn') + '">' +
              A.esc(it.state === 'done' ? '已完成' : '待处理') + '</span>' : '') + '</div>' +
            (it.content || it.meta ? '<p>' + A.esc(it.content || it.meta) + '</p>' : '') +
            (it.due || it.at ? '<p class="tiny" style="margin-top:2px">' +
              A.esc(A.fmtDT(it.due || it.at)) + '</p>' : '') +
            '</div></div>';
        }).join('') + '</div></div>';
      }
      el.innerHTML = html;
    }).catch(function (err) {
      if (err && err.code === 401) { showLogin(); return; }
      A.renderError(el, err, pageTodos);
    });
  }

  /* ---------------- 路由 ---------------- */
  function parseName() {
    var raw = String(location.hash || '').replace(/^#\/?/, '').split('?')[0];
    var name = raw.split('/')[0] || 'home';
    return TITLES[name] ? name : 'home';
  }

  function renderRoute(name) {
    if (!state.authed) { showLogin(); return; }
    name = name || parseName();
    chrome(true);
    setTitle(name);
    window.scrollTo(0, 0);
    if (name === 'timeline') { pageTimeline(); return; }
    if (name === 'profile') { pageProfile(); return; }
    if (name === 'todos') { pageTodos(); return; }
    pageHome();
  }

  function boot() {
    var bar = document.getElementById('tabbar');
    if (!bar) { return; }
    $all('button', bar).forEach(function (btn) {
      btn.addEventListener('click', function () {
        var tab = btn.getAttribute('data-tab');
        if (location.hash === '#/' + tab) { renderRoute(tab); return; }
        location.hash = '#/' + tab;
      });
    });
    window.addEventListener('hashchange', function () {
      if (!state.authed) { return; }
      renderRoute(parseName());
    });

    var logout = document.getElementById('fam-logout');
    if (logout) {
      logout.addEventListener('click', function () {
        if (!window.confirm('退出家长端登录？')) { return; }
        logout.disabled = true;
        fapi('/api/v1/family/logout', { method: 'POST', body: {} }).catch(function () {
          return null;
        }).then(function () {
          logout.disabled = false;
          state.authed = false;
          chrome(false);
          try { history.replaceState(null, '', '#/home'); } catch (e) { /* ignore */ }
          showLogin();
          A.toast('已退出');
        });
      });
    }

    // 服务端已判定会话：未登录页不发起 /family/home，避免控制台出现预期内的 403
    var authedHint = document.body.getAttribute('data-authed') === '1';
    if (!authedHint) {
      showLogin();
      return;
    }
    fapi('/api/v1/family/home').then(function (d) {
      state.authed = true;
      state.home = d;
      chrome(true);
      renderRoute(parseName());
    }).catch(function () {
      showLogin();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
