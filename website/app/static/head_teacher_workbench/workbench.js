/* 班主任工作台 · 九大模块前端（原生 fetch，无额外依赖） */
(function () {
  'use strict';

  var S = { ctx: null, sid: '', weekly: null, loaded: {} };
  var CATEGORIES = ['归寝异常', '缺勤关注', '学业联系', '行为观察', '家长告知', '其他'];

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function na(v) { return (v === null || v === undefined || v === '') ? '暂不可用' : v; }
  var toastTimer = null;
  function toast(m) {
    var t = $('toast'); t.textContent = m; t.style.display = 'block';
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.style.display = 'none'; }, 3000);
  }

  async function api(path, body, method) {
    var opt = {
      method: method || (body ? 'POST' : 'GET'),
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin'
    };
    if (body) opt.body = JSON.stringify(body);
    try {
      var r = await fetch(path, opt);
      if (r.status === 401) {
        location.href = '/api/v1/login?next=' + encodeURIComponent(location.pathname + location.search);
        return null;
      }
      var j = await r.json();
      if (!r.ok || j.code !== 0) {
        toast('[' + (j.code || r.status) + '] ' + (j.error || '请求失败'));
        return null;
      }
      return j.data;
    } catch (e) {
      toast('网络错误：' + e.message);
      return null;
    }
  }

  function badge(id, text, cls) {
    var el = $(id); if (!el) return;
    el.textContent = text; el.className = 'wb-badge ' + (cls || '');
  }
  function kpi(k, v, note) {
    var unavailable = (v === null || v === undefined || v === '');
    return '<div class="wb-kpi"><div class="k">' + esc(k) + '</div>' +
      '<div class="v' + (unavailable ? ' na' : '') + '">' + esc(na(v)) + '</div>' +
      (note ? '<div class="n">' + esc(note) + '</div>' : '') + '</div>';
  }
  function empty(text) { return '<div class="wb-empty">' + esc(text) + '</div>'; }
  function degrade(reason, rule) {
    return '<div class="wb-degrade"><div class="h">数据未就绪（如实降级，不填示例值）</div>' +
      '<div>' + esc(reason || '派生区未绑定该班级') + '</div>' +
      (rule ? '<div class="r">' + esc(rule) + '</div>' : '') + '</div>';
  }
  function resultBox(text, isErr) {
    return '<div class="wb-result' + (isErr ? ' err' : '') + '">' + esc(text) + '</div>';
  }

  /* ---------------------------------------------------------------- 身份 */
  function renderCtx() {
    var c = S.ctx;
    $('ctxWho').textContent = c.name + ' · ' + c.post_name;
    $('ctxMeta').textContent = (c.portal_name || '') + ' · ' + c.level +
      ' · 数据范围 ' + c.data_scope + ' · 智能体 ' + c.agent_name;
    $('ctxBar').innerHTML = [
      ['当前身份', c.name + '（' + c.user_id + '）'],
      ['职务', c.post_name],
      ['层级', c.level + (c.in_chain ? '' : ' · 不进推送链')],
      ['数据范围', c.data_scope],
      ['共建空间', c.space_id]
    ].map(function (x) {
      return '<span class="wb-chip">' + esc(x[0]) + '：<b>' + esc(x[1]) + '</b></span>';
    }).join('');
  }

  /* ---------------------------------------------------------------- 周报 */
  async function loadWeekly() {
    var d = await api('/api/v1/report/weekly?session_id=' + encodeURIComponent(S.sid));
    var body = $('weeklyBody');
    if (!d || !d.card) { body.innerHTML = empty('周报暂不可用'); badge('weeklyBadge', '不可用', 'danger'); return; }
    var c = d.card; S.weekly = c;
    var n = c.numbers || {};
    body.innerHTML = '<div class="wb-kpis" style="margin-bottom:16px">' +
      kpi('出勤率', n.attendance_rate, n.attendance_note) +
      kpi('需关注', n.attention_count, '人（只含标记，不含原因）') +
      kpi('德育', n.moral_delta, n.moral_note) +
      kpi('归寝异常', n.dorm_anomaly, n.dorm_note || '人次') +
      '</div><div class="wb-report">' +
      (c.lines || []).map(function (t, i) {
        var cls = i === 0 ? 'lead' : (String(t).indexOf('·') === 0 ? 'bullet' : '');
        return '<p class="' + cls + '">' + esc(t) + '</p>';
      }).join('') + '</div>';
    var archived = c.status === 'archived';
    badge('weeklyBadge', archived ? '已归档' : '待确认归档', archived ? 'ok' : 'warn');
    var btn = $('btnArchive');
    btn.disabled = archived;
    btn.dataset.rid = c.report_id || '';
  }

  async function archiveWeekly() {
    var rid = $('btnArchive').dataset.rid;
    if (!rid) return;
    if (!confirm('确认将本周周报归档到成长导航档案？归档后人审点即完成。')) return;
    var d = await api('/api/v1/report/archive', { session_id: S.sid, report_id: rid });
    if (!d) return;
    toast(d.reply || '已归档');
    loadWeekly();
  }

  /* ---------------------------------------------------------------- 需关注清单 */
  function categoryOptions() {
    return CATEGORIES.map(function (c) { return '<option value="' + esc(c) + '">' + esc(c) + '</option>'; }).join('');
  }

  async function loadWatch() {
    var d = await api('/api/v1/report/watchlist?session_id=' + encodeURIComponent(S.sid));
    var body = $('watchBody');
    if (!d || !d.card) { body.innerHTML = empty('需关注清单暂不可用'); badge('watchBadge', '不可用', 'danger'); return; }
    var items = (d.card.items || []);
    badge('watchBadge', items.length + ' 人待跟进', items.length ? 'warn' : 'ok');
    if (!items.length) { body.innerHTML = empty('本班当前无需要关注的标记'); return; }
    body.innerHTML = '<table class="wb-table"><thead><tr>' +
      '<th>学生（掩码）</th><th>标记</th><th>建议动作</th><th>状态</th><th>转介</th></tr></thead><tbody>' +
      items.map(function (x) {
        return '<tr><td>' + esc(x.name_masked || x.student_id) + '</td><td>' + esc(x.mark) +
          '</td><td>' + esc(x.action) + '</td><td>' + esc(x.status) + '</td>' +
          '<td><div class="wb-row-actions">' +
          '<select class="wb-select" data-student="' + esc(x.student_id) + '">' + categoryOptions() + '</select>' +
          '<button type="button" class="wb-btn wb-btn-mini" data-act="refer" data-student="' + esc(x.student_id) + '">转介</button>' +
          '</div></td></tr>';
      }).join('') + '</tbody></table>' +
      (d.card.note ? '<p class="wb-note" style="margin-top:10px">' + esc(d.card.note) + '｜' + esc(d.card.source || '') + '</p>' : '');
  }

  /* ---------------------------------------------------------------- 德育记录 */
  async function loadMoral() {
    var pending = await api('/api/v1/write/pending?session_id=' + encodeURIComponent(S.sid));
    var records = await api('/api/v1/write/records?session_id=' + encodeURIComponent(S.sid));
    var body = $('moralBody');
    var html = '';
    var p = pending && pending.pending;
    if (p) {
      badge('moralBadge', '有 1 条待确认草稿', 'warn');
      html += '<div class="wb-degrade"><div class="h">待确认写入草稿（人审后生效）</div>' +
        '<div>类型：' + esc(p.kind) + '　时间：' + esc(p.ts) + '</div>' +
        '<pre style="white-space:pre-wrap;font-size:12px;margin:8px 0 0">' + esc(p.payload_json || '') + '</pre>' +
        '<div class="wb-row-actions" style="margin-top:10px">' +
        '<button type="button" class="wb-btn wb-btn-primary wb-btn-mini" data-act="write-confirm">确认写入</button>' +
        '<button type="button" class="wb-btn wb-btn-mini" data-act="write-cancel">作废草稿</button>' +
        '</div></div>';
    } else {
      badge('moralBadge', '无待确认草稿', 'ok');
      html += empty('当前没有待确认的写入草稿。德育记录先形成草稿，班主任确认后才写入正式记录。');
    }
    var recs = (records && records.records) || [];
    html += '<h3 style="font-size:14px;color:var(--red);margin:18px 0 8px">已写入记录</h3>';
    if (!recs.length) {
      html += empty('暂无正式写入记录');
    } else {
      html += '<table class="wb-table"><thead><tr><th>时间</th><th>类型</th><th>内容</th></tr></thead><tbody>' +
        recs.map(function (r) {
          return '<tr><td>' + esc(r.ts) + '</td><td>' + esc(r.kind) + '</td><td style="max-width:520px">' +
            esc(r.payload_json) + '</td></tr>';
        }).join('') + '</tbody></table>';
    }
    body.innerHTML = html;
  }

  /* ---------------------------------------------------------------- 成长类 */
  function growthKpis(d) {
    return '<div class="wb-kpis">' +
      kpi('出勤率', d.attendance_rate, d.attendance_note) +
      kpi('需关注', d.attention_count, '人') +
      kpi('德育变化', d.moral_delta, d.moral_note) +
      kpi('归寝异常', d.dorm_anomaly, d.dorm_note || '人次') +
      kpi('请假', d.leave_count, d.leave_note || d.leave_reconcile) +
      '</div>';
  }

  async function loadScores() {
    var d = await api('/api/v1/growth/numbers?session_id=' + encodeURIComponent(S.sid));
    var body = $('scoresBody');
    if (!d || !d.data) { body.innerHTML = empty('学情数据暂不可用'); badge('scoresBadge', '不可用', 'danger'); return; }
    badge('scoresBadge', d.data.degraded ? '部分降级' : '已就绪', d.data.degraded ? 'warn' : 'ok');
    body.innerHTML = growthKpis(d.data) +
      '<p class="wb-note" style="margin-top:12px">' + esc(d.data.source || '') + '｜' + esc(d.zone || '') + '</p>';
  }

  function renderDerived(d, badgeId, bodyId, title) {
    var body = $(bodyId);
    if (!d || !d.data) { body.innerHTML = empty(title + '数据暂不可用'); badge(badgeId, '不可用', 'danger'); return; }
    var x = d.data;
    if (x.available === false) {
      badge(badgeId, '未就绪（已降级）', 'warn');
      body.innerHTML = degrade(x.reason, x.rule);
      return;
    }
    badge(badgeId, '已就绪', 'ok');
    body.innerHTML = '<pre style="white-space:pre-wrap;font-size:12.5px;margin:0">' + esc(JSON.stringify(x, null, 2)) + '</pre>';
  }

  async function loadTalent() {
    var d = await api('/api/v1/growth/profile?session_id=' + encodeURIComponent(S.sid));
    renderDerived(d, 'talentBadge', 'talentBody', '特长与兴趣');
  }
  async function loadFriends() {
    var d = await api('/api/v1/growth/derived?session_id=' + encodeURIComponent(S.sid));
    renderDerived(d, 'friendsBadge', 'friendsBody', '交友与同伴');
  }
  async function loadGoals() {
    var d = await api('/api/v1/growth/goals?session_id=' + encodeURIComponent(S.sid));
    renderDerived(d, 'goalsBadge', 'goalsBody', '成长目标');
  }

  /* ---------------------------------------------------------------- 家校沟通 */
  async function loadFamily() {
    var d = await api('/api/v1/todo/list?session_id=' + encodeURIComponent(S.sid));
    var items = ((d && d.items) || []).filter(function (x) { return x.kind === 'note'; });
    badge('familyBadge', items.length + ' 条沟通留痕', 'ok');
    var html = '<div class="wb-degrade" style="margin-bottom:14px">' +
      '<div class="h">登记人工沟通留痕</div><div>只记事由分类与时间，不保存家长联系方式，不自动向家长推送。</div>' +
      '<div class="wb-row-actions" style="margin-top:10px">' +
      '<select class="wb-select" id="familyCat">' + categoryOptions() + '</select>' +
      '<button type="button" class="wb-btn wb-btn-primary wb-btn-mini" data-act="note">登记</button></div>' +
      '<div id="familyResult"></div></div>';
    if (!items.length) {
      html += empty('本周暂无家校沟通登记');
    } else {
      html += '<table class="wb-table"><thead><tr><th>时间</th><th>事由分类</th><th>事实</th><th>状态</th></tr></thead><tbody>' +
        items.map(function (x) {
          return '<tr><td>' + esc(x.ts) + '</td><td>' + esc(x.category) + '</td><td>' + esc(x.fact) +
            '</td><td>' + esc(x.status) + '</td></tr>';
        }).join('') + '</tbody></table>';
    }
    $('familyBody').innerHTML = html;
  }

  /* ---------------------------------------------------------------- 控辍触发器 */
  async function loadDropout() {
    var st = await api('/api/v1/warning/state?session_id=' + encodeURIComponent(S.sid));
    var ref = await api('/api/v1/todo/referrals?session_id=' + encodeURIComponent(S.sid));
    var body = $('dropoutBody');
    if (!st) { body.innerHTML = empty('预警状态暂不可用'); badge('dropoutBadge', '不可用', 'danger'); return; }
    var approved = st.rules_approved, total = st.rules_total;
    badge('dropoutBadge', '规则 ' + approved + '/' + total + ' 已批准 · 影子期未启动', 'warn');
    var html = '<div class="wb-kpis" style="margin-bottom:14px">' +
      kpi('规则批准', approved + ' / ' + total, '未批准前不推送、不进考核') +
      kpi('影子模式', '未启动', st.shadow_mode) +
      kpi('月误报', '未开始', st.monthly_false_positive) +
      '</div>' +
      '<table class="wb-table"><tbody>' +
      [['转介通道', st.referral_slips], ['七类异动', st.enroll_change_7], ['保学快照', st.retention_snapshot]]
        .map(function (x) { return '<tr><th style="width:120px">' + esc(x[0]) + '</th><td>' + esc(x[1]) + '</td></tr>'; }).join('') +
      '</tbody></table>' +
      '<p class="wb-note" style="margin-top:10px">' + esc(st.note || '') + '</p>';
    var slips = (ref && ref.slips) || [];
    html += '<h3 style="font-size:14px;color:var(--red);margin:18px 0 8px">转介单（L1 → L2 劝返台账）</h3>';
    html += slips.length
      ? '<table class="wb-table"><thead><tr><th>时间</th><th>分类</th><th>事实</th><th>状态</th></tr></thead><tbody>' +
        slips.map(function (s) {
          return '<tr><td>' + esc(s.ts) + '</td><td>' + esc(s.category) + '</td><td>' + esc(s.fact) +
            '</td><td>' + esc(s.status) + '</td></tr>';
        }).join('') + '</tbody></table>'
      : empty('暂无转介单；转介只写事实，不作定性');
    body.innerHTML = html;
  }

  /* ---------------------------------------------------------------- 待确认红点 */
  async function loadTodo() {
    var d = await api('/api/v1/todo/list?session_id=' + encodeURIComponent(S.sid));
    var body = $('todoBody');
    if (!d) { body.innerHTML = empty('待确认列表暂不可用'); badge('todoBadge', '不可用', 'danger'); return; }
    var items = d.items || [];
    badge('todoBadge', (d.open_count || 0) + ' 项待办 · ' + (d.week || ''), items.length ? 'warn' : 'ok');
    if (!items.length) { body.innerHTML = empty(d.empty_text || '本周无待确认'); return; }
    body.innerHTML = '<table class="wb-table"><thead><tr><th>时间</th><th>类型</th><th>分类</th><th>事实</th><th>状态</th><th>操作</th></tr></thead><tbody>' +
      items.map(function (x) {
        return '<tr><td>' + esc(x.ts) + '</td><td>' + esc((d.kinds && d.kinds[x.kind]) || x.kind) +
          '</td><td>' + esc(x.category) + '</td><td>' + esc(x.fact) + '</td><td>' + esc(x.status) +
          '</td><td><button type="button" class="wb-btn wb-btn-mini" data-act="close" data-id="' + esc(x.id) + '">销号</button></td></tr>';
      }).join('') + '</tbody></table>' +
      '<p class="wb-note" style="margin-top:10px">' + esc(d.rule || '') + '</p>';
  }

  /* ---------------------------------------------------------------- 六级推送流 */
  async function loadFlow() {
    var d = await api('/api/v1/push/flow');
    var body = $('flowBody');
    if (!d) { body.innerHTML = empty('推送流暂不可用'); badge('flowBadge', '不可用', 'danger'); return; }
    badge('flowBadge', '六级链路', 'ok');
    var html = '<table class="wb-table"><thead><tr><th>层级</th><th>名称</th><th>时间</th></tr></thead><tbody>' +
      (d.schedule || []).map(function (s) {
        var lv = (d.levels || []).filter(function (x) { return x.id === s.level; })[0] || {};
        return '<tr><td><b>' + esc(s.level) + '</b></td><td>' + esc(lv.name || '') + '</td><td>' + esc(s.cron) + '</td></tr>';
      }).join('') + '</tbody></table>';
    var recent = d.recent || [];
    html += '<h3 style="font-size:14px;color:var(--red);margin:18px 0 8px">最近推送</h3>';
    html += recent.length
      ? '<table class="wb-table"><thead><tr><th>时间</th><th>层级</th><th>周期</th><th>渠道</th><th>状态</th></tr></thead><tbody>' +
        recent.map(function (r) {
          return '<tr><td>' + esc(r.ts) + '</td><td>' + esc(r.level) + '</td><td>' + esc(r.period) +
            '</td><td>' + esc(r.channel) + '</td><td>' + esc(r.status) + '</td></tr>';
        }).join('') + '</tbody></table>'
      : empty('暂无推送记录（试运行阶段尚未触发）');
    html += '<p class="wb-note" style="margin-top:10px">' + esc(d.rule || '') + '</p>';
    body.innerHTML = html;
  }

  /* ---------------------------------------------------------------- 运行与验收 */
  async function loadOps() {
    var d = await api('/api/v1/health/readiness');
    var body = $('opsBody');
    if (!d) { body.innerHTML = empty('验收状态暂不可用'); badge('opsBadge', '不可用', 'danger'); return; }
    badge('opsBadge', (d.state || '') + ' · ' + d.done + '/' + d.total, d.done >= d.total ? 'ok' : 'warn');
    body.innerHTML = '<div class="wb-kpis" style="margin-bottom:14px">' +
      kpi('运行状态', d.state, '上线前置完成度') +
      kpi('已就绪', d.done + ' / ' + d.total, '九项一票否决清单') +
      '</div><ul class="wb-ready">' +
      (d.items || []).map(function (i) {
        return '<li class="' + (i.done ? 'done' : '') + '"><span class="dot"></span><span>' + esc(i.name) + '</span></li>';
      }).join('') + '</ul>';
  }

  /* ---------------------------------------------------------------- 动作 */
  async function doAction(act, el) {
    if (act === 'refer') {
      var sel = el.parentNode.querySelector('select[data-student]');
      var cat = sel ? sel.value : CATEGORIES[0];
      if (!confirm('按“' + cat + '”转介该学生？只写事实、不作定性。')) return;
      var r = await api('/api/v1/todo/refer', { session_id: S.sid, student_id: el.dataset.student, category: cat });
      if (r) { toast('转介已登记（L1 → L2）'); loadWatch(); }
    } else if (act === 'close') {
      if (!confirm('确认销号？销号后不再出现在待确认列表。')) return;
      var c = await api('/api/v1/todo/close', { session_id: S.sid, item_id: el.dataset.id });
      if (c) { toast('已销号并留痕'); loadTodo(); }
    } else if (act === 'note') {
      var catEl = $('familyCat');
      var cat2 = catEl ? catEl.value : CATEGORIES[0];
      var n = await api('/api/v1/todo/note', { session_id: S.sid, category: cat2 });
      if (n) {
        toast('沟通留痕已登记');
        var box = $('familyResult'); if (box) box.innerHTML = resultBox('已登记：' + cat2 + '（仅留痕，不自动推送）');
        loadFamily();
      }
    } else if (act === 'write-confirm' || act === 'write-cancel') {
      var decision = act === 'write-confirm' ? 'confirm' : 'cancel';
      if (!confirm(decision === 'confirm' ? '确认写入正式记录？' : '确认作废该草稿？')) return;
      var w = await api('/api/v1/write/confirm', { session_id: S.sid, decision: decision });
      if (w) { toast(w.reply || '已处理'); loadMoral(); }
    }
  }

  /* ---------------------------------------------------------------- 路由 */
  var LOADERS = {
    weekly: loadWeekly, watchlist: loadWatch, moral: loadMoral, scores: loadScores,
    talent: loadTalent, friends: loadFriends, goals: loadGoals, family: loadFamily,
    dropout: loadDropout, todo: loadTodo, flow: loadFlow, ops: loadOps
  };

  function showTab(name) {
    var btns = document.querySelectorAll('#wbNav button');
    for (var i = 0; i < btns.length; i++) btns[i].className = btns[i].dataset.tab === name ? 'on' : '';
    var panels = document.querySelectorAll('.wb-panel');
    for (var j = 0; j < panels.length; j++) panels[j].className = 'wb-panel' + (panels[j].id === 'panel-' + name ? ' on' : '');
    if (LOADERS[name]) LOADERS[name]();
  }

  document.getElementById('wbNav').addEventListener('click', function (e) {
    var b = e.target.closest('button[data-tab]');
    if (b) showTab(b.dataset.tab);
  });
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-act]');
    if (b) doAction(b.dataset.act, b);
  });
  $('btnArchive').addEventListener('click', archiveWeekly);
  $('btnLogout').addEventListener('click', function () { location.href = '/api/v1/logout'; });

  async function boot() {
    var auto = await api('/api/v1/portal/auto', {});
    if (!auto || !auto.ctx) {
      $('ctxWho').textContent = '身份识别失败';
      $('ctxMeta').textContent = '请退出后重新登录，或联系管理员核对企业微信通讯录职务';
      return;
    }
    S.ctx = auto.ctx; S.sid = auto.ctx.session_id;
    renderCtx();
    showTab('weekly');
  }

  boot();
})();
