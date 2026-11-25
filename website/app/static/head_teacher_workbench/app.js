/* 班主任德育工作台 · 交互（八模块） */
(function () {
  'use strict';
  var S = { sid: '', cid: '', name: '', view: 'home', weekly: null, kind: '', watching: null,
            canViewStudents: false, canViewData: true,
            focusItems: null, students: null, feedbackItems: null, feedbackSummary: null,
            pendingCount: null, todayAbsent: null,
            growthSid: '', growthData: null, growthFilter: 'all', growthDim: '', growthTerm: '',
            reportData: null, ga: null, gaView: [],
            spaceKind: 'seat', spaceData: null, spacePick: '',
            moralData: null, moralView: 'class', moralSort: 'id', moralPeriod: 'month',
            moralMonth: '', moralTerm: '', moralTerms: null };
  var TITLES = {
    home: ['小秘书', '今日待办 · 班级态势 · 重点学生 · 科任反馈'],
    students: ['成长档案', '五维记录、成长时间轴与学期档案'],
    space: ['班级空间', '座位表与寝室表，拖拽卡片即可排位'],
    attendance: ['出勤统计', '本周出勤趋势、今日未到与请假'],
    learning: ['学情预警', '需关注学生、作业提交与考试成绩'],
    moral: ['德育量化', '行为事件确认与德育积分台账'],
    affairs: ['班务减负', '本周班务事项与转介回执'],
    family: ['家校协同', '沟通留痕登记与记录查询'],
    data: ['数据备份', '学生、教师、成绩的 Excel 维护入口']
  };
  var CATS = ['归寝异常', '缺勤关注', '学业联系', '行为观察', '家长告知', '其他'];
  var WEEK = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
  var loaded = {};

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function stuNo(x) { return (x && (x.student_no || x.student_id)) || ''; }
  var tm = null;
  function toast(msg) {
    var t = $('toast'); t.textContent = msg; t.style.display = 'block';
    clearTimeout(tm); tm = setTimeout(function () { t.style.display = 'none'; }, 3000);
  }
  async function api(path, body, method) {
    var opt = { method: method || (body ? 'POST' : 'GET'), credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' } };
    if (body) { opt.body = JSON.stringify(body); }
    try {
      var r = await fetch(path, opt);
      if (r.status === 401) { location.href = '/api/v1/login?next=' + encodeURIComponent(location.pathname); return null; }
      var j = await r.json();
      if (!r.ok || j.code !== 0) { toast(j.error || '请求失败，请稍后再试'); return null; }
      return j.data;
    } catch (e) { toast('网络异常，请检查连接'); return null; }
  }
  function na(v, unit) {
    if (v === null || v === undefined || v === '') { return { t: '暂不可用', cls: ' na' }; }
    return { t: v + (unit || ''), cls: '' };
  }
  function empty(text) { return '<div class="empty">' + esc(text) + '</div>'; }
  function badge(id, text, cls) { var el = $(id); if (el) { el.textContent = text; el.className = 'badge ' + (cls || ''); } }
  function kpi(label, value, note) {
    return '<div class="kpi"><div class="k">' + esc(label) + '</div><div class="v' + value.cls + '">' +
      esc(value.t) + '</div><div class="s">' + esc(note) + '</div></div>';
  }

  /* ---------------- 班主任小秘书 ---------------- */
  async function loadHome() {
    if (!S.canViewStudents) {
      var msg = '仅本班班主任可查看本班学生信息';
      $('kpis').innerHTML = empty(msg);
      $('weeklyBody').innerHTML = empty(msg);
      $('watchBody').innerHTML = empty('');
      $('todoBody').innerHTML = empty('');
      $('focusBody').innerHTML = empty('');
      $('fbBody').innerHTML = empty('');
      $('homeAlerts').innerHTML = '';
      badge('weeklyBadge', '—', ''); badge('watchBadge', '—', ''); badge('todoBadge', '—', '');
      badge('focusBadge', '—', ''); badge('fbBadge', '—', '');
      $('btnArchive').disabled = true;
      return;
    }
    loadWeekly(); loadWatch(); loadTodo();
    loadFocus(); loadFeedback(); loadAlerts();
    var d = await api('/api/v1/growth/numbers?session_id=' + encodeURIComponent(S.sid));
    var n = d && d.data ? d.data : null;
    $('kpis').innerHTML = [
      kpi('出勤率', na(n && n.attendance_rate, '%'), '本周考勤'),
      kpi('需关注', na(n && n.attention_count, ' 人'), '命中关注规则'),
      kpi('德育积分', n && n.moral_delta != null ? { t: (n.moral_delta >= 0 ? '+' : '') + n.moral_delta + ' 分', cls: '' } : { t: '暂不可用', cls: ' na' }, '本周已确认'),
      kpi('归寝异常', na(n && n.dorm_anomaly, ' 人次'), '晚寝异常'),
      kpi('本周请假', na(n && n.leave_count, ' 人次'), '已审批请假')
    ].join('');
  }

  async function loadWeekly() {
    var d = await api('/api/v1/report/weekly?session_id=' + encodeURIComponent(S.sid));
    S.weekly = d && d.card ? d.card : null;
    var c = S.weekly, body = $('weeklyBody');
    if (!c) { body.innerHTML = empty('周报暂时无法生成'); badge('weeklyBadge', '不可用', 'danger'); return; }
    var main = [], notes = [];
    (c.lines || []).forEach(function (t, i) {
      var text = String(t);
      if (i > 0 && (/^(·|数据源|未经确认|说明)/.test(text) || /双轨纪律|未就绪|口径/.test(text))) {
        notes.push(text); return;
      }
      main.push(text);
    });
    body.innerHTML = '<div class="weekly">' + main.map(function (t) {
      return '<p>' + esc(t) + '</p>';
    }).join('') + (notes.length ? '<details><summary>数据口径</summary>' +
      notes.map(function (t) { return '<p>' + esc(t) + '</p>'; }).join('') + '</details>' : '') + '</div>';
    var archived = c.status === 'archived';
    var unavailable = c.status === 'unavailable';
    badge('weeklyBadge', archived ? '已归档' : (unavailable ? '不可用' : '待确认'),
      archived ? 'ok' : (unavailable ? 'danger' : 'warn'));
    var b = $('btnArchive'); b.disabled = archived || unavailable; b.dataset.rid = c.report_id || '';
  }
  async function archive() {
    var rid = $('btnArchive').dataset.rid;
    if (!rid) { return; }
    if (!confirm('确认归档本周周报？归档后不再修改。')) { return; }
    var d = await api('/api/v1/report/archive', { session_id: S.sid, report_id: rid });
    if (d) { toast('已归档'); loadWeekly(); }
  }

  async function loadWatch() {
    var d = await api('/api/v1/report/watchlist?session_id=' + encodeURIComponent(S.sid));
    S.watching = d && d.card ? (d.card.items || []) : null;
    renderWatch($('watchBody'), $('watchBadge'), 8);
  }
  function renderWatch(body, badgeEl, limit) {
    var list = S.watching;
    if (!list) { body.innerHTML = empty('需关注清单暂时不可用'); if (badgeEl) { badgeEl.textContent = '不可用'; badgeEl.className = 'badge danger'; } return; }
    if (badgeEl) { badgeEl.textContent = list.length ? list.length + ' 人' : '暂无'; badgeEl.className = 'badge ' + (list.length ? 'warn' : 'ok'); }
    if (!list.length) { body.innerHTML = empty('本班暂无需要关注的学生'); return; }
    var rows = limit ? list.slice(0, limit) : list;
    body.innerHTML = '<table><thead><tr><th>学生</th><th>关注点</th><th>状态</th><th>处理</th></tr></thead><tbody>' +
      rows.map(function (x) {
        return '<tr><td>' + esc(x.name_masked || x.student_id) + '</td><td>' + esc(x.mark) +
          '<div class="row-hint">' + esc(x.action) + '</div></td><td>' + esc(x.status) + '</td>' +
          '<td><div class="tools"><select data-sel="' + esc(x.student_id) + '">' +
          CATS.map(function (c) { return '<option>' + esc(c) + '</option>'; }).join('') +
          '</select><button type="button" class="btn sm" data-refer="' + esc(x.student_id) + '">转介</button></div></td></tr>';
      }).join('') + '</tbody></table>';
  }

  async function loadTodo() {
    var d = await api('/api/v1/todo/list?session_id=' + encodeURIComponent(S.sid));
    var body = $('todoBody');
    if (!d) { body.innerHTML = empty('待办暂时不可用'); badge('todoBadge', '不可用', 'danger'); return; }
    var items = d.items || [];
    badge('todoBadge', items.length ? items.length + ' 项' : '暂无', items.length ? 'warn' : 'ok');
    if (!items.length) { body.innerHTML = empty('本周暂无待办'); return; }
    body.innerHTML = '<table><thead><tr><th>时间</th><th>类型</th><th>事由</th><th>说明</th><th>操作</th></tr></thead><tbody>' +
      items.slice(0, 6).map(function (x) {
        return '<tr><td>' + esc((x.ts || '').replace('T', ' ').slice(5, 16)) + '</td><td>' +
          esc((d.kinds && d.kinds[x.kind]) || x.kind) + '</td><td>' + esc(x.category) + '</td><td>' +
          esc(x.fact) + '</td><td><button type="button" class="btn sm" data-close="' + esc(x.id) + '">完成</button></td></tr>';
      }).join('') + '</tbody></table>';
  }

  /* ---------------- 小秘书 · 提醒条 ---------------- */
  function alertChip(jump, num, label, cls) {
    var v = (num === null || num === undefined) ? '—' : num;
    return '<button type="button" class="alert-chip ' + (cls || '') + '" data-jump="' + esc(jump) + '">' +
      '<b>' + esc(v) + '</b><span>' + esc(label) + '</span></button>';
  }
  function renderAlerts() {
    var focusN = S.focusItems ? S.focusItems.length : null;
    var unread = S.feedbackSummary ? S.feedbackSummary.unread : null;
    $('homeAlerts').innerHTML = [
      alertChip('students', S.pendingCount, '待确认记录', S.pendingCount ? 'warn' : ''),
      alertChip('home-focus', focusN, '重点学生', focusN ? 'focus' : ''),
      alertChip('home-feedback', unread, '科任反馈未读', unread ? 'focus' : ''),
      alertChip('attendance', S.todayAbsent, '今日缺勤', S.todayAbsent ? 'danger' : '')
    ].join('');
  }
  async function loadAlerts() {
    var ov = await api('/api/v1/growth360/class/overview?class_id=' + encodeURIComponent(S.cid));
    S.pendingCount = ov && ov.stats ? ov.stats.pending : null;
    var at = await api('/api/v1/attendance/week?class_id=' + encodeURIComponent(S.cid));
    S.todayAbsent = at && at.today && at.today.absent ? at.today.absent.length : null;
    renderAlerts();
  }

  /* ---------------- 小秘书 · 重点学生标记 ---------------- */
  async function loadFocus() {
    var d = await api('/api/v1/assistant/focus?class_id=' + encodeURIComponent(S.cid));
    if (!d) { $('focusBody').innerHTML = empty('重点学生标记暂时不可用'); badge('focusBadge', '不可用', 'danger'); return; }
    S.focusItems = d.items || [];
    fillTagOptions(d.tags || []);
    renderFocus();
    fillFocusStudents();
    renderAlerts();
  }
  function fillTagOptions(tags) {
    var sel = $('focusTag');
    if (!sel || sel.dataset.filled === '1' || !tags.length) { return; }
    sel.innerHTML = tags.map(function (t) { return '<option>' + esc(t) + '</option>'; }).join('');
    sel.dataset.filled = '1';
  }
  async function fillFocusStudents() {
    if (!S.students) {
      var d = await api('/api/v1/students?class_id=' + encodeURIComponent(S.cid));
      S.students = d && d.items ? d.items : [];
    }
    var sel = $('focusStudent');
    if (!sel || sel.dataset.filled === '1') { return; }
    sel.innerHTML = '<option value="">选择学生</option>' + S.students.map(function (x) {
      return '<option value="' + esc(x.student_id) + '">' +
        esc((x.name || '') + ' ' + stuNo(x)) + '</option>';
    }).join('');
    sel.dataset.filled = '1';
  }
  function renderFocus() {
    var list = S.focusItems || [];
    badge('focusBadge', list.length ? list.length + ' 项' : '暂无', list.length ? 'warn' : 'ok');
    if (!list.length) {
      $('focusBody').innerHTML = empty('暂无重点标记；选择学生与标签后点「标记」');
      return;
    }
    $('focusBody').innerHTML = '<table><thead><tr><th>学生</th><th>标签</th><th>说明</th><th>操作</th></tr></thead><tbody>' +
      list.map(function (x) {
        return '<tr><td>' + esc(x.student_name || stuNo(x)) +
          '<div class="row-hint">' + esc(stuNo(x)) + '</div></td>' +
          '<td><span class="tag-pill">' + esc(x.tag) + '</span></td>' +
          '<td>' + esc(x.note || '—') + '</td>' +
          '<td><button type="button" class="btn sm ghost" data-focus-del="' + esc(x.id) + '">移除</button></td></tr>';
      }).join('') + '</tbody></table>';
  }
  async function addFocus() {
    var sid = $('focusStudent').value;
    var tag = $('focusTag').value;
    if (!sid) { toast('请先选择学生'); return; }
    if (!tag) { toast('请选择标签'); return; }
    var note = prompt('补充说明（可选）', '');
    if (note === null) { return; }
    var d = await api('/api/v1/assistant/focus',
      { class_id: S.cid, student_id: sid, tag: tag, note: note });
    if (d) {
      S.focusItems = d.items || [];
      renderFocus(); renderAlerts();
      toast(d.created === false ? '已更新该标签备注' : '已标记，科任教师可见');
    }
  }
  async function removeFocus(id) {
    if (!confirm('移除该重点标记？')) { return; }
    var d = await api('/api/v1/assistant/focus/remove', { class_id: S.cid, mark_id: id });
    if (d) { S.focusItems = d.items || []; renderFocus(); renderAlerts(); toast('已移除'); }
  }

  /* ---------------- 小秘书 · 科任反馈 ---------------- */
  async function loadFeedback() {
    var d = await api('/api/v1/assistant/feedback?class_id=' + encodeURIComponent(S.cid));
    if (!d) { $('fbBody').innerHTML = empty('科任反馈暂时不可用'); badge('fbBadge', '不可用', 'danger'); return; }
    S.feedbackItems = d.items || [];
    S.feedbackSummary = d.summary || { total: 0, unread: 0 };
    renderFeedback();
    renderAlerts();
  }
  function renderFeedback() {
    var list = S.feedbackItems || [];
    var sum = S.feedbackSummary || {};
    var unread = sum.unread || 0;
    badge('fbBadge', list.length ? (unread ? unread + ' 条未读' : list.length + ' 条') : '暂无',
      unread ? 'warn' : (list.length ? 'ok' : ''));
    if (!list.length) {
      $('fbBody').innerHTML = empty('暂无科任反馈；教师提交课堂或作业点评后在此汇总');
      return;
    }
    $('fbBody').innerHTML = '<ul class="fb-list">' + list.slice(0, 8).map(function (x) {
      var who = x.student_name || x.student_id || '全班';
      return '<li class="fb-item' + (x.status === 'new' ? ' new' : '') + '">' +
        '<div class="fb-top"><b>' + esc(who) + '</b>' +
        '<span class="fb-kind">' + esc(x.kind) + '</span>' +
        '<em>' + esc((x.ts || '').replace('T', ' ').slice(5, 16)) + '</em></div>' +
        '<p>' + esc(x.content) + '</p>' +
        '<div class="fb-foot"><span>' + esc(x.teacher_name || x.teacher_userid || '科任教师') + '</span>' +
        (x.status === 'new'
          ? '<button type="button" class="btn sm" data-fb-read="' + esc(x.id) + '">知晓</button>'
          : '<span class="fb-read">已读</span>') +
        '</div></li>';
    }).join('') + '</ul>';
  }
  async function readFeedback(id) {
    var d = await api('/api/v1/assistant/feedback/read', { class_id: S.cid, comment_id: id });
    if (d) { S.feedbackSummary = d.summary || S.feedbackSummary; loadFeedback(); }
  }

  /* ---------------- 成长档案 ---------------- */
  var DIMS = [];

  function lvCls(lv) { return lv ? 'lv-' + lv : 'lv-none'; }
  function lvTxt(lv) { return lv || '—'; }
  function cnDate(s) {
    var m = String(s || '').slice(0, 10).match(/^(\d{4})-(\d{2})-(\d{2})$/);
    return m ? m[1] + '年' + m[2] + '月' + m[3] + '日' : String(s || '');
  }
  function dimDots(levels) {
    return DIMS.map(function (d) {
      var lv = levels[d.id];
      return '<i class="gdot ' + lvCls(lv) + '" title="' + esc(d.name + '：' + (lv || '证据不足')) + '">' +
        esc(lv || '·') + '</i>';
    }).join('');
  }

  async function loadDims() {
    if (DIMS.length) { return DIMS; }
    var d = await api('/api/v1/growth360/dimensions');
    DIMS = (d && d.dimensions) || [];
    return DIMS;
  }

  async function loadStudents() {
    await loadDims();
    var q = $('stuSearch').value.trim().toLowerCase();
    var d = await api('/api/v1/growth360/class/overview?class_id=' + encodeURIComponent(S.cid));
    if (!d) { $('studentsBody').innerHTML = empty('成长档案加载失败'); return; }
    S.ga = d;
    $('gaKpis').innerHTML = [
      '<div class="kpi"><div class="k">班级学生</div><div class="v">' + d.total + '</div><div class="s">' + esc(d.term) + '</div></div>',
      '<div class="kpi"><div class="k">需关注</div><div class="v">' + d.stats.attention + '</div><div class="s">待确认或证据缺口</div></div>',
      '<div class="kpi"><div class="k">待确认</div><div class="v">' + d.stats.pending + '</div><div class="s">任课 / 企业提交</div></div>',
      '<div class="kpi"><div class="k">无记录</div><div class="v">' + d.stats.empty + '</div><div class="s">可先记一条</div></div>'
    ].join('');
    $('gaFilters').innerHTML = [
      ['all', '全部', d.total], ['attention', '需关注', d.stats.attention],
      ['pending', '待确认', d.stats.pending], ['empty', '无记录', d.stats.empty]
    ].map(function (x) {
      return '<button type="button" class="ga-filter' + (S.growthFilter === x[0] ? ' on' : '') +
        '" data-gf="' + x[0] + '">' + x[1] + ' <b>' + x[2] + '</b></button>';
    }).join('');
    S.gaView = (d.items || []).filter(function (x) {
      if (q && (x.name || '').toLowerCase().indexOf(q) < 0 &&
          stuNo(x).toLowerCase().indexOf(q) < 0) { return false; }
      if (S.growthFilter === 'attention') { return x.attention; }
      if (S.growthFilter === 'pending') { return x.pending > 0; }
      if (S.growthFilter === 'empty') { return x.count === 0; }
      return true;
    });
    renderRoster();
    if (!S.growthSid || !S.gaView.some(function (x) { return x.student_id === S.growthSid; })) {
      S.growthSid = S.gaView.length ? S.gaView[0].student_id : '';
      S.growthTerm = '';
    }
    if (S.growthSid) { loadGrowthStudent(S.growthSid, S.growthTerm); }
    else { $('gaDetail').innerHTML = empty('没有匹配的学生'); }
  }

  function renderRoster() {
    var arr = S.gaView || [];
    $('gaRosterBadge').textContent = arr.length + ' 人';
    if (!arr.length) { $('studentsBody').innerHTML = empty('没有匹配的学生'); return; }
    $('studentsBody').innerHTML = arr.map(function (x) {
      return '<div class="ga-stu' + (x.student_id === S.growthSid ? ' on' : '') + '" data-stu="' +
        esc(x.student_id) + '">' +
        '<span class="ga-ava">' + esc((x.name || '?').slice(0, 1)) + '</span>' +
        '<span class="ga-meta"><b>' + esc(x.name) + '<em>' + esc(stuNo(x)) + '</em></b>' +
        '<span class="ga-sub">' + x.count + ' 条记录' +
        (x.flag ? '<i class="ga-flag">' + esc(x.flag) + '</i>' : '') + '</span></span>' +
        '<span class="ga-dots">' + dimDots(x.levels) + '</span></div>';
    }).join('');
  }

  async function loadGrowthStudent(sid, term) {
    S.growthSid = sid;
    S.growthDim = '';
    S.growthTerm = term || '';
    $('gaDetail').innerHTML = '<div class="loading">加载中…</div>';
    var d = await api('/api/v1/growth360/' + encodeURIComponent(sid) +
      '?class_id=' + encodeURIComponent(S.cid) +
      (S.growthTerm ? '&term=' + encodeURIComponent(S.growthTerm) : ''));
    if (!d) { $('gaDetail').innerHTML = empty('档案加载失败'); return; }
    S.growthData = d;
    document.querySelectorAll('#studentsBody .ga-stu').forEach(function (el) {
      el.className = 'ga-stu' + (el.dataset.stu === sid ? ' on' : '');
    });
    renderGrowthDetail();
  }

  function renderGrowthDetail() {
    var d = S.growthData;
    if (!d) { return; }
    var s = d.student, c = d.counts, report = d.report;
    var covered = d.dims.filter(function (x) { return x.level; }).length;
    var dimsHtml = d.dims.map(function (x) {
      return '<button type="button" class="ga-dim' + (S.growthDim === x.id ? ' on' : '') +
        '" data-gdim="' + x.id + '">' +
        '<span class="ga-dim-top"><span>' + esc(x.short) + '</span><b class="' + lvCls(x.level) + '">' +
        lvTxt(x.level) + '</b></span>' +
        '<span class="bar"><i style="width:' + Math.max(4, x.coverage) + '%"></i></span>' +
        '<em class="ga-dim-meta">' + x.count + ' 条记录 · ' +
        (x.progress ? '较上学期 ' + x.progress : '暂无对比') + '</em></button>';
    }).join('');
    var list = (d.timeline || []).filter(function (x) { return !S.growthDim || x.dim === S.growthDim; });
    var tlHtml = list.length ? list.map(function (x) {
      var actions = x.status === 'pending' ?
        '<span class="ga-ti-act"><button type="button" class="btn sm" data-gconfirm="' + esc(x.id) +
        '">确认</button><button type="button" class="btn sm ghost" data-greturn="' + esc(x.id) +
        '">退回</button></span>' : '';
      var tag = x.status === 'confirmed' ? 'pos' : x.status === 'pending' ? 'pending' : 'neg';
      return '<div class="ga-ti"><span class="ga-ti-date">' + esc(cnDate(x.date)) + '</span>' +
        '<div class="ga-ti-main"><div class="ga-ti-title"><b>' + esc(x.title) + '</b>' +
        '<span class="tag ' + tag + '">' + esc(x.status_text) + '</span></div>' +
        '<p>' + esc(x.dim_name) + ' · ' + esc(x.sub_item) + '</p>' +
        '<em>佐证：' + esc(x.evidence || '待补充') + ' · 来源：' + esc(x.source) + '</em>' +
        actions + '</div></div>';
    }).join('') : empty(S.growthDim ? '该维度本学期暂无记录' : '本学期暂无记录，可从一次班会或一次实训开始');
    var att = d.attendance || {};
    var termOptions = (d.terms || [d.term]).map(function (t) {
      return '<option value="' + esc(t) + '"' + (t === d.term ? ' selected' : '') + '>' + esc(t) + '</option>';
    }).join('');
    var certs = d.certificates || [];
    var certHtml = certs.length ? '<div class="ga-cert-list">' + certs.slice(0, 4).map(function (x) {
      var statusText = { confirmed: '已确认', pending: '待确认', returned: '退回补证' }[x.status] || x.status;
      return '<div class="ga-cert-item"><b>' + esc(x.name) + (x.level ? ' · ' + esc(x.level) : '') + '</b>' +
        '<span>' + esc(x.issued_on) + ' · ' + esc(x.issuer || '发证机构未填写') + ' · ' + esc(statusText) + '</span>' +
        '<span>佐证：' + esc(x.evidence || '待补充') + '</span></div>';
    }).join('') + (certs.length > 4 ? '<p class="ga-note">另有 ' + (certs.length - 4) + ' 条已登记证书</p>' : '') +
      '</div>' : '<p class="ga-note">本学期暂无证书记录，可按证书正文登记。</p>';
    $('gaDetail').innerHTML =
      '<div class="ga-hero">' +
      '<span class="ga-bigava">' + esc((s.name || '?').slice(0, 1)) + '</span>' +
      '<div class="ga-hero-main"><h3>' + esc(s.name) + ' <em>' + esc(stuNo(s)) + '</em></h3>' +
      '<div class="ga-chips">' +
      (s.gender ? '<span class="ga-chip">' + esc(s.gender) + '</span>' : '') +
      '<span class="ga-chip">' + esc(S.cid) + ' 班</span>' +
      '<span class="ga-chip">' + esc(d.term) + '</span>' +
      '<span class="ga-chip ok">已确认 ' + c.confirmed + ' 条</span>' +
      (c.pending ? '<span class="ga-chip warn">待确认 ' + c.pending + ' 条</span>' : '') +
      '</div></div>' +
      '<div class="tools"><select class="ga-term" data-gterm aria-label="选择学期">' + termOptions + '</select>' +
      '<button type="button" class="btn sm" data-cert-add>+ 证书</button>' +
      '<button type="button" class="btn sm primary" data-growth-add>+ 随手记</button></div></div>' +
      '<div class="ga-dims">' + dimsHtml + '</div>' +
      '<div class="ga-cols"><div class="ga-panel">' +
      '<div class="ga-panel-head"><b>成长时间轴</b><span>' + list.length +
      ' 条' + (S.growthDim ? ' · 已筛选' : '') + '</span></div>' +
      '<div class="ga-tl">' + tlHtml + '</div></div>' +
      '<div class="ga-side"><div class="ga-panel">' +
      '<div class="ga-panel-head"><b>本学期概览</b><span>' + esc(d.term) + '</span></div>' +
      '<div class="ga-sum"><div><b>' + c.confirmed + '</b><span>已确认</span></div>' +
      '<div><b>' + c.pending + '</b><span>待确认</span></div>' +
      '<div><b>' + covered + '/5</b><span>维度覆盖</span></div></div>' +
      '<p class="ga-note">近 7 日出勤：实到 ' + (att.present || 0) + ' 天 · 请假 ' +
      (att.leave || 0) + ' 天 · 未到 ' + (att.absent || 0) + ' 天。</p></div>' +
      '<div class="ga-panel"><div class="ga-panel-head"><b>学期成长报告</b>' +
      '<span class="tag ' + (report ? (report.status === 'published' ? 'pos' : 'pending') : '') + '">' +
      esc(report ? report.status_text : '未生成') + '</span></div>' +
      '<p class="ga-note">' + (report ? 'v' + report.version + ' · ' +
        (report.status === 'published' ? '已发布并冻结，历史版本已保留' : '草稿可编辑，发布后冻结') :
        '按本学期已确认记录汇总五维、代表性事件与证书。') + '</p>' +
      '<div class="ga-actions"><button type="button" class="btn sm" data-report-open>' +
      (report ? '查看 / 编辑报告' : '生成学期报告') + '</button></div></div>' +
      '<div class="ga-panel"><div class="ga-panel-head"><b>1+X / 职业资格证书</b><span>' + certs.length + ' 条</span></div>' +
      certHtml + '<div class="ga-actions"><button type="button" class="btn sm" data-cert-add>登记证书</button></div></div>' +
      '</div></div>';
  }

  function growthFillSubs() {
    var dim = DIMS.find(function (x) { return x.id === $('gmDim').value; });
    $('gmSub').innerHTML = (dim ? dim.items : []).map(function (x) {
      return '<option value="' + esc(x.name) + '">' + esc(x.name) + '</option>';
    }).join('');
  }

  async function growthOpen() {
    await loadDims();
    if (!DIMS.length) { toast('成长维度加载失败'); return; }
    if (!S.growthSid) { toast('请先在左侧选择学生'); return; }
    var s = S.growthData && S.growthData.student;
    $('gmStudent').textContent = s ? (s.name + ' · ' + stuNo(s)) : S.growthSid;
    $('gmDim').innerHTML = DIMS.map(function (x) {
      return '<option value="' + x.id + '">' + esc(x.name) + '</option>';
    }).join('');
    growthFillSubs();
    $('gmTitle').value = '';
    $('gmFact').value = '';
    $('gmEvidence').value = '';
    $('gmDate').value = new Date().toISOString().slice(0, 10);
    $('growthModal').hidden = false;
    $('gmTitle').focus();
  }

  function growthClose() { $('growthModal').hidden = true; }

  async function growthSubmit() {
    var title = $('gmTitle').value.trim();
    if (!title) { toast('请填写记录标题'); return; }
    var r = await api('/api/v1/growth360/' + encodeURIComponent(S.growthSid) + '/items?class_id=' +
      encodeURIComponent(S.cid), {
        dim: $('gmDim').value, sub_item: $('gmSub').value, title: title,
        occurred_on: $('gmDate').value, fact: $('gmFact').value.trim(),
        evidence: $('gmEvidence').value.trim()
      });
    if (!r) { return; }
    toast('已记入成长档案');
    growthClose();
    await loadStudents();
  }

  async function growthConfirm(id, action) {
    if (!confirm(action === 'confirm' ? '确认该记录进入成长档案？' : '退回该记录补充佐证？')) { return; }
    var r = await api('/api/v1/growth360/items/' + encodeURIComponent(id) + '/confirm',
      { action: action });
    if (!r) { return; }
    toast(action === 'confirm' ? '已确认' : '已退回');
    await loadStudents();
  }

  function reportClose() { $('reportModal').hidden = true; }

  function reportOpen() {
    if (!S.growthData) { toast('请先选择学生'); return; }
    S.reportData = S.growthData.report || null;
    $('grTitle').textContent = S.growthData.student.name + ' · ' + S.growthData.term + ' 成长报告';
    $('reportModal').hidden = false;
    reportRender();
  }

  function applyReport(report) {
    S.reportData = report;
    if (S.growthData) { S.growthData.report = report; }
    renderGrowthDetail();
    if (!$('reportModal').hidden) { reportRender(); }
  }

  function reportRender() {
    var r = S.reportData, body = $('grBody');
    if (!r) {
      body.innerHTML = empty('尚未生成本学期报告。系统将只汇总已确认记录，证据不足的维度会如实标注。') +
        '<div class="gr-actions"><button type="button" class="btn primary" data-report-generate>生成报告草稿</button></div>';
      return;
    }
    var c = r.content || {}, dims = c.dims || [], highlights = c.highlights || [];
    var published = r.status === 'published';
    var dimsHtml = dims.map(function (x) {
      return '<div class="gr-dim-row"><span>' + esc(x.name) + '</span><b class="' + lvCls(x.level) + '">' +
        esc(x.level || '未评') + '</b><span>' + x.count + ' 条 · 佐证 ' + x.evidence + ' 条</span></div>';
    }).join('');
    var highlightsHtml = highlights.length ? '<ol class="gr-highlights">' + highlights.map(function (x) {
      return '<li><b>' + esc(x.title) + '</b><span>' + esc(x.date) + ' · ' + esc(x.dim_name) +
        ' · 佐证：' + esc(x.evidence || '待补充') + '</span></li>';
    }).join('') + '</ol>' : empty('本学期暂无已确认的代表性事件');
    var notes = (c.evidence_notes || []).join('；');
    var versions = (r.versions || []).map(function (x) {
      return 'v' + x.version + ' ' + esc(x.status === 'published' ? '已发布' : x.status) +
        (x.published_at ? '（' + esc(x.published_at.slice(0, 10)) + '）' : '');
    }).join(' · ');
    body.innerHTML =
      '<div class="gr-meta"><b>' + esc((c.student && c.student.name) || S.growthData.student.name) +
      ' · ' + esc(r.term) + '</b><span>v' + r.version + ' · ' + esc(r.status_text) +
      (r.generated_at ? ' · 生成于 ' + esc(r.generated_at.replace('T', ' ').slice(0, 16)) : '') + '</span></div>' +
      '<div class="gr-section"><h4>五维摘要</h4>' + dimsHtml + '</div>' +
      '<div class="gr-section"><h4>代表性成长事件</h4>' + highlightsHtml + '</div>' +
      '<div class="gr-section"><h4>证据提示</h4><p class="ga-note">' + esc(notes || '无') + '</p></div>' +
      '<div class="gr-section"><h4>班主任评语</h4><textarea id="grComment" class="gr-comment"' +
      (published ? ' readonly' : '') + ' maxlength="2000" placeholder="只写事实与下学期建议，不作定性标签">' +
      esc(c.teacher_comment || '') + '</textarea></div>' +
      (versions ? '<div class="gr-history">已发布历史版本：' + versions + '</div>' : '') +
      '<div class="gr-actions">' +
      '<button type="button" class="btn ghost" data-report-generate>' +
      (published ? '生成新版本' : '重新汇总记录') + '</button>' +
      (!published ? '<button type="button" class="btn" data-report-save>保存评语</button>' +
        '<button type="button" class="btn primary" data-report-publish>审核并发布</button>' : '') +
      '</div>';
  }

  async function reportGenerate() {
    var old = S.reportData;
    if (old && old.status === 'published' &&
        !confirm('将保留当前已发布版本，并基于最新记录生成新草稿。继续？')) { return; }
    var term = S.growthData && S.growthData.term;
    if (!term) { return; }
    var r = await api('/api/v1/growth360/' + encodeURIComponent(S.growthSid) +
      '/report/generate?class_id=' + encodeURIComponent(S.cid), { term: term });
    if (!r) { return; }
    applyReport(r);
    toast(old && old.status === 'published' ? '已生成新版本草稿' : '报告草稿已生成');
  }

  async function reportSave() {
    var term = S.growthData && S.growthData.term;
    var comment = $('grComment') ? $('grComment').value.trim() :
      ((S.reportData.content || {}).teacher_comment || '');
    var r = await api('/api/v1/growth360/' + encodeURIComponent(S.growthSid) +
      '/report/edit?class_id=' + encodeURIComponent(S.cid),
      { term: term, teacher_comment: comment });
    if (!r) { return false; }
    applyReport(r);
    toast('评语已保存');
    return true;
  }

  async function reportPublish() {
    if (!S.reportData) { toast('请先生成报告草稿'); return; }
    if (S.reportData.status === 'published') { toast('该报告已发布'); return; }
    if (!$('reportModal').hidden && $('grComment')) {
      var saved = await reportSave();
      if (!saved) { return; }
    }
    if (!confirm('确认审核并发布该学期报告？发布后当前版本将冻结。')) { return; }
    var term = S.growthData && S.growthData.term;
    var r = await api('/api/v1/growth360/' + encodeURIComponent(S.growthSid) +
      '/report/publish?class_id=' + encodeURIComponent(S.cid), { term: term });
    if (!r) { return; }
    applyReport(r);
    toast('学期报告已发布并保留版本');
  }

  function certOpen() {
    if (!S.growthData) { toast('请先选择学生'); return; }
    var s = S.growthData.student;
    $('gcStudent').textContent = s.name + ' · ' + stuNo(s) + ' · ' + S.growthData.term;
    ['gcName', 'gcLevel', 'gcIssuer', 'gcNo', 'gcEvidence'].forEach(function (id) { $(id).value = ''; });
    $('gcDate').value = new Date().toISOString().slice(0, 10);
    $('certModal').hidden = false;
    $('gcName').focus();
  }

  function certClose() { $('certModal').hidden = true; }

  async function certSubmit() {
    var name = $('gcName').value.trim();
    if (!name) { toast('请填写证书名称'); return; }
    var r = await api('/api/v1/growth360/' + encodeURIComponent(S.growthSid) +
      '/certificates?class_id=' + encodeURIComponent(S.cid), {
        name: name, level: $('gcLevel').value.trim(), issuer: $('gcIssuer').value.trim(),
        cert_no: $('gcNo').value.trim(), issued_on: $('gcDate').value,
        evidence: $('gcEvidence').value.trim()
      });
    if (!r) { return; }
    certClose();
    toast(r.status === 'confirmed' ? '证书已登记并进入成长时间轴' : '证书已提交，待班主任确认');
    await loadStudents();
  }

  /* ---------------- 班级空间 ---------------- */
  function spaceCard(stu) {
    var g = stu.gender === '女' ? 'girl' : 'boy';
    return '<div class="space-card ' + g + (S.spacePick === stu.student_id ? ' picked' : '') +
      '" draggable="true" data-drag="' + esc(stu.student_id) + '" data-pick="' + esc(stu.student_id) +
      '" title="' + esc(stu.name + ' · ' + stuNo(stu)) + '">' +
      '<b>' + esc(stu.name) + '</b><span>' + esc(stuNo(stu)) + '</span></div>';
  }

  function spaceCell(cell, label) {
    return '<div class="seat-cell' + (cell.student ? ' filled' : '') +
      '" data-seat="' + cell.row + '-' + cell.col + '">' +
      '<em class="seat-no">' + esc(label) + '</em>' +
      (cell.student ? spaceCard(cell.student) : '<span class="seat-empty">空位</span>') + '</div>';
  }

  var SEAT_GROUP_OPTIONS = ['2-2-2-2', '2-4-2', '3-3-3', '4-4', '3-3', '6'];

  function seatGroupList(d) {
    var cols = d.cols || 0;
    var raw = (d.meta && d.meta.groups) || [];
    var groups = raw.map(function (x) { return parseInt(x, 10) || 0; })
      .filter(function (x) { return x > 0; });
    var sum = groups.reduce(function (a, b) { return a + b; }, 0);
    if (groups.length && sum === cols) { return groups; }
    var preset = { 1: [1], 2: [2], 3: [3], 4: [2, 2], 6: [2, 2, 2], 8: [2, 2, 2, 2] };
    if (preset[cols]) { return preset[cols].slice(); }
    var out = [], left = cols;
    while (left > 0) { var w = Math.min(2, left); out.push(w); left -= w; }
    return out.length ? out : [1];
  }

  function seatGroupPick() {
    var val = $('spaceGroups').value;
    if (val === 'custom') {
      val = ($('spaceGroupsCustom').value || '').trim().replace(/[，、\s]+/g, '-');
    }
    var parts = val.split(/[-/]/).filter(Boolean).map(function (x) { return parseInt(x, 10); });
    if (!parts.length || parts.length > 6) { return null; }
    if (parts.some(function (x) { return !(x >= 1 && x <= 6); })) { return null; }
    if (parts.reduce(function (a, b) { return a + b; }, 0) > 12) { return null; }
    return parts;
  }

  function renderSeat(d) {
    var groups = seatGroupList(d);
    var tpl = [];
    groups.forEach(function (w, i) {
      if (i) { tpl.push('12px'); }
      for (var j = 0; j < w; j += 1) { tpl.push('minmax(0,1fr)'); }
    });
    var style = 'grid-template-columns:' + tpl.join(' ');
    var hint = d.stats.seated === 0
      ? '<div class="space-empty-hint">把右侧学生卡片拖到座位即可开始排位；也可点「按学号重排」一键排好。</div>' : '';
    var heads = groups.map(function (w, i) {
      var start = 1 + groups.slice(0, i).reduce(function (a, b) { return a + b; }, 0) + i;
      return (i ? '<span class="seat-aisle" aria-hidden="true"></span>' : '') +
        '<span class="seat-group-head" style="grid-column:' + start + ' / span ' + w + '">第 ' + (i + 1) + ' 组</span>';
    }).join('');
    var html = hint +
      '<div class="space-podium"><span>讲 台</span><em>' + d.rows + ' 行 × ' + groups.join('/') +
      ' 列 · ' + groups.length + ' 组</em></div>' +
      '<div class="seat-group-heads" style="' + style + '">' + heads + '</div>' +
      '<div class="seat-grid" style="' + style + '">';
    d.grid.forEach(function (line) {
      var idx = 0;
      groups.forEach(function (w, gi) {
        if (gi) { html += '<span class="seat-aisle" aria-hidden="true"></span>'; }
        for (var j = 0; j < w && idx < line.length; j += 1, idx += 1) {
          html += spaceCell(line[idx], (gi + 1) + '组 ' + line[idx].row + '排' + (j + 1) + '座');
        }
      });
    });
    $('spaceBoard').innerHTML = html + '</div>';
  }

  function roomGender(line) {
    var boys = 0, girls = 0;
    line.forEach(function (c) {
      if (!c.student) { return; }
      if (c.student.gender === '女') { girls += 1; } else { boys += 1; }
    });
    if (boys && girls) { return 'mixed'; }
    if (girls) { return 'girl'; }
    if (boys) { return 'boy'; }
    return 'empty';
  }

  function roomLoc(name) {
    var m = /^(\d)(\d)(\d{2})$/.exec(String(name || ''));
    if (!m) { return '寝室号未按四位编号'; }
    return m[1] + '号楼 · ' + m[2] + '层 · ' + m[3] + '室';
  }

  function renderDorm(d) {
    var rooms = (d.meta && d.meta.room_names) || [];
    var fixedGenders = (d.meta && d.meta.room_genders) || [];
    var hint = d.stats.seated === 0
      ? '<div class="space-empty-hint">先把学生拖进右侧已建好的寝室；新增寝室时需选择男寝或女寝。</div>' : '';
    var labels = { boy: '男寝', girl: '女寝', mixed: '混合', empty: '待定' };
    var html = hint + d.grid.map(function (line, i) {
      var filled = line.filter(function (c) { return c.student; }).length;
      var g = fixedGenders[i] || roomGender(line);
      var name = rooms[i] || ((i + 1) + ' 号寝室');
      var beds = line.map(function (cell) { return spaceCell(cell, cell.col + ' 床'); }).join('');
      return '<div class="dorm-room ' + g + '"><div class="dorm-head"><b>' +
        esc(name) + ' 寝室</b><span class="dorm-loc">' + esc(roomLoc(name)) + '</span>' +
        '<span class="dorm-gender ' + g + '">' + labels[g] + '</span>' +
        '<span class="dorm-meta">已住 ' + filled + ' / ' + line.length + '</span>' +
        '<span class="dorm-actions">' +
        '<button type="button" data-room-edit="' + esc(name) + '">编辑</button>' +
        '<button type="button" data-room-del="' + esc(name) + '">删除</button></span></div>' +
        '<div class="dorm-beds" style="grid-template-columns:repeat(' + d.cols +
        ',minmax(0,1fr))">' + beds + '</div></div>';
    }).join('');
    $('spaceBoard').innerHTML = html || empty('暂未配置寝室');
  }

  function renderSpace() {
    var d = S.spaceData;
    if (!d) { return; }
    var st = d.stats;
    $('spaceStats').innerHTML = [
      '<span class="space-kpi">学生 <b>' + st.total + '</b></span>',
      '<span class="space-kpi ok">已排 <b>' + st.seated + '</b></span>',
      '<span class="space-kpi' + (st.unseated ? ' warn' : '') + '">未排 <b>' + st.unseated + '</b></span>',
      '<span class="space-kpi">位置 <b>' + st.capacity + '</b> 个 · 空 ' + st.empty + '</span>',
      '<span class="space-kpi">' + esc(d.kind_name) + ' · ' +
      (d.kind === 'dorm' ? (d.rows + ' 间 × 每间 ' + d.cols + ' 床')
        : (d.rows + ' 行 × ' + seatGroupList(d).length + ' 组 ' + seatGroupList(d).join('/') + ' 列')) + '</span>' +
      (S.spacePick ? '<span class="space-kpi pick">已选 <b>' + esc(S.spacePick) + '</b>，点空格落位</span>' : '')
    ].join('');
    if (d.kind === 'dorm') { renderDorm(d); } else { renderSeat(d); }
    var pool = d.pool || [];
    $('spacePoolCount').textContent = pool.length ? pool.length + ' 人' : '已排完';
    $('spacePool').innerHTML = pool.length ? pool.map(spaceCard).join('') : empty('全部学生已排位');
  }

  async function loadSpace() {
    if (!S.canViewStudents) {
      $('spaceBoard').innerHTML = empty('仅本班班主任可维护座位与寝室');
      $('spacePool').innerHTML = '';
      $('spaceStats').innerHTML = '';
      return;
    }
    $('spaceBoard').innerHTML = '<div class="loading">加载中…</div>';
    var d = await api('/api/v1/seating/' + S.spaceKind + '?class_id=' + encodeURIComponent(S.cid));
    if (!d) { $('spaceBoard').innerHTML = empty('座位数据加载失败，请稍后再试'); return; }
    S.spaceData = d;
    S.spacePick = '';
    $('spaceRows').value = d.rows;
    $('spaceCols').value = d.cols;
    var isSeat = d.kind !== 'dorm';
    $('spaceGroupsWrap').hidden = !isSeat;
    $('spaceColsWrap').hidden = isSeat;
    if (isSeat) {
      var key = seatGroupList(d).join('-');
      if (SEAT_GROUP_OPTIONS.indexOf(key) >= 0) {
        $('spaceGroups').value = key;
      } else {
        $('spaceGroups').value = 'custom';
        $('spaceGroupsCustom').value = key;
      }
    }
    $('spaceGroupsCustomWrap').hidden = !isSeat || $('spaceGroups').value !== 'custom';
    $('spaceRoomStartWrap').hidden = d.kind !== 'dorm';
    $('spaceRoomNameWrap').hidden = d.kind !== 'dorm';
    $('spaceRoomGenderWrap').hidden = d.kind !== 'dorm';
    $('spaceAddRoom').hidden = d.kind !== 'dorm';
    $('spaceRowsLabel').textContent = d.kind === 'dorm' ? '寝室数' : '行';
    $('spaceColsLabel').textContent = d.kind === 'dorm' ? '每间床位' : '列';
    if (d.kind === 'dorm') { $('spaceRoomStart').value = (d.meta && d.meta.room_start) || 1101; }
    renderSpace();
  }

  function spaceTab(kind) {
    S.spaceKind = kind;
    document.querySelectorAll('[data-space-tab]').forEach(function (b) {
      b.className = 'space-tab' + (b.dataset.spaceTab === kind ? ' on' : '');
    });
    loadSpace();
  }

  async function spaceAssign(sid, key) {
    var pos = String(key || '').split('-');
    var d = await api('/api/v1/seating/assign?class_id=' + encodeURIComponent(S.cid), {
      kind: S.spaceKind, row: parseInt(pos[0], 10), col: parseInt(pos[1], 10), student_id: sid
    });
    if (!d) { return; }
    S.spaceData = d;
    S.spacePick = '';
    renderSpace();
  }

  async function spaceUnassign(sid) {
    var d = await api('/api/v1/seating/unassign?class_id=' + encodeURIComponent(S.cid),
      { kind: S.spaceKind, student_id: sid });
    if (!d) { return; }
    S.spaceData = d;
    S.spacePick = '';
    renderSpace();
  }

  async function spaceApplyLayout() {
    var rows = parseInt($('spaceRows').value, 10);
    if (!rows) { toast('请填写行数'); return; }
    var cols = parseInt($('spaceCols').value, 10);
    var meta = null;
    if (S.spaceKind === 'dorm') {
      meta = { room_start: parseInt($('spaceRoomStart').value, 10) || 1101 };
    } else {
      var groups = seatGroupPick();
      if (!groups) { toast('分组示例 2-4-2；每组 1—6 列，总列数不超过 12'); return; }
      cols = groups.reduce(function (a, b) { return a + b; }, 0);
      meta = { groups: groups };
    }
    var d = await api('/api/v1/seating/layout?class_id=' + encodeURIComponent(S.cid),
      { kind: S.spaceKind, rows: rows, cols: cols, meta: meta });
    if (!d) { return; }
    S.spaceData = d;
    S.spacePick = '';
    $('spaceRows').value = d.rows;
    $('spaceCols').value = d.cols;
    renderSpace();
    toast('已应用 ' + d.rows + (d.kind === 'dorm' ? ' 间 × 每间 ' : ' 行 × ') +
      (d.kind === 'dorm' ? d.cols + ' 床' : seatGroupList(d).join('/') + ' 列'));
  }

  async function spaceAddRoom() {
    var name = ($('spaceRoomName').value || '').trim();
    if (!/^\d{4}$/.test(name)) { toast('寝室号需为四位数字，例如 1401'); $('spaceRoomName').focus(); return; }
    var d = await api('/api/v1/seating/room?class_id=' + encodeURIComponent(S.cid),
      { room_name: name, gender: $('spaceRoomGender').value });
    if (!d) { return; }
    S.spaceData = d;
    S.spacePick = '';
    $('spaceRoomName').value = '';
    $('spaceRows').value = d.rows;
    $('spaceCols').value = d.cols;
    renderSpace();
    toast('已新增 ' + name + ($('spaceRoomGender').value === '女' ? ' 女寝' : ' 男寝'));
  }

  function roomEditOpen(name) {
    var genders = (S.spaceData.meta && S.spaceData.meta.room_genders) || [];
    var rooms = (S.spaceData.meta && S.spaceData.meta.room_names) || [];
    var idx = rooms.indexOf(name);
    S.roomEdit = name;
    $('roomNoText').textContent = name;
    $('roomLocText').textContent = roomLoc(name);
    $('roomEditGender').value = (idx >= 0 && genders[idx] === 'girl') ? '女' : '男';
    $('roomModal').hidden = false;
  }

  function roomEditClose() {
    $('roomModal').hidden = true;
    S.roomEdit = '';
  }

  async function roomEditSave() {
    var d = await api('/api/v1/seating/room/update?class_id=' + encodeURIComponent(S.cid),
      { room_name: S.roomEdit, gender: $('roomEditGender').value });
    if (!d) { return; }
    S.spaceData = d;
    roomEditClose();
    renderSpace();
    toast('寝室信息已更新');
  }

  async function roomDelete(name) {
    if (!confirm('删除 ' + name + ' 寝室？寝室内学生将回到未分配区。')) { return; }
    var d = await api('/api/v1/seating/room/delete?class_id=' + encodeURIComponent(S.cid),
      { room_name: name });
    if (!d) { return; }
    S.spaceData = d;
    S.spacePick = '';
    renderSpace();
    toast('已删除 ' + name + ' 寝室');
  }

  async function spaceAuto() {
    if (!confirm('按学号顺序重新排位？当前位置会被覆盖。')) { return; }
    var d = await api('/api/v1/seating/auto?class_id=' + encodeURIComponent(S.cid), { kind: S.spaceKind });
    if (!d) { return; }
    S.spaceData = d;
    S.spacePick = '';
    renderSpace();
    toast('已按学号重排');
  }

  async function spaceClear() {
    if (!confirm('清空当前位置？学生全部回到未分配区。')) { return; }
    var d = await api('/api/v1/seating/clear?class_id=' + encodeURIComponent(S.cid), { kind: S.spaceKind });
    if (!d) { return; }
    S.spaceData = d;
    S.spacePick = '';
    renderSpace();
    toast('已清空，可重新拖拽排位');
  }

  function spaceExport() {
    if (!S.canViewStudents) { toast('仅本班班主任可导出'); return; }
    location.href = '/api/v1/seating/' + S.spaceKind + '/export?class_id=' + encodeURIComponent(S.cid);
  }

  function spaceExportXlsx() {
    if (!S.canViewStudents) { toast('仅本班班主任可导出'); return; }
    location.href = '/api/v1/seating/' + S.spaceKind + '/export/xlsx?class_id=' + encodeURIComponent(S.cid);
  }

  /* ---------------- 出勤统计 ---------------- */
  async function loadAttendance() {
    var d = await api('/api/v1/attendance/week?class_id=' + encodeURIComponent(S.cid));
    if (!d) { $('attBody').innerHTML = empty('出勤数据暂不可用'); return; }
    var today = d.today || { absent: [] };
    $('attKpis').innerHTML = [
      kpi('本周出勤率', na(d.week_rate, '%'), d.week),
      kpi('今日未到', { t: (today.absent || []).length + ' 人', cls: '' }, today.date),
      kpi('本周请假', { t: (d.leaves || []).length + ' 人次', cls: '' }, '已审批')
    ].join('');
    badge('attBadge', d.week, '');
    $('attBody').innerHTML = '<table><thead><tr><th>日期</th><th>实到</th><th>未到</th><th>请假</th><th>迟到</th><th>出勤率</th></tr></thead><tbody>' +
      (d.days || []).map(function (x, i) {
        var label = WEEK[i] + ' ' + (x.date || '').slice(5);
        var rate = x.rate == null ? '<span class="hint">暂无</span>' :
          '<div class="tools"><span>' + x.rate + '%</span><div class="bar"><i style="width:' +
          Math.max(0, Math.min(100, x.rate)) + '%"></i></div></div>';
        return '<tr><td>' + esc(label) + '</td><td>' + esc(x.present) + '</td><td>' + esc(x.absent) +
          '</td><td>' + esc(x.leave) + '</td><td>' + esc(x.late) + '</td><td>' + rate + '</td></tr>';
      }).join('') + '</tbody></table>';
    var absent = today.absent || [];
    badge('attTodayBadge', absent.length ? absent.length + ' 人' : '全部到齐', absent.length ? 'warn' : 'ok');
    $('attToday').innerHTML = absent.length ?
      '<table><thead><tr><th>学号</th><th>姓名</th><th>状态</th></tr></thead><tbody>' +
      absent.map(function (x) {
        return '<tr><td>' + esc(stuNo(x)) + '</td><td>' + esc(x.name) + '</td><td>' +
          esc(x.status === 'leave' ? '请假' : '未到') + '</td></tr>';
      }).join('') + '</tbody></table>' : empty('今日暂无未到学生');
    var leaves = d.leaves || [];
    badge('attLeaveBadge', leaves.length ? leaves.length + ' 条' : '无', leaves.length ? '' : 'ok');
    $('attLeave').innerHTML = leaves.length ?
      '<table><thead><tr><th>姓名</th><th>起止</th><th>类型</th></tr></thead><tbody>' +
      leaves.map(function (x) {
        return '<tr><td>' + esc(x.name || x.student_id) + '</td><td>' + esc(x.date_from) + ' ~ ' + esc(x.date_to) +
          '</td><td>' + esc(x.leave_type) + '</td></tr>';
      }).join('') + '</tbody></table>' : empty('本周没有请假记录');
  }

  /* ---------------- 学情预警 ---------------- */
  async function loadLearning() {
    var d = await api('/api/v1/learning/overview?class_id=' + encodeURIComponent(S.cid));
    if (!d) { $('learnKpis').innerHTML = ''; }
    else {
      var hw = d.homework || {};
      $('learnKpis').innerHTML = [
        kpi('作业提交率', na(hw.rate, '%'), '本周全部学科'),
        kpi('低提交学生', { t: (hw.low || []).length + ' 人', cls: '' }, '提交率低于 70%')
      ].join('');
    }
    if (!S.watching) {
      var w = await api('/api/v1/report/watchlist?session_id=' + encodeURIComponent(S.sid));
      S.watching = w && w.card ? (w.card.items || []) : null;
    }
    renderWatch($('learnWatch'), $('learnWatchBadge'), 0);
    await loadScores();
    if (d && d.homework && (d.homework.low || []).length) {
      $('learnLow').innerHTML =
        '<div class="card"><div class="card-head"><h2>作业提交偏低</h2></div><div class="card-body flush">' +
        '<table><thead><tr><th>学号</th><th>姓名</th><th>提交率</th></tr></thead><tbody>' +
        d.homework.low.map(function (x) {
          return '<tr><td>' + esc(stuNo(x)) + '</td><td>' + esc(x.name) + '</td><td>' + esc(x.rate) + '%</td></tr>';
        }).join('') + '</tbody></table></div></div>';
    } else {
      $('learnLow').innerHTML = '';
    }
  }

  async function loadScores() {
    var d = await api('/api/v1/scores/summary?class_id=' + encodeURIComponent(S.cid));
    var body = $('scoresBody');
    if (!d) { body.innerHTML = empty('暂无成绩数据，可先导入'); return; }
    var dist = d.distribution || {}, trend = d.trend || {};
    body.innerHTML = '<div class="muted" style="margin-bottom:12px">' + esc(d.exam) + ' · 共 ' + d.total + ' 人</div>' +
      '<div class="dist">' + Object.keys(dist).sort().map(function (k) {
        return '<div class="d"><span>' + esc(k) + ' 等</span><b>' + esc(dist[k]) + '</b></div>';
      }).join('') + '</div><table><thead><tr><th>趋势</th><th>人数</th></tr></thead><tbody>' +
      Object.keys(trend).map(function (k) {
        return '<tr><td>' + esc(k) + '</td><td>' + esc(trend[k]) + '</td></tr>';
      }).join('') + '</tbody></table>';
  }

  /* ---------------- 德育量化 ---------------- */
  function moralFmt(v) { return (v > 0 ? '+' : '') + v; }
  function moralDay(day, compact) {
    // compact=true 月视图：只显示 D（标题已含月份）；compact=undefined 学期视图：M/D
    var p = String(day).split('-');
    if (p.length !== 3) { return day; }
    if (compact) { return Number(p[2]); }
    return Number(p[1]) + '/' + Number(p[2]);
  }
  function moralView(name) {
    S.moralView = name;
    $('moralClassPanel').hidden = name !== 'class';
    $('moralStudentsPanel').hidden = name !== 'students';
    document.querySelectorAll('[data-moral-view]').forEach(function (b) {
      var on = b.dataset.moralView === name;
      b.classList.toggle('on', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
  }
  function moralTodayIso() {
    var d = new Date();
    return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
  }
  function moralR1(v) { return Math.round(v * 10) / 10; }
  function moralNiceMax(v) {
    var m = Math.max(2, Math.abs(Number(v) || 0));
    var step = m <= 3 ? 1 : m <= 10 ? 2 : m <= 25 ? 5 : m <= 60 ? 10 : 20;
    return Math.ceil(m / step) * step;
  }
  /* Catmull-Rom → 三次贝塞尔；控制点纵向夹紧，避免曲线冲过零线 */
  function moralCurve(pts) {
    if (!pts.length) { return ''; }
    var d = 'M' + moralR1(pts[0].x) + ',' + moralR1(pts[0].y);
    for (var i = 0; i < pts.length - 1; i++) {
      var p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      var c1x = p1.x + (p2.x - p0.x) / 6, c1y = p1.y + (p2.y - p0.y) / 6;
      var c2x = p2.x - (p3.x - p1.x) / 6, c2y = p2.y - (p3.y - p1.y) / 6;
      var lo = Math.min(p1.y, p2.y), hi = Math.max(p1.y, p2.y);
      c1y = Math.min(hi, Math.max(lo, c1y));
      c2y = Math.min(hi, Math.max(lo, c2y));
      d += ' C' + moralR1(c1x) + ',' + moralR1(c1y) + ' ' + moralR1(c2x) + ',' + moralR1(c2y) +
        ' ' + moralR1(p2.x) + ',' + moralR1(p2.y);
    }
    return d;
  }
  function moralXLabel(dayStr, compact) {
    var p = String(dayStr).split('-');
    if (p.length !== 3) { return dayStr; }
    if (compact) { return Number(p[2]); }       // 只日号：1,2,3…
    return Number(p[1]) + '/' + Number(p[2]);   // M/D
  }
  /* 刻度：能整除 2 时给 5 档，否则 3 档，避免出现 2.5 这类小数刻度 */
  function moralTicks(max) {
    return max % 2 === 0 ? [max, max / 2, 0, -max / 2, -max] : [max, 0, -max];
  }
  /* 单日视图：两根棒棒糖（得分向上、扣分向下） */
  function moralSingleDaySvg(item) {
    var W = 880, H = 236, L = 46, R = 24, T = 24, B = 46;
    var iw = W - L - R, ih = H - T - B, zero = T + ih / 2;
    var pos = Number(item.positive || 0), neg = Number(item.negative || 0);
    var max = moralNiceMax(Math.max(Math.abs(pos), Math.abs(neg))), scale = (ih / 2) / max;
    function y(v) { return zero - v * scale; }
    var out = '<svg class="moral-daily-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="当日得分与扣分">';
    moralTicks(max).forEach(function (v) {
      var yy = y(v);
      out += '<line x1="' + L + '" y1="' + moralR1(yy) + '" x2="' + (W - R) + '" y2="' + moralR1(yy) + '" class="moral-grid' + (v === 0 ? ' zero' : '') + '"></line>';
      out += '<text x="' + (L - 10) + '" y="' + moralR1(yy + 4) + '" class="moral-axis" text-anchor="end">' + esc(moralFmt(v)) + '</text>';
    });
    var gx = L + iw * 0.33, lx = L + iw * 0.61;
    out += '<line class="moral-stem gain" x1="' + moralR1(gx) + '" y1="' + moralR1(zero) + '" x2="' + moralR1(gx) + '" y2="' + moralR1(y(pos)) + '"></line>';
    out += '<circle class="moral-dot gain" cx="' + moralR1(gx) + '" cy="' + moralR1(y(pos)) + '" r="6"></circle>';
    out += '<text class="moral-big gain" x="' + moralR1(gx) + '" y="' + moralR1(y(pos) - 16) + '" text-anchor="middle">' + esc(moralFmt(pos)) + '</text>';
    out += '<text class="moral-day" x="' + moralR1(gx) + '" y="' + (H - 15) + '" text-anchor="middle">得分</text>';
    out += '<line class="moral-stem loss" x1="' + moralR1(lx) + '" y1="' + moralR1(zero) + '" x2="' + moralR1(lx) + '" y2="' + moralR1(y(neg)) + '"></line>';
    out += '<circle class="moral-dot loss" cx="' + moralR1(lx) + '" cy="' + moralR1(y(neg)) + '" r="6"></circle>';
    out += '<text class="moral-big loss" x="' + moralR1(lx) + '" y="' + moralR1(y(neg) + 26) + '" text-anchor="middle">' + esc(moralFmt(neg)) + '</text>';
    out += '<text class="moral-day" x="' + moralR1(lx) + '" y="' + (H - 15) + '" text-anchor="middle">扣分</text>';
    out += '<text class="moral-date" x="' + moralR1(gx) + '" y="' + (zero - ih / 2 - 6) + '" text-anchor="middle">' + esc(item.date) + '</text>';
    return out + '</svg>';
  }
  function moralDailySvg(items, period) {
    if (!items || !items.length) { return empty('该周期暂无德育数据'); }
    var p = period || 'week';
    if (items.length === 1) { return moralSingleDaySvg(items[0]); }
    var n = items.length;
    // W 让它够宽，超出容器后由 CSS 让容器出横向滚动条
    var W = 900, H = 236, L = 46, R = 24, T = 24, B = 46;
    if (p === 'week') { W = Math.max(900, n * 52 + L + R); }        // 7天 → 1000px，不超也安全
    else if (p === 'month') { W = Math.max(1300, n * 46 + L + R); } // 30天 → 1450px
    else if (p === 'term') { W = Math.max(1300, Math.min(n * 32 + L + R, 1800)); }
    var iw = W - L - R, ih = H - T - B, zero = T + ih / 2;
    var peak = 2;
    items.forEach(function (d) {
      peak = Math.max(peak, Math.abs(Number(d.positive || 0)), Math.abs(Number(d.negative || 0)));
    });
    var max = moralNiceMax(peak), scale = (ih / 2) / max;
    function y(v) { return zero - Number(v || 0) * scale; }
    function cx(i) { return L + (i + .5) * iw / n; }
    var gains = items.map(function (d, i) { return { x: cx(i), y: y(Math.max(0, Number(d.positive || 0))) }; });
    var losses = items.map(function (d, i) { return { x: cx(i), y: y(Math.min(0, Number(d.negative || 0))) }; });
    var out = '<svg class="moral-daily-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="全班每日得分与扣分曲线">' +
      '<defs>' +
      '<linearGradient id="moralGainFill" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="#5A9B78" stop-opacity=".30"/><stop offset="100%" stop-color="#5A9B78" stop-opacity=".02"/></linearGradient>' +
      '<linearGradient id="moralLossFill" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="#C76658" stop-opacity=".02"/><stop offset="100%" stop-color="#C76658" stop-opacity=".30"/></linearGradient>' +
      '</defs>';
    moralTicks(max).forEach(function (v) {
      var yy = y(v);
      out += '<line x1="' + L + '" y1="' + moralR1(yy) + '" x2="' + (W - R) + '" y2="' + moralR1(yy) + '" class="moral-grid' + (v === 0 ? ' zero' : '') + '"></line>';
      out += '<text x="' + (L - 10) + '" y="' + moralR1(yy + 4) + '" class="moral-axis" text-anchor="end">' + esc(moralFmt(v)) + '</text>';
    });
    // 今天位置：完整自然周 / 月内含未来日期时，用虚线标出今天
    var todayIso = moralTodayIso(), ti = -1;
    items.forEach(function (d, i) { if (d.date === todayIso) { ti = i; } });
    if (ti >= 0 && ti < n - 1) {
      out += '<line class="moral-today" x1="' + moralR1(cx(ti)) + '" y1="' + T + '" x2="' + moralR1(cx(ti)) + '" y2="' + (T + ih) + '"></line>' +
        '<text class="moral-today-label" x="' + moralR1(cx(ti)) + '" y="' + (T - 7) + '" text-anchor="middle">今天</text>';
    }
    out += '<path class="moral-area gain" d="' + moralCurve(gains) + ' L' + moralR1(gains[n - 1].x) + ',' + moralR1(zero) +
      ' L' + moralR1(gains[0].x) + ',' + moralR1(zero) + ' Z"></path>';
    out += '<path class="moral-area loss" d="' + moralCurve(losses) + ' L' + moralR1(losses[n - 1].x) + ',' + moralR1(zero) +
      ' L' + moralR1(losses[0].x) + ',' + moralR1(zero) + ' Z"></path>';
    out += '<path class="moral-line gain" d="' + moralCurve(gains) + '"></path>';
    out += '<path class="moral-line loss" d="' + moralCurve(losses) + '"></path>';
    var dotStep = n <= 14 ? 1 : Math.ceil(n / 14);
    items.forEach(function (d, i) {
      var pos = Number(d.positive || 0), neg = Number(d.negative || 0);
      var hitW = Math.max(2, iw / n);
      out += '<g><title>' + esc(d.date + '：得分 ' + moralFmt(pos) + '，扣分 ' + moralFmt(neg) +
        '，净 ' + moralFmt(d.net || 0) + '，' + (d.count || 0) + ' 条') + '</title>' +
        '<rect class="moral-hit" x="' + moralR1(cx(i) - hitW / 2) + '" y="' + T + '" width="' + moralR1(hitW) + '" height="' + ih + '"></rect></g>';
      if (i % dotStep === 0 || i === n - 1) {
        var r = n <= 14 ? 3 : 2;
        if (pos) { out += '<circle class="moral-dot gain" cx="' + moralR1(gains[i].x) + '" cy="' + moralR1(gains[i].y) + '" r="' + r + '"></circle>'; }
        if (neg) { out += '<circle class="moral-dot loss" cx="' + moralR1(losses[i].x) + '" cy="' + moralR1(losses[i].y) + '" r="' + r + '"></circle>'; }
      }
    });
    if (n <= 14) {
      items.forEach(function (d, i) {
        var pos = Number(d.positive || 0), neg = Number(d.negative || 0);
        if (pos) { out += '<text class="moral-value gain" x="' + moralR1(gains[i].x) + '" y="' + moralR1(gains[i].y - 9) + '" text-anchor="middle">' + esc(moralFmt(pos)) + '</text>'; }
        if (neg) { out += '<text class="moral-value loss" x="' + moralR1(losses[i].x) + '" y="' + moralR1(losses[i].y + 16) + '" text-anchor="middle">' + esc(moralFmt(neg)) + '</text>'; }
      });
    }
    var labStep = n <= 10 ? 1 : Math.ceil(n / 10);
    var compact = (p === 'week' || p === 'month');  // week/month 只显示日号；term 保留 M/D
    items.forEach(function (d, i) {
      if (i % labStep !== 0 && i !== n - 1) { return; }
      if (p === 'week') {
        var wk = WEEK[(new Date(d.date + 'T00:00:00').getDay() + 6) % 7];
        out += '<text class="moral-day" x="' + moralR1(cx(i)) + '" y="' + (H - 27) + '" text-anchor="middle">' + esc(wk) + '</text>';
        out += '<text class="moral-date" x="' + moralR1(cx(i)) + '" y="' + (H - 13) + '" text-anchor="middle">' + esc(moralXLabel(d.date, compact)) + '</text>';
      } else {
        out += '<text class="moral-date" x="' + moralR1(cx(i)) + '" y="' + (H - 18) + '" text-anchor="middle">' + esc(moralXLabel(d.date, compact)) + '</text>';
      }
    });
    var totalCount = items.reduce(function (s, d) { return s + Number(d.count || 0); }, 0);
    if (!totalCount) {
      out += '<text class="moral-empty-note" x="' + moralR1(L + iw / 2) + '" y="' + moralR1(zero - 12) + '" text-anchor="middle">该周期暂无已确认的德育事件</text>' +
        '<text class="moral-empty-sub" x="' + moralR1(L + iw / 2) + '" y="' + moralR1(zero + 12) + '" text-anchor="middle">在「德育台账」登记并确认事件后，这里会自动生成曲线</text>';
    }
    return out + '</svg>';
  }
  function moralCategorySvg(items, kind) {
    if (!items.length) { return empty(kind === 'gain' ? '该周期暂无已确认的加分记录' : '该周期暂无已确认的扣分记录'); }
    var w = 430, rowH = 52, h = items.length * rowH + 12;
    var max = Math.max.apply(null, items.map(function (x) { return Math.abs(x.points); }).concat([1]));
    var out = '<svg class="moral-category-svg" viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="' + (kind === 'gain' ? '得分点类别分析' : '扣分点类别分析') + '">';
    items.forEach(function (x, i) {
      var y = 10 + i * rowH, bw = Math.abs(x.points) / max * 188;
      var label = String(x.category || '其他');
      var short = label.length > 8 ? label.slice(0, 8) + '…' : label;
      out += '<g><title>' + esc(label + '：' + moralFmt(x.points) + ' 分，' + x.count + ' 次') + '</title>';
      out += '<text x="0" y="' + (y + 13) + '" class="moral-cat-label">' + esc(short) + '</text>';
      out += '<text x="0" y="' + (y + 31) + '" class="moral-cat-count">' + esc(x.count + ' 次') + '</text>';
      out += '<rect x="116" y="' + (y + 5) + '" width="188" height="16" rx="8" class="moral-cat-track"></rect>';
      out += '<rect x="116" y="' + (y + 5) + '" width="' + Math.max(3, bw) + '" height="16" rx="8" class="moral-cat-bar ' + kind + '"></rect>';
      out += '<text x="420" y="' + (y + 19) + '" text-anchor="end" class="moral-cat-value ' + kind + '">' + esc(moralFmt(x.points) + ' 分') + '</text></g>';
    });
    return out + '</svg>';
  }
  function moralScoreStyle(score) {
    var delta = score - 100;
    if (!delta) { return '--score-bg:#F7F3EA;--score-accent:#A79368;--score-ink:#6E675C'; }
    var level = Math.min(4, Math.floor((Math.abs(delta) - 1) / 2));
    var palette = delta < 0 ? [
      ['#FDF0ED', '#C97567', '#8E2F25'], ['#F8DCD6', '#BC5546', '#85241C'],
      ['#F0BDB3', '#A93E32', '#761A14'], ['#E7A093', '#923126', '#691912'],
      ['#D87B6C', '#762019', '#57100C']
    ] : [
      ['#EDF7F0', '#579A76', '#276043'], ['#D8EDDE', '#3F8460', '#20543B'],
      ['#B7DBC3', '#2E704D', '#194831'], ['#8FC4A2', '#205C3D', '#123C28'],
      ['#66A983', '#174A32', '#0D3522']
    ];
    var p = palette[level];
    return '--score-bg:' + p[0] + ';--score-accent:' + p[1] + ';--score-ink:' + p[2];
  }
  function renderMoralStudents() {
    var body = $('moralStudentCards');
    if (!S.moralData) { body.innerHTML = empty('学生量化数据暂不可用'); return; }
    var items = (S.moralData.students || []).slice();
    function byId(a, b) { return String(a.student_id).localeCompare(String(b.student_id), 'zh-CN', { numeric: true }); }
    items.sort(function (a, b) {
      if (S.moralSort === 'asc') { return a.total_score - b.total_score || byId(a, b); }
      if (S.moralSort === 'desc') { return b.total_score - a.total_score || byId(a, b); }
      return byId(a, b);
    });
    if (!items.length) { body.innerHTML = empty('本班暂无学生名册'); return; }
    body.innerHTML = items.map(function (x) {
      var delta = x.total_score - 100;
      var trend = delta > 0 ? '↑' : delta < 0 ? '↓' : '—';
      var cls = delta > 0 ? 'gain' : delta < 0 ? 'loss' : '';
      return '<button type="button" class="moral-student" data-moral-stu="' + esc(x.student_id) + '" style="' + moralScoreStyle(x.total_score) + '" title="' + esc((x.name || '') + ' · 学号 ' + stuNo(x) + ' · 正 ' + x.positive + ' 负 ' + x.negative + ' · ' + x.event_count + ' 条记录') + '">' +
        '<span class="moral-student-top"><span class="moral-student-avatar">' + esc((x.name || '生').slice(0, 1)) + '</span>' +
        '<span class="moral-student-name"><b>' + esc(x.name || stuNo(x)) + '</b><small>' + esc(stuNo(x)) + '</small></span>' +
        '<span class="moral-student-open">详情 ›</span></span>' +
        '<span class="moral-student-score"><b>' + esc(x.total_score) + '</b><em>分</em><small class="' + cls + '">' + trend + '</small></span>' +
        '<span class="moral-student-foot"><span class="gain">+' + x.positive + '</span><span class="loss">−' + x.negative + '</span><span>' + x.event_count + ' 条</span></span></button>';
    }).join('');
  }
  function moralDetailGroup(title, items, kind) {
    if (!items.length) { return ''; }
    return '<section class="moral-detail-group"><h4>' + esc(title) + '<span>' + items.length + ' 条</span></h4>' +
      items.map(function (x) {
        var status = x.status === 'confirmed' ? '已确认' : x.status === 'pending' ? '待确认 · 不计分' : '已作废 · 不计分';
        return '<div class="moral-event ' + kind + '"><div class="moral-event-head"><span>' + esc(x.event_date) + ' · ' + esc(x.category) + '</span><b>' + esc(moralFmt(x.points)) + ' 分</b></div>' +
          '<p>' + esc(x.fact || '未填写具体事实说明') + '</p><small>' + esc(x.source || '政教处事件登记') + ' · ' + esc(status) + '</small></div>';
      }).join('') + '</section>';
  }
  function moralDetailClose() { $('moralDetailModal').hidden = true; }
  function moralDetailBarSvg(daily, period) {
    var n = daily.length || 1, bw = 14, totalW = Math.max(520, n * 22 + 60);
    if (period === 'day') { bw = 36; totalW = 220; }
    else if (period === 'month') { bw = 8; totalW = Math.max(1200, n * 24 + 80); }
    else if (period === 'term') { bw = 5; totalW = Math.max(1200, Math.min(n * 18 + 80, 1680)); }
    var w = totalW, zero = 110, range = 72, left = 38, right = 14, h = 240;
    var plotW = w - left - right, max = 5;
    daily.forEach(function (d) { max = Math.max(max, Math.abs(d.net || 0)); });
    max = Math.max(5, Math.ceil(max / 5) * 5);
    function y(v) { return zero - v / max * range; }
    var out = '<svg class="student-detail-bar" viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="每日净得分">';
    [max, max / 2, 0, -max / 2, -max].forEach(function (v) {
      var yy = y(v);
      out += '<line x1="' + left + '" y1="' + yy + '" x2="' + (w - right) + '" y2="' + yy + '" class="moral-grid' + (v === 0 ? ' zero' : '') + '"></line>';
      out += '<text x="' + (left - 4) + '" y="' + (yy + 3) + '" class="moral-axis" text-anchor="end">' + moralFmt(v) + '</text>';
    });
    daily.forEach(function (d, i) {
      var center = left + (i + .5) * plotW / daily.length;
      var net = Number(d.net || 0);
      var py = y(net);
      var hh = Math.max(2, Math.abs(net) / max * range);
      if (net >= 0) {
        out += '<g><title>' + esc(d.date + ' 净 ' + moralFmt(net)) + '</title><rect x="' + (center - bw / 2) + '" y="' + py + '" width="' + bw + '" height="' + Math.max(2, zero - py) + '" rx="2" class="moral-bar-gain"></rect></g>';
      } else {
        out += '<g><title>' + esc(d.date + ' 净 ' + moralFmt(net)) + '</title><rect x="' + (center - bw / 2) + '" y="' + zero + '" width="' + bw + '" height="' + hh + '" rx="2" class="moral-bar-loss"></rect></g>';
      }
      // 日期标签：周/月只显示 D（标题已含"本周"/"本月"）；term 稀疏；day 全部
      var showLabel = true, compact = false;
      if (period === 'week') {
        compact = true;
      } else if (period === 'month') {
        showLabel = (i % Math.max(1, Math.ceil(n / 15)) === 0);
        compact = true;
      } else if (period === 'term') {
        showLabel = (i % Math.max(1, Math.ceil(n / 10)) === 0);
      }
      if (showLabel) out += '<text x="' + center + '" y="' + (h - 4) + '" class="axis-label">' + esc(moralDay(d.date, compact)) + '</text>';
    });
    return out + '</svg>';
  }
  function moralDetailLineSvg(daily, period) {
    // 累计净得分折线
    var n = daily.length || 1, totalW = Math.max(520, n * 22 + 60);
    if (period === 'day') totalW = 220;
    else if (period === 'month') totalW = Math.max(1200, n * 24 + 80);
    else if (period === 'term') totalW = Math.max(1200, Math.min(n * 18 + 80, 1680));
    var w = totalW, zero = 110, range = 72, left = 38, right = 14, h = 240;
    var plotW = w - left - right;
    var cum = 0, points = [];
    daily.forEach(function (d) {
      cum += Number(d.net || 0);
      points.push({ date: d.date, v: cum });
    });
    var vmax = 5;
    points.forEach(function (p) { vmax = Math.max(vmax, Math.abs(p.v)); });
    vmax = Math.max(5, Math.ceil(vmax / 5) * 5);
    function y(v) { return zero - v / vmax * range; }
    var out = '<svg class="student-detail-line" viewBox="0 0 ' + w + ' ' + h + '" role="img" aria-label="累计净得分折线">';
    [vmax, vmax / 2, 0, -vmax / 2, -vmax].forEach(function (v) {
      var yy = y(v);
      out += '<line x1="' + left + '" y1="' + yy + '" x2="' + (w - right) + '" y2="' + yy + '" class="axis"></line>';
      out += '<text x="' + (left - 4) + '" y="' + (yy + 3) + '" class="axis-label" text-anchor="end">' + moralFmt(v) + '</text>';
    });
    var poly = [];
    points.forEach(function (p, i) {
      var xx = left + (i + .5) * plotW / points.length;
      poly.push(xx + ',' + y(p.v));
    });
    out += '<polyline class="line-path" points="' + poly.join(' ') + '"></polyline>';
    points.forEach(function (p, i) {
      var xx = left + (i + .5) * plotW / points.length;
      var yy = y(p.v);
      out += '<circle class="line-dot" cx="' + xx + '" cy="' + yy + '" r="2.2"><title>' + esc(p.date + ' 累计 ' + moralFmt(p.v)) + '</title></circle>';
      var showLabel = true, compact = false;
      if (period === 'week') {
        compact = true;
      } else if (period === 'month') {
        showLabel = (i % Math.max(1, Math.ceil(n / 15)) === 0);
        compact = true;
      } else if (period === 'term') {
        showLabel = (i % Math.max(1, Math.ceil(n / 10)) === 0);
      }
      if (showLabel) out += '<text x="' + xx + '" y="' + (h - 4) + '" class="axis-label">' + esc(moralDay(p.date, compact)) + '</text>';
    });
    return out + '</svg>';
  }
  async function moralDetailOpen(sid) {
    var stu = ((S.moralData && S.moralData.students) || []).filter(function (x) { return x.student_id === sid; })[0];
    if (!stu || !S.moralData) { return; }
    var period = S.moralPeriod || 'week';
    var periodLabel = (S.moralData && (S.moralData.period_title || S.moralData.period_label)) ||
      (period === 'day' ? '当日' : period === 'month' ? '本月' : period === 'term' ? '本学期' : '本周');
    $('moralDetailTitle').textContent = stu.name + ' · ' + periodLabel + '德育明细';
    $('moralDetailBody').innerHTML = '<div class="loading">正在加载个人明细…</div>';
    $('moralDetailModal').hidden = false;
    var d = await api('/api/v1/moral/records?class_id=' + encodeURIComponent(S.cid) + '&student_id=' + encodeURIComponent(sid) +
      '&start=' + encodeURIComponent(S.moralData.start) + '&end=' + encodeURIComponent(S.moralData.end));
    if (!d) { $('moralDetailBody').innerHTML = empty('个人明细加载失败'); return; }
    var items = d.items || [];
    // 前端按日聚合出每日净得分（学生个人可能有某些天无记录 → 净 0）
    var dailyMap = {}, start = S.moralData.start, end = S.moralData.end;
    (items || []).forEach(function (x) {
      if (x.status !== 'confirmed') return;
      dailyMap[x.event_date] = (dailyMap[x.event_date] || 0) + Number(x.points || 0);
    });
    // 生成完整日期序列
    var daily = [];
    if (start && end) {
      var cur = new Date(start + 'T00:00:00'), endD = new Date(end + 'T00:00:00');
      for (var i = 0; cur <= endD; i++) {
        var dstr = cur.toISOString().slice(0, 10);
        daily.push({ date: dstr, net: dailyMap[dstr] || 0 });
        cur.setDate(cur.getDate() + 1);
      }
    }
    var losses = items.filter(function (x) { return x.points < 0; });
    var gains = items.filter(function (x) { return x.points >= 0; });
    $('moralDetailBody').innerHTML = '<div class="moral-detail-summary" style="' + moralScoreStyle(stu.total_score) + '">' +
      '<div><span>' + esc(stu.student_id) + '</span><b>' + esc(stu.name) + '</b></div><strong>' + esc(stu.total_score) + '<small> 分</small></strong>' +
      '<p>' + esc(periodLabel) + ' · 得分 ' + moralFmt(stu.positive) + ' · 扣分 ' + moralFmt(stu.negative) + ' · 基准 100</p></div>' +
      '<div class="moral-detail-charts">' +
      '<div class="moral-detail-chart"><h4>每日净得分</h4>' + moralDetailBarSvg(daily, period) + '</div>' +
      '<div class="moral-detail-chart"><h4>累计净得分趋势</h4>' + moralDetailLineSvg(daily, period) + '</div>' +
      '</div>' +
      (items.length ? moralDetailGroup('扣分明细', losses, 'loss') + moralDetailGroup('加分明细', gains, 'gain') : empty(periodLabel + '暂无德育事件记录')) +
      '<p class="moral-detail-note">仅已确认事件计入总得分；待确认与已作废事件仅作过程留痕。</p>';
  }
  /* 锚点控件：月用月份选择器，学期用下拉 */
  function moralSyncAnchor(d) {
    var p = (d && d.period) || S.moralPeriod || 'month';
    var start = (d && d.start) || '';
    $('moralAnchorMonthWrap').hidden = p !== 'month';
    $('moralAnchorTermWrap').hidden = p !== 'term';
    if (start) { $('moralAnchorMonth').value = start.slice(0, 7); }
    var terms = (d && d.terms) || S.moralTerms || [];
    if (terms.length) {
      S.moralTerms = terms;
      var sel = $('moralAnchorTerm');
      sel.innerHTML = terms.map(function (t) {
        return '<option value="' + esc(t.start) + '">' + esc(t.title) + '（' + esc(t.start) + ' ~ ' + esc(t.end) + '）</option>';
      }).join('');
      sel.value = start;
      if (!sel.value) { sel.value = (terms.filter(function (t) { return t.current; })[0] || terms[0]).start; }
    }
  }
  async function loadMoral() {
    var p = S.moralPeriod || 'month';
    var url = '/api/v1/moral/summary?session_id=' + encodeURIComponent(S.sid) + '&class_id=' + encodeURIComponent(S.cid) +
      '&period=' + encodeURIComponent(p);
    if (p === 'month' && S.moralMonth) { url += '&anchor=' + encodeURIComponent(S.moralMonth + '-01'); }
    if (p === 'term' && S.moralTerm) { url += '&anchor=' + encodeURIComponent(S.moralTerm); }
    var d = await api(url);
    S.moralData = d;
    if (!d) {
      $('moralStrip').innerHTML = ''; $('moralDailyChart').innerHTML = empty('德育图表暂不可用');
      $('moralGainChart').innerHTML = ''; $('moralLossChart').innerHTML = '';
      $('moralPending').innerHTML = empty('德育数据暂不可用'); $('moralStudentCards').innerHTML = empty('学生量化数据暂不可用');
      badge('moralPendingBadge', '不可用', 'danger');
    } else {
      S.moralMonth = (d.start || '').slice(0, 7);
      S.moralTerm = d.period === 'term' ? d.start : S.moralTerm;
      S.moralTerms = d.terms || S.moralTerms;
      $('moralPeriod').innerHTML = '<b>' + esc(d.period_title || d.period_label || '本月') + '</b>' +
        '<span>' + esc(d.start + ' — ' + d.end) + ' · ' + d.size + ' 人 · 基准 100 分</span>';
      $('moralOverviewTitle').textContent = (d.period_title || d.period_label || '本月') + '班级量化脉搏';
      moralSyncAnchor(d);
      $('moralStrip').innerHTML =
        '<div class="m"><span>' + esc(d.period_label || '本月') + '净变化</span><b>' + moralFmt(d.week_delta) + '<small> 分</small></b></div>' +
        '<div class="m"><span>得分</span><b class="gain">' + moralFmt(d.positive_points) + '<small> 分</small></b></div>' +
        '<div class="m"><span>扣分</span><b class="loss">' + moralFmt(d.negative_points) + '<small> 分</small></b></div>' +
        '<div class="m"><span>已确认事件</span><b>' + d.confirmed_count + '<small> 条</small></b></div>' +
        '<div class="m"><span>待确认事件</span><b>' + (d.pending || []).length + '<small> 条</small></b></div>';
      $('moralDailyChart').innerHTML = moralDailySvg(d.daily || [], d.period || S.moralPeriod);
      badge('moralDailyBadge', d.size + ' 人 · ' + (d.period_title || d.period_label || ''), '');
      $('moralGainChart').innerHTML = moralCategorySvg(d.positive_categories || [], 'gain');
      $('moralLossChart').innerHTML = moralCategorySvg(d.negative_categories || [], 'loss');
      badge('moralGainBadge', (d.positive_categories || []).length + ' 类', 'ok');
      badge('moralLossBadge', (d.negative_categories || []).length + ' 类', (d.negative_categories || []).length ? 'danger' : 'ok');
      renderMoralStudents();
      badge('moralPendingBadge', (d.pending || []).length ? (d.pending || []).length + ' 条' : '无',
        (d.pending || []).length ? 'warn' : 'ok');
      if (!(d.pending || []).length) { $('moralPending').innerHTML = empty('没有待确认的事件'); }
      else {
        $('moralPending').innerHTML = '<table><thead><tr><th>学生</th><th>类别</th><th>分值</th><th>说明</th><th>操作</th></tr></thead><tbody>' +
          d.pending.map(function (p) {
            return '<tr><td>' + esc(p.student_masked) + '</td><td>' + esc(p.category) + '</td><td>' +
              moralFmt(p.points) + '</td><td>' + esc(p.fact) + '</td><td><div class="tools">' +
              '<button type="button" class="btn sm primary" data-moral="' + esc(p.id) + '" data-d="confirm">确认</button>' +
              '<button type="button" class="btn sm ghost" data-moral="' + esc(p.id) + '" data-d="cancel">作废</button>' +
              '</div></td></tr>';
          }).join('') + '</tbody></table>';
      }
    }
    await loadMoralLog();
  }
  async function loadMoralLog() {
    var d = await api('/api/v1/moral/records?class_id=' + encodeURIComponent(S.cid));
    var body = $('moralLog'), items = d ? (d.items || []) : null;
    if (!items) { body.innerHTML = empty('台账加载失败'); badge('moralLogBadge', '不可用', 'danger'); return; }
    badge('moralLogBadge', items.length ? items.length + ' 条' : '暂无', items.length ? '' : 'ok');
    if (!items.length) { body.innerHTML = empty('还没有德育记录'); return; }
    body.innerHTML = '<table><thead><tr><th>日期</th><th>学生</th><th>类别</th><th>分值</th><th>状态</th></tr></thead><tbody>' +
      items.slice(0, 80).map(function (x) {
        var pos = x.polarity === 'positive';
        var st = x.status === 'confirmed' ? '<span class="tag pos">已确认</span>' :
          x.status === 'pending' ? '<span class="tag pending">待确认</span>' : '<span class="tag neg">已作废</span>';
        return '<tr><td>' + esc(x.event_date) + '</td><td>' + esc(x.name || stuNo(x)) + '</td><td>' +
          esc(x.category) + '</td><td>' + (pos ? '+' : '') + esc(x.points) + '</td><td>' + st + '</td></tr>';
      }).join('') + '</tbody></table>';
  }

  /* ---------------- 班务减负 ---------------- */
  async function loadAffairs() {
    var d = await api('/api/v1/todo/list?session_id=' + encodeURIComponent(S.sid));
    var body = $('affairsBody');
    if (!d) { body.innerHTML = empty('班务数据暂不可用'); return; }
    var items = d.items || [];
    badge('affairsBadge', items.length ? items.length + ' 项待办' : '暂无', items.length ? 'warn' : 'ok');
    body.innerHTML = items.length ?
      '<table><thead><tr><th>时间</th><th>类型</th><th>事由</th><th>说明</th><th>操作</th></tr></thead><tbody>' +
      items.map(function (x) {
        return '<tr><td>' + esc((x.ts || '').replace('T', ' ').slice(5, 16)) + '</td><td>' +
          esc((d.kinds && d.kinds[x.kind]) || x.kind) + '</td><td>' + esc(x.category) + '</td><td>' +
          esc(x.fact || '—') + '</td><td><button type="button" class="btn sm" data-close="' + esc(x.id) + '">完成</button></td></tr>';
      }).join('') + '</tbody></table>' : empty('本周没有待办事项');
    var s = await api('/api/v1/todo/referrals?session_id=' + encodeURIComponent(S.sid));
    var slips = s && s.slips ? s.slips : [];
    badge('slipBadge', slips.length ? slips.length + ' 张' : '无', slips.length ? '' : 'ok');
    $('slipBody').innerHTML = slips.length ?
      '<table><thead><tr><th>学生</th><th>事由</th><th>状态</th></tr></thead><tbody>' +
      slips.map(function (x) {
        return '<tr><td>' + esc(stuNo(x)) + '</td><td>' + esc(x.category) + '</td><td>' +
          '<span class="tag">' + esc(x.status_text || x.status) + '</span></td></tr>';
      }).join('') + '</tbody></table>' : empty('暂无转介回执');
  }

  /* ---------------- 家校协同 ---------------- */
  async function loadFamily() {
    var d = await api('/api/v1/todo/list?session_id=' + encodeURIComponent(S.sid));
    var items = d ? (d.items || []).filter(function (x) { return x.kind === 'notify'; }) : null;
    if (!items) { $('famBody').innerHTML = empty('沟通记录加载失败'); badge('famBadge', '不可用', 'danger'); return; }
    badge('famBadge', items.length ? items.length + ' 条' : '暂无', items.length ? '' : 'ok');
    $('famBody').innerHTML = items.length ?
      '<table><thead><tr><th>时间</th><th>分类</th><th>状态</th><th>操作</th></tr></thead><tbody>' +
      items.map(function (x) {
        return '<tr><td>' + esc((x.ts || '').replace('T', ' ').slice(5, 16)) + '</td><td>' + esc(x.category) +
          '</td><td><span class="tag">' + esc(x.status === 'closed' ? '已归档' : '已登记') + '</span></td><td>' +
          '<button type="button" class="btn sm" data-close="' + esc(x.id) + '">归档</button></td></tr>';
      }).join('') + '</tbody></table>' : empty('还没有家校沟通记录，上方登记一条');
  }
  async function submitFamily() {
    var cat = $('famCategory').value;
    var d = await api('/api/v1/files/family/note', { category: cat });
    if (d) { toast(d.note || '已登记'); loadFamily(); loadHome(); }
  }

  /* ---------------- 数据备份 ---------------- */
  async function loadMapping() {
    var d = await api('/api/v1/org/bindings?limit=8');
    if (!d) { $('mapBody').innerHTML = empty('映射数据暂不可用'); return; }
    var s = d.stats || {}, p = s.by_portal || {};
    badge('mapBadge', (s.bound_users || 0) + ' 人 / ' + (s.bindings || 0) + ' 条',
      s.bound_users ? 'ok' : 'warn');
    $('mapBody').innerHTML =
      '<div class="muted" style="font-size:12.5px;margin-bottom:8px">班主任 ' + (s.headteachers || 0) +
      ' 人；班主任端 ' + (p.headteacher || 0) + ' · 教师端 ' + (p.teacher || 0) +
      ' · 行政端 ' + (p.admin || 0) + '</div>' +
      '<table><thead><tr><th>账号</th><th>姓名</th><th>职务</th><th>端</th><th>班级</th><th>复核</th></tr></thead><tbody>' +
      (d.items || []).map(function (x) {
        return '<tr><td>' + esc(x.userid) + '</td><td>' + esc(x.name) + '</td><td>' +
          esc(x.post_name) + '</td><td>' + esc({ headteacher: '班主任端', teacher: '教师端', admin: '行政端' }[x.portal] || x.portal) +
          '</td><td>' + esc((JSON.parse(x.class_ids || '[]') || []).join(',')) + '</td><td>' +
          esc(x.review_status) + '</td></tr>';
      }).join('') + '</tbody></table>';
  }

  async function loadData() {
    loadMapping();
    var d = await api('/api/v1/domains/status');
    var body = $('domainBody');
    if (!d) { body.innerHTML = empty('数据域状态暂不可用'); return; }
    var list = d.domains || [];
    var on = list.filter(function (x) { return /已接入|已有|试点已有/.test(x.status); }).length;
    badge('domainBadge', on + ' / ' + list.length + ' 个数据域已接入', on ? 'ok' : 'warn');
    body.innerHTML = '<div class="domain-list">' + list.map(function (x) {
      var cls = /隔离/.test(x.status) ? 'danger' : (/已接入|已有|试点已有/.test(x.status) ? 'ok' : 'warn');
      return '<div class="row"><span>' + esc(x.id) + '. ' + esc(x.name) + '</span>' +
        '<span class="badge ' + cls + '">' + esc(x.status) + '</span></div>';
    }).join('') + '</div>';
  }

  /* ---------------- 文件 ---------------- */
  function download(kind, mode) {
    var base = mode === 'template' ? '/api/v1/files/template/' : '/api/v1/files/export/';
    location.href = base + kind + '?class_id=' + encodeURIComponent(S.cid);
  }
  function pickFile(kind) {
    S.kind = kind;
    var input = $('fileInput'); input.value = ''; input.click();
  }
  async function upload(file) {
    var fd = new FormData(); fd.append('file', file);
    var url = '/api/v1/files/import/' + S.kind + '?class_id=' + encodeURIComponent(S.cid);
    var r = await fetch(url, { method: 'POST', body: fd, credentials: 'same-origin' });
    if (r.status === 401) { location.href = '/api/v1/login'; return; }
    var j = await r.json().catch(function () { return {}; });
    if (!r.ok || j.code !== 0) { toast(j.error || '导入失败'); return; }
    var d = j.data || {};
    toast('导入完成：新增 ' + d.added + '，更新 ' + d.updated + '，跳过 ' + d.skipped);
    if (S.kind === 'students') { loadStudents(); }
    if (S.kind === 'scores') { loadScores(); }
    if (S.view === 'home') { loadHome(); }
  }

  /* ---------------- 操作 ---------------- */
  document.addEventListener('click', async function (e) {
    var mp = e.target.closest('[data-moral-period]');
    if (mp) {
      var period = mp.dataset.moralPeriod;
      if (period === S.moralPeriod) return;
      S.moralPeriod = period;
      document.querySelectorAll('.moral-period-seg [data-moral-period]').forEach(function (b) {
        var on = b.dataset.moralPeriod === period;
        b.classList.toggle('on', on);
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      loadMoral();
      return;
    }
    var mv = e.target.closest('[data-moral-view]');
    if (mv) { moralView(mv.dataset.moralView); return; }
    var ms = e.target.closest('[data-moral-stu]');
    if (ms) { moralDetailOpen(ms.dataset.moralStu); return; }
    var gf = e.target.closest('[data-gf]');
    if (gf) { S.growthFilter = gf.dataset.gf; loadStudents(); return; }
    var gd = e.target.closest('[data-gdim]');
    if (gd) {
      S.growthDim = S.growthDim === gd.dataset.gdim ? '' : gd.dataset.gdim;
      renderGrowthDetail();
      return;
    }
    var gadd = e.target.closest('[data-growth-add]');
    if (gadd) { growthOpen(); return; }
    var certAdd = e.target.closest('[data-cert-add]');
    if (certAdd) { certOpen(); return; }
    var reportButton = e.target.closest('[data-report-open],[data-report-generate],[data-report-save],[data-report-publish]');
    if (reportButton) {
      if (reportButton.hasAttribute('data-report-open')) { reportOpen(); }
      else if (reportButton.hasAttribute('data-report-generate')) { reportGenerate(); }
      else if (reportButton.hasAttribute('data-report-save')) { reportSave(); }
      else { reportPublish(); }
      return;
    }
    var gc = e.target.closest('[data-gconfirm],[data-greturn]');
    if (gc) {
      var isConfirm = gc.hasAttribute('data-gconfirm');
      growthConfirm(isConfirm ? gc.dataset.gconfirm : gc.dataset.greturn,
        isConfirm ? 'confirm' : 'return');
      return;
    }
    var stu = e.target.closest('[data-stu]');
    if (stu) { loadGrowthStudent(stu.dataset.stu); return; }
    var b = e.target.closest('[data-import],[data-export],[data-template],[data-refer],[data-moral],[data-close],[data-backup],[data-map-gen],[data-map-csv],[data-focus-del],[data-fb-read],[data-jump]');
    if (!b) { return; }
    if (b.dataset.jump) {
      var jump = b.dataset.jump;
      if (jump === 'students' || jump === 'attendance') { show(jump); return; }
      var target = jump === 'home-focus' ? 'focusBody' : 'fbBody';
      if ($(target)) { $(target).scrollIntoView({ behavior: 'smooth', block: 'center' }); }
      return;
    }
    if (b.dataset.focusDel) { await removeFocus(b.dataset.focusDel); return; }
    if (b.dataset.fbRead) { await readFeedback(b.dataset.fbRead); return; }
    if (b.hasAttribute('data-map-csv')) { location.href = '/api/v1/org/bindings.csv'; return; }
    if (b.hasAttribute('data-map-gen')) {
      if (!confirm('按账号表重新生成职务与班级映射？已确认的人工修正会保留。')) { return; }
      var mg = await api('/api/v1/org/bindings/generate', {});
      if (mg) { toast('已生成：' + mg.bindings + ' 条映射'); loadMapping(); }
      return;
    }
    if (b.hasAttribute('data-backup')) {
      location.href = '/api/v1/files/backup/zip?class_id=' + encodeURIComponent(S.cid);
      return;
    }
    if (b.dataset.import) { pickFile(b.dataset.import); return; }
    if (b.dataset.export) { download(b.dataset.export, 'export'); return; }
    if (b.dataset.template) { download(b.dataset.template, 'template'); return; }
    if (b.dataset.refer) {
      var sel = b.parentNode.querySelector('select');
      var cat = sel ? sel.value : CATS[0];
      if (!confirm('按“' + cat + '”转介该学生？')) { return; }
      var r = await api('/api/v1/todo/refer', { session_id: S.sid, student_id: b.dataset.refer, category: cat });
      if (r) { toast('已转介'); loadWatch(); loadTodo(); }
      return;
    }
    if (b.dataset.moral) {
      var dec = b.dataset.d;
      if (!confirm(dec === 'confirm' ? '确认该事件计入德育分？' : '确认作废该事件？')) { return; }
      var m = await api('/api/v1/moral/confirm', { session_id: S.sid, event_id: b.dataset.moral, decision: dec });
      if (m) { toast(m.reply || '已处理'); loadMoral(); }
      return;
    }
    if (b.dataset.close) {
      if (!confirm('确认完成并销号？')) { return; }
      var c = await api('/api/v1/todo/close', { session_id: S.sid, item_id: b.dataset.close });
      if (c) { toast('已完成'); loadTodo(); loadAffairs(); loadFamily(); }
    }
  });

  $('fileInput').addEventListener('change', function () {
    if (this.files && this.files[0]) { upload(this.files[0]); }
  });
  $('btnArchive').addEventListener('click', archive);
  $('btnFocusAdd').addEventListener('click', addFocus);
  $('logout').addEventListener('click', function () { location.href = '/api/v1/logout'; });
  $('famSubmit').addEventListener('click', submitFamily);
  $('gmClose').addEventListener('click', growthClose);
  $('gmCancel').addEventListener('click', growthClose);
  $('gmSubmit').addEventListener('click', growthSubmit);
  $('gmDim').addEventListener('change', growthFillSubs);
  $('grClose').addEventListener('click', reportClose);
  $('gcClose').addEventListener('click', certClose);
  $('gcCancel').addEventListener('click', certClose);
  $('gcSubmit').addEventListener('click', certSubmit);
  $('growthModal').addEventListener('click', function (e) {
    if (e.target === this) { growthClose(); }
  });
  $('reportModal').addEventListener('click', function (e) {
    if (e.target === this) { reportClose(); }
  });
  $('certModal').addEventListener('click', function (e) {
    if (e.target === this) { certClose(); }
  });
  $('roomModal').addEventListener('click', function (e) {
    if (e.target === this) { roomEditClose(); }
  });
  $('roomModalX').addEventListener('click', roomEditClose);
  $('roomModalCancel').addEventListener('click', roomEditClose);
  $('roomEditSave').addEventListener('click', roomEditSave);
  $('moralSort').addEventListener('change', function () { S.moralSort = this.value; renderMoralStudents(); });
  $('moralAnchorMonth').addEventListener('change', function () {
    if (!this.value) { return; }
    S.moralMonth = this.value;
    loadMoral();
  });
  $('moralAnchorTerm').addEventListener('change', function () {
    if (!this.value) { return; }
    S.moralTerm = this.value;
    loadMoral();
  });
  $('moralDetailX').addEventListener('click', moralDetailClose);
  $('moralDetailModal').addEventListener('click', function (e) {
    if (e.target === this) { moralDetailClose(); }
  });
  $('spaceBoard').addEventListener('click', function (e) {
    var edit = e.target.closest('[data-room-edit]');
    if (edit) { roomEditOpen(edit.dataset.roomEdit); return; }
    var del = e.target.closest('[data-room-del]');
    if (del) { roomDelete(del.dataset.roomDel); }
  });
  document.addEventListener('change', function (e) {
    var term = e.target.closest('[data-gterm]');
    if (term) { loadGrowthStudent(S.growthSid, term.value); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key !== 'Escape') { return; }
    if (!$('growthModal').hidden) { growthClose(); }
    if (!$('reportModal').hidden) { reportClose(); }
    if (!$('certModal').hidden) { certClose(); }
    if (!$('roomModal').hidden) { roomEditClose(); }
    if (!$('moralDetailModal').hidden) { moralDetailClose(); }
  });

  $('spaceTabs').addEventListener('click', function (e) {
    var b = e.target.closest('[data-space-tab]');
    if (b) { spaceTab(b.dataset.spaceTab); }
  });
  $('spaceApply').addEventListener('click', spaceApplyLayout);
  $('spaceAuto').addEventListener('click', spaceAuto);
  $('spaceClear').addEventListener('click', spaceClear);
  $('spaceExport').addEventListener('click', spaceExport);
  $('spaceExportXlsx').addEventListener('click', spaceExportXlsx);
  $('spaceAddRoom').addEventListener('click', spaceAddRoom);
  $('spaceGroups').addEventListener('change', function () {
    $('spaceGroupsCustomWrap').hidden = this.value !== 'custom';
    if (this.value === 'custom') { $('spaceGroupsCustom').focus(); }
  });

  document.addEventListener('click', function (e) {
    var pick = e.target.closest('[data-pick]');
    if (pick) {
      var sid = pick.dataset.pick;
      S.spacePick = S.spacePick === sid ? '' : sid;
      renderSpace();
      return;
    }
    var seat = e.target.closest('[data-seat]');
    if (!seat) { return; }
    if (!S.spacePick) { toast('先点一名学生，再点目标位置'); return; }
    spaceAssign(S.spacePick, seat.dataset.seat);
  });

  document.addEventListener('dragstart', function (e) {
    var card = e.target.closest('[data-drag]');
    if (!card) { return; }
    e.dataTransfer.setData('text/plain', card.dataset.drag);
    e.dataTransfer.effectAllowed = 'move';
    card.classList.add('dragging');
  });
  document.addEventListener('dragend', function (e) {
    var card = e.target.closest('[data-drag]');
    if (card) { card.classList.remove('dragging'); }
    document.querySelectorAll('.drop-on').forEach(function (el) { el.classList.remove('drop-on'); });
  });
  function dragEdgeScroll(el, y) {
    if (!el) { return; }
    var box = el.getBoundingClientRect();
    var edge = 64, step = 18;
    if (y > box.bottom - edge) { el.scrollTop += step; }
    else if (y < box.top + edge) { el.scrollTop -= step; }
  }

  document.addEventListener('dragover', function (e) {
    dragEdgeScroll($('spaceBoard'), e.clientY);
    dragEdgeScroll($('spacePool'), e.clientY);
    var zone = e.target.closest('[data-seat],[data-pool-drop]');
    if (!zone) { return; }
    e.preventDefault();
    zone.classList.add('drop-on');
  });
  document.addEventListener('dragleave', function (e) {
    var zone = e.target.closest('[data-seat],[data-pool-drop]');
    if (zone) { zone.classList.remove('drop-on'); }
  });
  document.addEventListener('drop', function (e) {
    var zone = e.target.closest('[data-seat],[data-pool-drop]');
    if (!zone) { return; }
    e.preventDefault();
    zone.classList.remove('drop-on');
    var sid = e.dataTransfer.getData('text/plain');
    if (!sid) { return; }
    if (zone.hasAttribute('data-pool-drop')) { spaceUnassign(sid); return; }
    spaceAssign(sid, zone.dataset.seat);
  });

  var st;
  $('stuSearch').addEventListener('input', function () {
    clearTimeout(st); st = setTimeout(loadStudents, 300);
  });

  /* ---------------- 路由 ---------------- */
  var LOAD = { home: loadHome, students: loadStudents, space: loadSpace, attendance: loadAttendance,
    learning: loadLearning, moral: loadMoral, affairs: loadAffairs, family: loadFamily, data: loadData };
  function show(name) {
    if (!S.canViewStudents && name !== 'home' && name !== 'data') { return; }
    if (name === 'data' && !S.canViewData) { return; }
    S.view = name;
    var btns = document.querySelectorAll('#nav button');
    for (var i = 0; i < btns.length; i++) { btns[i].className = btns[i].dataset.view === name ? 'on' : ''; }
    var views = document.querySelectorAll('.view');
    for (var j = 0; j < views.length; j++) { views[j].className = 'view' + (views[j].id === 'view-' + name ? ' on' : ''); }
    $('pageTitle').textContent = TITLES[name][0];
    $('pageSub').textContent = TITLES[name][1];
    var content = document.querySelector('.content');
    if (content) { content.className = 'content' + (name === 'space' || name === 'students' ? ' wide' : ''); }
    if (LOAD[name]) { LOAD[name](); }
  }
  $('nav').addEventListener('click', function (e) {
    var b = e.target.closest('button[data-view]');
    if (b) { show(b.dataset.view); }
  });

  async function boot() {
    var d = new Date();
    $('today').textContent = d.getFullYear() + ' 年 ' + (d.getMonth() + 1) + ' 月 ' + d.getDate() + ' 日';
    var auto = await api('/api/v1/portal/auto', {});
    if (!auto || !auto.ctx) {
      $('userName').textContent = '身份识别失败';
      $('userRole').textContent = '请退出后重新登录';
      return;
    }
    var ctx = auto.ctx;
    S.sid = ctx.session_id;
    S.cid = (ctx.class_ids && ctx.class_ids[0]) || '';
    S.name = ctx.name || '';
    $('userName').textContent = S.name || ctx.user_id;
    $('userRole').textContent = ctx.post_name || '';
    $('avatar').textContent = (S.name || '班').slice(0, 1);
    var me = await api('/api/v1/me');
    S.canViewStudents = !!(me && me.can_view_students);
    if (!S.cid && me && me.class_ids && me.class_ids.length) { S.cid = me.class_ids[0]; }
    $('classChip').textContent = S.cid ? S.cid + ' 班' : '—';
    if (!S.canViewStudents) {
      ['students', 'space', 'attendance', 'learning', 'moral', 'affairs', 'family'].forEach(function (v) {
        var b = document.querySelector('#nav button[data-view="' + v + '"]');
        if (b) { b.style.display = 'none'; }
      });
    }
    if (me && me.can_manage_teachers === false) {
      var tc = $('teacherCard');
      if (tc) { tc.style.display = 'none'; }
      if (!S.canViewStudents) {
        S.canViewData = false;
        var db = document.querySelector('#nav button[data-view="data"]');
        if (db) { db.style.display = 'none'; }
      }
    }
    show('home');
  }
  boot();
})();
