/* 学生成长门户 · 核心（原生 ES5 风格，零依赖）
   - api(): fetch 封装，统一 {code,message,data} 信封
   - hash 路由：#/home #/assess #/quiz/{code} #/timeline #/todo #/mine ...
   - 401 跳登录；403 显示「仅学生本人可访问」
   - 提供转义、空态/错误态、骨架、Tab 高亮、返回等公共能力 */
(function () {
  'use strict';

  window.Views = window.Views || {};

  var ROOTS = { home: 1, assess: 1, timeline: 1, todo: 1, mine: 1 };
  var TAB_OF = {
    home: 'home', assess: 'assess', quiz: 'assess', profile: 'assess', batch: 'assess',
    timeline: 'timeline', todo: 'todo', plan: 'mine', share: 'mine', privacy: 'mine', mine: 'mine'
  };
  var TITLES = {
    home: ['成长门户', '京山中职 · 学生成长'],
    assess: ['测评中心', '八项诊断 · 先给自己看'],
    quiz: ['答题', '真实作答 · 没有对错'],
    profile: ['我的画像', '只和自己比 · 不排名'],
    batch: ['批次进度', '本学期施测安排'],
    timeline: ['成长时间轴', '德育 · 测评 · 考勤 · 作业 · 计划'],
    todo: ['我的待办', '老师催办与系统任务'],
    plan: ['计划与打卡', '目标 · 周计划 · 今日打卡'],
    share: ['分享成长', '授权后才可见 · 随时可撤销'],
    privacy: ['隐私与数据权利', '谁能看到什么，由我决定'],
    mine: ['我的', '身份 · 隐私 · 退出']
  };
  var ICONS = {
    home: '<path d="M4 11 12 4l8 7v9a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1z"/>',
    assess: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/>',
    timeline: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    todo: '<path d="m4 6 2 2 3-3M4 13l2 2 3-3M4 20l2 2 3-3"/><path d="M13 6h7M13 13h7M13 20h7"/>',
    mine: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c1.5-3.5 4-5 7-5s5.5 1.5 7 5"/>',
    share: '<circle cx="6" cy="12" r="2.5"/><circle cx="17" cy="6" r="2.5"/><circle cx="17" cy="18" r="2.5"/><path d="m8.3 10.8 6.4-3.6M8.3 13.2l6.4 3.6"/>',
    shield: '<path d="M12 3 5 6v5c0 4.5 3 7.5 7 9 4-1.5 7-4.5 7-9V6z"/><path d="m9 12 2 2 4-4"/>',
    target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5"/>',
    chart: '<path d="M4 20V4M4 20h16"/><path d="m7 15 4-5 3 3 5-7"/>',
    book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v18H6.5A2.5 2.5 0 0 0 4 23z"/><path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H20"/>',
    check: '<path d="m5 12 5 5L20 6"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.6 1.6"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.6-1.6"/>',
    lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    bell: '<path d="M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6"/><path d="M10 19a2 2 0 0 0 4 0"/>',
    logout: '<path d="M14 5H6v14h8"/><path d="M17 8l4 4-4 4M21 12H10"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    user: '<circle cx="12" cy="8" r="3.5"/><path d="M5 20c1.5-3.5 4-5 7-5s5.5 1.5 7 5"/>'
  };

  function $(sel, host) { return (host || document).querySelector(sel); }
  function $all(sel, host) {
    return Array.prototype.slice.call((host || document).querySelectorAll(sel));
  }

  function esc(text) {
    return String(text == null ? '' : text).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function icon(name, extra) {
    var body = ICONS[name] || ICONS.book;
    return '<svg class="ic' + (extra ? ' ' + extra : '') + '" viewBox="0 0 24 24" fill="none" ' +
      'stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" ' +
      'aria-hidden="true">' + body + '</svg>';
  }

  function na(v, unit) {
    if (v === null || v === undefined || v === '') { return '暂不可用'; }
    return String(v) + (unit || '');
  }

  function api(path, opts) {
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
      if (res.status === 401) {
        location.href = '/api/v1/login';
        return Promise.reject({ code: 401, message: '登录已过期，请重新登录' });
      }
      if (res.status === 403) {
        return Promise.reject({ code: 403, message: '仅学生本人可访问' });
      }
      return res.text().then(function (raw) {
        var body = null;
        if (raw) {
          try { body = JSON.parse(raw); } catch (e) { body = null; }
        }
        if (body && typeof body.code === 'number') {
          if (body.code !== 0) {
            return Promise.reject({
              code: body.code,
              message: body.message || body.error || '请求失败'
            });
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

  function skeleton(n) {
    var lines = '';
    for (var i = 0; i < (n || 3); i++) {
      lines += '<div class="sk-line ' + (i === 0 ? 'w40' : (i === 1 ? 'w80' : 'w60')) + '"></div>';
    }
    return '<div class="sk-card">' + lines + '</div>' +
      '<div class="sk-grid"><div class="sk-cell"></div><div class="sk-cell"></div></div>' +
      '<div class="sk-card"><div class="sk-line w60"></div><div class="sk-line w80"></div></div>';
  }

  function emptyHTML(text, extraHTML) {
    return '<div class="empty"><p>' + esc(text || '暂无内容') + '</p>' +
      (extraHTML || '') + '</div>';
  }

  function errorHTML(err) {
    var code = err && err.code;
    var title = code === 403 ? '仅学生本人可访问' : '加载失败';
    var msg = (err && err.message) || '请稍后重试';
    return '<div class="card"><div class="error"><div class="etitle">' + esc(title) + '</div>' +
      '<p>' + esc(msg) + '</p><button type="button" class="btn ghost" data-retry>重试</button></div></div>';
  }

  function renderError(el, err, retry) {
    el.innerHTML = errorHTML(err);
    var btn = $('[data-retry]', el);
    if (btn && retry) {
      btn.addEventListener('click', function () {
        el.innerHTML = skeleton(3);
        retry();
      });
    }
  }

  function bindRetry(el, retry) {
    var btn = $('[data-retry]', el);
    if (btn && retry) {
      btn.addEventListener('click', function () {
        el.innerHTML = skeleton(3);
        retry();
      });
    }
  }

  function toast(msg) {
    var t = document.getElementById('toast');
    if (!t) {
      t = document.createElement('div');
      t.id = 'toast';
      t.className = 'toast';
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toast._tm);
    toast._tm = setTimeout(function () { t.classList.remove('show'); }, 2600);
  }

  function fmtDate(v) {
    if (!v) { return '—'; }
    return String(v).slice(0, 10);
  }
  function fmtDT(v) {
    if (!v) { return '—'; }
    return String(v).replace('T', ' ').slice(0, 16);
  }
  function todayISO() {
    var d = new Date();
    var m = d.getMonth() + 1;
    var day = d.getDate();
    return d.getFullYear() + '-' + (m < 10 ? '0' : '') + m + '-' + (day < 10 ? '0' : '') + day;
  }
  function greeting() {
    var h = new Date().getHours();
    if (h < 6) { return '夜深了'; }
    if (h < 11) { return '早上好'; }
    if (h < 14) { return '中午好'; }
    if (h < 18) { return '下午好'; }
    return '晚上好';
  }

  function go(hash) {
    if (!hash) { return; }
    if (location.hash === hash) { render(); return; }
    location.hash = hash;
  }
  function back() {
    if (window.history.length > 2) {
      window.history.back();
    } else {
      go('#/home');
    }
  }

  function setTab(tab) {
    $all('.tabbar button').forEach(function (b) {
      var on = b.getAttribute('data-tab') === tab;
      b.classList.toggle('on', on);
      b.setAttribute('aria-current', on ? 'page' : 'false');
    });
  }

  function setHeader(name) {
    var pair = TITLES[name] || TITLES.home;
    var t = document.getElementById('app-title');
    var s = document.getElementById('app-sub');
    if (t) { t.textContent = pair[0]; }
    if (s) { s.textContent = pair[1]; }
    var backBtn = document.getElementById('btn-back');
    if (backBtn) { backBtn.hidden = !!ROOTS[name]; }
    document.title = pair[0] + ' · 京山市中等职业技术学校';
  }

  function parseRoute() {
    var raw = String(location.hash || '').replace(/^#\/?/, '');
    var q = raw.split('?');
    var parts = q[0].split('/');
    var list = [];
    for (var i = 0; i < parts.length; i++) {
      if (parts[i]) { list.push(decodeURIComponent(parts[i])); }
    }
    var params = {};
    var query = q[1] || '';
    query.split('&').forEach(function (kv) {
      if (!kv) { return; }
      var p = kv.split('=');
      params[decodeURIComponent(p[0])] = decodeURIComponent(p[1] || '');
    });
    if (list[1]) { params.code = list[1]; }
    return { name: list[0] || 'home', params: params };
  }

  var meCache = null;
  function loadMe(force) {
    if (meCache && !force) { return Promise.resolve(meCache); }
    return api('/api/v1/student/me').then(function (d) { meCache = d; return d; });
  }

  function render() {
    var route = parseRoute();
    var view = window.Views[route.name] || window.Views.home;
    if (!view) {
      document.getElementById('view').innerHTML = errorHTML({ message: '页面不存在' });
      return;
    }
    setHeader(route.name);
    setTab(TAB_OF[route.name] || 'home');
    window.scrollTo(0, 0);
    var host = document.getElementById('view');
    host.innerHTML = '';
    try {
      view.render(host, route.params || {});
    } catch (e) {
      host.innerHTML = errorHTML({ message: e && e.message ? e.message : '页面渲染失败' });
    }
  }

  function mountTabbar() {
    var bar = document.getElementById('tabbar');
    if (!bar) { return; }
    $all('button', bar).forEach(function (btn) {
      btn.addEventListener('click', function () {
        var tab = btn.getAttribute('data-tab');
        go('#/' + tab);
      });
    });
    var backBtn = document.getElementById('btn-back');
    if (backBtn) { backBtn.addEventListener('click', back); }
  }

  function boot() {
    if (!document.getElementById('view')) { return; }
    mountTabbar();
    window.addEventListener('hashchange', render);
    if (!location.hash) {
      try { history.replaceState(null, '', '#/home'); } catch (e) { location.hash = '#/home'; }
    }
    render();
  }

  window.App = {
    api: api,
    get: function (p) { return api(p); },
    post: function (p, b) { return api(p, { method: 'POST', body: b === undefined ? {} : b }); },
    put: function (p, b) { return api(p, { method: 'PUT', body: b }); },
    del: function (p) { return api(p, { method: 'DELETE' }); },
    esc: esc,
    na: na,
    icon: icon,
    toast: toast,
    go: go,
    back: back,
    render: render,
    boot: boot,
    skeleton: skeleton,
    emptyHTML: emptyHTML,
    errorHTML: errorHTML,
    renderError: renderError,
    bindRetry: bindRetry,
    fmtDate: fmtDate,
    fmtDT: fmtDT,
    todayISO: todayISO,
    greeting: greeting,
    loadMe: loadMe,
    setHeader: setHeader,
    setTab: setTab
  };
})();
