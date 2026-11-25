/* 政教处工作台 · 前端逻辑（无依赖，原生 JS） */
(function () {
  "use strict";

  var API = "/api/v1";
  var LOGIN = "/api/v1/login?next=/api/deyu";

  var state = {
    view: "home",
    me: null,
    criteria: [],
    directions: [],
    classes: [],
    students: [],
    loaded: {},
    stats: null,
    statsClasses: [],
    statsCharts: {},
    statsReady: false,
    roster: {
      tab: "students",
      classes: [],
      classId: "",
      students: [],
      checked: {},
      picked: {},
      pendingFile: null,
      importErrors: [],
      numbering: null,
      dorms: [],
      dormId: null,
      dormLoaded: false
    }
  };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }
  function esc(s) {
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }
  function todayStr() {
    var d = new Date();
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function fmtDay(s) {
    if (!s) return "—";
    return String(s).replace("T", " ").slice(0, 10);
  }

  /* ---------------- 通信 ---------------- */
  function api(path, opts) {
    opts = opts || {};
    opts.credentials = "include";
    return fetch(API + path, opts).then(function (r) {
      if (r.status === 401) {
        location.href = LOGIN;
        return Promise.reject(new Error("未登录或登录已过期"));
      }
      var ct = r.headers.get("content-type") || "";
      if (ct.indexOf("application/json") >= 0) {
        return r.json().then(function (j) {
          if (j && typeof j.code !== "undefined" && j.code !== 0) {
            throw new Error(j.message || j.error || "操作失败");
          }
          return j;
        });
      }
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r;
    });
  }
  function apiJson(path, method, body) {
    return api(path, {
      method: method || "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined
    });
  }

  /* ---------------- Toast ---------------- */
  var toastTimer = null;
  function toast(msg, kind) {
    var t = $("toast");
    if (!t) return;
    t.textContent = msg == null ? "" : String(msg);
    t.className = "toast" + (kind ? " " + kind : "");
    t.style.display = "block";
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.style.display = "none"; }, 2600);
  }
  function errToast(e) {
    if (e && e.message && e.message !== "未登录或登录已过期") toast(e.message, "err");
  }

  /* ---------------- 确认弹窗 ---------------- */
  function openConfirm(o) {
    o = o || {};
    $("confirmTitle").textContent = o.title || "确认操作";
    $("confirmText").textContent = o.text || "";
    $("confirmOk").textContent = o.okText || "确定";
    var m = $("confirmModal");
    m.hidden = false;
    return new Promise(function (resolve) {
      function cleanup(v) {
        m.hidden = true;
        $("confirmOk").onclick = null;
        $("confirmCancel").onclick = null;
        $("confirmClose").onclick = null;
        resolve(v);
      }
      $("confirmOk").onclick = function () { cleanup(true); };
      $("confirmCancel").onclick = function () { cleanup(false); };
      $("confirmClose").onclick = function () { cleanup(false); };
    });
  }

  /* ---------------- 通用表单弹窗 ---------------- */
  function openForm(o) {
    o = o || {};
    var box = $("formModalBox");
    box.className = "modal-box" + (o.wide ? " wide" : "");
    $("formTitle").textContent = o.title || "编辑";
    $("formSubmit").textContent = o.submitText || "保存";
    var body = $("formBody");
    body.innerHTML = "";
    var grid = el("div", "form-grid");
    body.appendChild(grid);
    (o.fields || []).forEach(function (f) {
      var wrap = el("div", "form-field" + (f.full ? " full" : ""));
      var label = el("label");
      label.innerHTML = esc(f.label) + (f.required ? '<span class="req">*</span>' : "");
      wrap.appendChild(label);
      var input;
      if (f.type === "select") {
        input = document.createElement("select");
        input.name = f.name;
        var opts = f.options || [];
        if (!f.required) opts = [{ v: "", t: "请选择" }].concat(opts);
        opts.forEach(function (op) {
          var opt = document.createElement("option");
          opt.value = op.v; opt.textContent = op.t;
          if (String(f.value) === String(op.v)) opt.selected = true;
          input.appendChild(opt);
        });
      } else if (f.type === "textarea") {
        input = document.createElement("textarea");
        input.name = f.name; input.rows = f.rows || 2;
        input.value = f.value == null ? "" : f.value;
      } else {
        input = document.createElement("input");
        input.type = f.type || "text";
        input.name = f.name;
        input.value = f.value == null ? "" : f.value;
        if (f.readonly) input.readOnly = true;
        if (f.placeholder) input.placeholder = f.placeholder;
        if (f.min != null) input.min = f.min;
        if (f.max != null) input.max = f.max;
        if (f.step != null) input.step = f.step;
      }
      wrap.appendChild(input);
      grid.appendChild(wrap);
    });
    if (o.tip) { body.appendChild(el("p", "form-tip", esc(o.tip))); }

    var m = $("formModal");
    m.hidden = false;
    function close() { m.hidden = true; }
    $("formClose").onclick = close;
    $("formCancel").onclick = close;
    $("formSubmit").onclick = function () {
      var values = {};
      var ok = true;
      [].forEach.call(grid.querySelectorAll("[name]"), function (inp) {
        values[inp.name] = inp.value;
      });
      (o.fields || []).forEach(function (f) {
        if (f.required && !String(values[f.name] || "").trim()) {
          toast((f.label || f.name) + "不能为空", "err"); ok = false;
        }
      });
      if (!ok) return;
      var btn = $("formSubmit");
      btn.disabled = true;
      Promise.resolve()
        .then(function () { return o.onSubmit(values); })
        .then(function () { btn.disabled = false; close(); })
        .catch(function (e) { btn.disabled = false; toast(e.message || "操作失败", "err"); });
    };
  }

  /* ---------------- 视图切换 ---------------- */
  var VIEW_META = {
    home: { title: "政教处概览", sub: "全校德育治理总览" },
    criteria: { title: "德育指标", sub: "维护掌声鼓励 / 有待改善指标与分值" },
    records: { title: "德育登记", sub: "全校德育事件登记与确认跟踪" },
    stats: { title: "全校统计", sub: "按周 / 月 / 学期汇总班级与学生德育得分" },
    roster: { title: "名单与寝室", sub: "学生名单、学号编排与寝室统一分配" }
  };

  function switchView(v) {
    if (!VIEW_META[v]) v = "home";
    state.view = v;
    [].forEach.call(document.querySelectorAll(".nav button"), function (b) {
      b.classList.toggle("on", b.getAttribute("data-view") === v);
    });
    [].forEach.call(document.querySelectorAll(".view"), function (s) {
      s.classList.toggle("on", s.id === "view-" + v);
    });
    var meta = VIEW_META[v];
    $("pageTitle").textContent = meta.title;
    $("pageSub").textContent = meta.sub;
    if (v === "home") loadHome();
    if (v === "criteria") loadCriteria();
    if (v === "records") loadRecordsView();
    if (v === "stats") {
      if (!state.statsReady) {
        loadStatsClasses().then(loadStats).catch(errToast);
      } else {
        loadStats();
      }
    }
    if (v === "roster") loadRoster();
  }

  /* ---------------- 概览 ---------------- */
  function loadHome() {
    var day = todayStr();
    Promise.all([
      api("/deyu/moral/records?status=pending&limit=500"),
      api("/deyu/moral/records?start=" + day + "&end=" + day + "&limit=500")
    ]).then(function (res) {
      var pending = (res[0] && res[0].data && res[0].data.items) || [];
      var today = (res[1] && res[1].data && res[1].data.items) || [];
      $("kpiPending").textContent = pending.length;
      $("kpiToday").textContent = today.length;
    }).catch(errToast);
    api("/deyu/stats?period=week").then(function (j) {
      var data = (j && j.data) || {};
      var focus = data.focus || [];
      $("kpiFocus").textContent = focus.length;
      renderHomeFocus(focus);
    }).catch(errToast);
  }

  /* ---------------- 德育指标 ---------------- */
  function loadCriteria() {
    return api("/deyu/criteria").then(function (j) {
      var data = (j && j.data) || {};
      state.criteria = data.items || [];
      state.directions = data.directions || [
        { key: "praise", label: "掌声鼓励" }, { key: "improve", label: "有待改善" }
      ];
      renderCriteria();
      return state.criteria;
    }).catch(function (e) { errToast(e); });
  }

  function criteriaRow(c) {
    var on = Number(c.enabled) === 1;
    var pts = Number(c.points) || 0;
    var tr = el("tr");
    tr.innerHTML =
      '<td>' + esc(c.name) + '</td>' +
      '<td class="mono">' + (pts > 0 ? "+" : "") + pts + '</td>' +
      '<td><span class="status-dot ' + (on ? "on" : "off") + '"></span>' + (on ? "启用" : "停用") + '</td>' +
      '<td><div class="row-actions">' +
      '<button type="button" class="btn sm" data-act="edit" data-id="' + esc(c.id) + '">编辑</button>' +
      '<button type="button" class="btn sm" data-act="toggle" data-id="' + esc(c.id) + '">' +
      (on ? "停用" : "启用") + '</button>' +
      '<button type="button" class="btn sm danger" data-act="remove" data-id="' + esc(c.id) + '">删除</button>' +
      '</div></td>';
    return tr;
  }

  function renderCriteria() {
    var praise = state.criteria.filter(function (c) { return c.direction === "praise"; });
    var improve = state.criteria.filter(function (c) { return c.direction === "improve"; });
    var tp = $("criteriaPraise"), ti = $("criteriaImprove");
    tp.innerHTML = ""; ti.innerHTML = "";
    praise.forEach(function (c) { tp.appendChild(criteriaRow(c)); });
    improve.forEach(function (c) { ti.appendChild(criteriaRow(c)); });
    $("praiseCount").textContent = praise.length + " 项";
    $("improveCount").textContent = improve.length + " 项";
    $("criteriaPraiseEmpty").hidden = praise.length > 0;
    $("criteriaImproveEmpty").hidden = improve.length > 0;
  }

  function findCriteria(id) {
    for (var i = 0; i < state.criteria.length; i++) {
      if (String(state.criteria[i].id) === String(id)) return state.criteria[i];
    }
    return null;
  }

  function openCriteriaForm(item) {
    var isEdit = !!item;
    openForm({
      title: isEdit ? "编辑指标" : "新增指标",
      submitText: isEdit ? "保存" : "新增",
      tip: "分值范围 -20 ~ 20；修改分值只影响后续登记，已登记事件保持快照分值。",
      fields: [
        { name: "name", label: "指标名称", required: true, value: item && item.name || "" },
        { name: "direction", label: "方向", type: "select", required: true,
          value: item && item.direction || "praise",
          options: state.directions.map(function (d) { return { v: d.key, t: d.label }; }) },
        { name: "points", label: "分值", type: "number", required: true,
          value: item ? item.points : "", min: -20, max: 20, step: 1 },
        { name: "category", label: "类别", value: item && item.category || "" },
        { name: "term", label: "生效学期", value: item && item.term || "",
          placeholder: "如 2026-2027-1，可留空" }
      ],
      onSubmit: function (v) {
        var pts = Number(v.points);
        if (!isFinite(pts) || Math.floor(pts) !== pts || pts < -20 || pts > 20) {
          return Promise.reject(new Error("分值需为 -20 到 20 之间的整数"));
        }
        var body = {
          name: v.name, direction: v.direction, points: pts,
          category: v.category, term: v.term
        };
        var req;
        if (isEdit) {
          body.id = item.id;
          req = apiJson("/deyu/criteria/update", "POST", body);
        } else {
          req = apiJson("/deyu/criteria", "POST", body);
        }
        return req.then(function () {
          toast(isEdit ? "指标已更新" : "指标已新增", "ok");
          return loadCriteria();
        });
      }
    });
  }

  function onCriteriaAction(e) {
    var btn = e.target.closest("[data-act]");
    if (!btn) return;
    var item = findCriteria(btn.getAttribute("data-id"));
    if (!item) return;
    var act = btn.getAttribute("data-act");
    if (act === "edit") { openCriteriaForm(item); return; }
    if (act === "toggle") {
      var enable = Number(item.enabled) !== 1;
      apiJson("/deyu/criteria/toggle", "POST", { id: item.id, enabled: enable })
        .then(function () {
          toast(enable ? "指标已启用" : "指标已停用", "ok");
          return loadCriteria();
        }).catch(errToast);
      return;
    }
    if (act === "remove") {
      openConfirm({
        title: "删除指标",
        text: "确认删除「" + item.name + "」？若已有事件引用，将改为停用并保留历史。",
        okText: "删除"
      }).then(function (yes) {
        if (!yes) return;
        apiJson("/deyu/criteria/remove", "POST", { id: item.id })
          .then(function (j) {
            var action = (j && j.data && j.data.action) || "deleted";
            toast(action === "disabled" ? "已有历史引用，已改为停用" : "指标已删除",
                  action === "disabled" ? "ok" : "ok");
            return loadCriteria();
          }).catch(errToast);
      });
    }
  }

  /* ---------------- 德育登记 ---------------- */
  function loadRecordsView() {
    return Promise.all([loadClasses(), loadCriteria()]).then(function () {
      refreshRecords();
    }).catch(errToast);
  }

  function loadClasses() {
    return api("/deyu/classes").then(function (j) {
      state.classes = ((j && j.data && j.data.items) || []);
      var sel = $("regClass");
      var prev = sel.value;
      sel.innerHTML = '<option value="">请选择班级</option>';
      state.classes.forEach(function (c) {
        var opt = document.createElement("option");
        opt.value = c.class_id;
        opt.textContent = (c.name || c.class_id) + "（" + (c.student_count || 0) + "人）";
        sel.appendChild(opt);
      });
      if (prev) {
        sel.value = prev;
        if (!sel.value) sel.value = "";
      }
      if (sel.value) loadStudents(sel.value).catch(errToast);
      return state.classes;
    });
  }

  function loadStudents(cid) {
    if (!cid) {
      state.students = [];
      renderStudents();
      return Promise.resolve([]);
    }
    return api("/deyu/students?class_id=" + encodeURIComponent(cid)).then(function (j) {
      state.students = ((j && j.data && j.data.items) || []);
      renderStudents();
      return state.students;
    });
  }

  function renderStudents() {
    var sel = $("regStudent");
    sel.innerHTML = '<option value="">请选择学生</option>';
    state.students.forEach(function (s) {
      var opt = document.createElement("option");
      opt.value = s.student_id;
      opt.textContent = (s.student_no || s.student_id) + " " + s.name + (s.dorm ? "（" + s.dorm + "）" : "");
      sel.appendChild(opt);
    });
  }

  function renderCriteriaSelect() {
    var sel = $("regCriteria");
    sel.innerHTML = '<option value="">请选择指标</option>';
    state.directions.forEach(function (d) {
      var group = document.createElement("optgroup");
      group.label = d.label + (d.key === "praise" ? "（加分）" : "（扣分）");
      var any = false;
      state.criteria.forEach(function (c) {
        if (c.direction !== d.key || Number(c.enabled) !== 1) return;
        any = true;
        var opt = document.createElement("option");
        opt.value = c.id;
        var pts = Number(c.points) || 0;
        opt.textContent = c.name + "（" + (pts > 0 ? "+" : "") + pts + "）";
        group.appendChild(opt);
      });
      if (any) sel.appendChild(group);
    });
  }

  function refreshRecords() {
    renderCriteriaSelect();
    Promise.all([
      api("/deyu/moral/records?status=pending&limit=100"),
      api("/deyu/moral/records?limit=100")
    ]).then(function (res) {
      var pending = ((res[0] && res[0].data && res[0].data.items) || []);
      var recent = ((res[1] && res[1].data && res[1].data.items) || []);
      renderPending(pending);
      renderRecent(recent);
      $("pendingCount").textContent = pending.length + " 条";
    }).catch(errToast);
  }

  function eventClassLabel(ev) {
    var cid = ev.class_id || "";
    for (var i = 0; i < state.classes.length; i++) {
      if (String(state.classes[i].class_id) === String(cid)) {
        return (state.classes[i].name || cid);
      }
    }
    return cid;
  }

  function renderPending(items) {
    var body = $("pendingBody");
    body.innerHTML = "";
    items.forEach(function (ev) {
      var tr = el("tr");
      var pts = Number(ev.points) || 0;
      tr.innerHTML =
        '<td>' + esc(fmtDay(ev.event_date)) + '</td>' +
        '<td>' + esc(eventClassLabel(ev)) + ' / ' + esc(ev.student_id) + ' ' + esc(ev.student_name) + '</td>' +
        '<td>' + esc(ev.criteria_name || ev.category) + '</td>' +
        '<td class="mono">' + (pts > 0 ? "+" : "") + pts + '</td>' +
        '<td>' + esc(ev.fact || "") + '</td>' +
        '<td>' + esc(ev.recorded_by || "—") + '</td>' +
        '<td><div class="row-actions">' +
        '<button type="button" class="btn sm primary" data-review="confirm" data-id="' + esc(ev.id) + '">确认</button>' +
        '<button type="button" class="btn sm danger" data-review="void" data-id="' + esc(ev.id) + '">作废</button>' +
        '</div></td>';
      body.appendChild(tr);
    });
    $("pendingEmpty").hidden = items.length > 0;
  }

  function statusBadge(status) {
    if (status === "confirmed") return '<span class="badge ok">已确认</span>';
    if (status === "void") return '<span class="badge danger">已作废</span>';
    return '<span class="badge warn">待确认</span>';
  }

  function renderRecent(items) {
    var body = $("recentBody");
    body.innerHTML = "";
    items.forEach(function (ev) {
      var tr = el("tr");
      var pts = Number(ev.points) || 0;
      tr.innerHTML =
        '<td>' + esc(fmtDay(ev.event_date)) + '</td>' +
        '<td>' + esc(eventClassLabel(ev)) + ' / ' + esc(ev.student_id) + ' ' + esc(ev.student_name) + '</td>' +
        '<td>' + esc(ev.criteria_name || ev.category) + '</td>' +
        '<td class="mono">' + (pts > 0 ? "+" : "") + pts + '</td>' +
        '<td>' + statusBadge(ev.status) + '</td>' +
        '<td>' + esc(ev.fact || "") + '</td>' +
        '<td>' + esc(ev.recorded_by || "—") + '</td>';
      body.appendChild(tr);
    });
    $("recentEmpty").hidden = items.length > 0;
  }

  function submitRegister() {
    var cid = $("regClass").value;
    var sid = $("regStudent").value;
    var criteriaId = $("regCriteria").value;
    var fact = $("regFact").value.trim();
    var day = $("regDate").value;
    if (!cid) { toast("请先选择班级", "err"); return; }
    if (!sid) { toast("请选择学生", "err"); return; }
    if (!criteriaId) { toast("请选择德育指标", "err"); return; }
    if (!fact) { toast("请填写事实描述", "err"); return; }
    var btn = $("regSubmit");
    btn.disabled = true;
    apiJson("/deyu/moral/register", "POST", {
      class_id: cid, student_id: sid, criteria_id: criteriaId,
      fact: fact, event_date: day || todayStr()
    }).then(function () {
      toast("已登记，待班主任确认后计分", "ok");
      $("regFact").value = "";
      refreshRecords();
      loadHome();
    }).catch(errToast).then(function () {
      btn.disabled = false;
    });
  }

  function onReviewAction(e) {
    var btn = e.target.closest("[data-review]");
    if (!btn) return;
    var id = btn.getAttribute("data-id");
    var action = btn.getAttribute("data-review");
    var isConfirm = action === "confirm";
    openConfirm({
      title: isConfirm ? "确认事件" : "作废事件",
      text: isConfirm ? "确认后该事件将计入德育量化。" : "作废后该事件不计分；已确认的分数同步回退。",
      okText: isConfirm ? "确认" : "作废"
    }).then(function (yes) {
      if (!yes) return;
      apiJson("/deyu/moral/review", "POST", { event_id: id, action: action })
        .then(function () {
          toast(isConfirm ? "已确认并计入德育量化" : "已作废", "ok");
          refreshRecords();
          loadHome();
        }).catch(errToast);
    });
  }

  /* ---------------- 全校统计 ---------------- */
  var BAND_CLASS = { "领先": "lead", "良好": "good", "关注": "watch", "重点": "focus" };

  function signed(n) {
    n = Number(n) || 0;
    return (n > 0 ? "+" : "") + n;
  }

  function bandBadge(band) {
    return '<span class="band ' + (BAND_CLASS[band] || "good") + '">' + esc(band || "—") + '</span>';
  }

  function focusRow(f) {
    var obj = f.name || f.id;
    if (f.type === "student" && f.class_name) obj += "（" + f.class_name + "）";
    var tr = el("tr");
    tr.innerHTML =
      '<td>' + (f.type === "class" ? "班级" : "学生") + '</td>' +
      '<td>' + esc(obj) + '</td>' +
      '<td class="focus-reason">' + esc((f.reasons || []).join("；")) + '</td>' +
      '<td class="mono">' + signed(f.score) + '</td>';
    return tr;
  }

  function renderHomeFocus(items) {
    var body = $("homeFocusBody");
    body.innerHTML = "";
    items.slice(0, 5).forEach(function (f) { body.appendChild(focusRow(f)); });
    $("homeFocusEmpty").hidden = items.length > 0;
    $("homeFocusCount").textContent = items.length + " 项";
  }

  function fillSelect(sel, items, placeholder) {
    var prev = sel.value;
    sel.innerHTML = '<option value="">' + esc(placeholder) + '</option>';
    (items || []).forEach(function (it) {
      var opt = document.createElement("option");
      opt.value = it.v;
      opt.textContent = it.t;
      sel.appendChild(opt);
    });
    sel.value = prev;
  }

  function fillStatsClassOptions() {
    var grade = $("statGrade").value;
    var opts = state.statsClasses.filter(function (c) {
      return !grade || c.grade === grade;
    }).map(function (c) {
      return { v: c.class_id, t: (c.name || c.class_id) + "（" + (c.student_count || 0) + "人）" };
    });
    fillSelect($("statClass"), opts, "全部班级");
  }

  function fillStatCriteriaOptions() {
    if (!state.criteria.length) {
      return loadCriteria().then(fillStatCriteriaOptions);
    }
    var sel = $("statCriteria");
    var prev = sel.value;
    sel.innerHTML = "";
    var all = document.createElement("option");
    all.value = "";
    all.textContent = "全部指标";
    sel.appendChild(all);
    state.criteria.forEach(function (c) {
      var opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = c.name + "（" + signed(c.points) + "）";
      sel.appendChild(opt);
    });
    sel.value = prev;
  }

  function loadStatsClasses() {
    return api("/deyu/classes").then(function (j) {
      state.statsClasses = ((j && j.data && j.data.items) || []);
      var seen = {}, grades = [];
      state.statsClasses.forEach(function (c) {
        var g = c.grade || "";
        if (g && !seen[g]) { seen[g] = 1; grades.push(g); }
      });
      grades.sort();
      fillSelect($("statGrade"), grades.map(function (g) {
        return { v: g, t: g + "级" };
      }), "全部年级");
      fillStatsClassOptions();
      fillStatCriteriaOptions();
      state.statsReady = true;
    });
  }

  function statsQuery() {
    var q = "period=" + encodeURIComponent($("statPeriod").value || "week");
    var grade = $("statGrade").value;
    var cid = $("statClass").value;
    if (grade) q += "&grade=" + encodeURIComponent(grade);
    if (cid) q += "&class_id=" + encodeURIComponent(cid);
    var crit = $("statCriteria").value;
    if (crit) q += "&criteria_id=" + encodeURIComponent(crit);
    return q;
  }

  function loadStats() {
    return api("/deyu/stats?" + statsQuery()).then(function (j) {
      state.stats = (j && j.data) || null;
      renderStats();
    }).catch(errToast);
  }

  function renderStatsChart(name, elementId, data, opts) {
    var current = state.statsCharts[name];
    if (current) {
      current.update(data, opts);
      return;
    }
    state.statsCharts[name] = window.DeyuCharts[name]($(elementId), data, opts);
  }

  function renderStats() {
    var d = state.stats;
    if (!d) return;
    if (!window.DeyuCharts) throw new Error("统计图表组件未加载，请刷新页面");
    var t = d.totals || {};
    var focus = d.focus || [];
    var kpiData = {
      classes: t.classes || 0, students: t.students || 0, net: t.net || 0,
      pending: t.pending || 0, focus: focus.length
    };
    renderStatsChart("kpis", "statKpis", kpiData, { items: [
      { key: "classes", label: "班级数", unit: "个", tone: "ink" },
      { key: "students", label: "学生数", unit: "人", tone: "ink" },
      { key: "net", label: "净分", unit: "分", tone: "gold", sign: true },
      { key: "pending", label: "待确认", unit: "条", tone: "warn" },
      { key: "focus", label: "重点对象", unit: "项", tone: "danger" }
    ] });
    $("statTrendRange").textContent = d.range ? (d.range.start + " ~ " + d.range.end) : "—";
    $("statFocusCount").textContent = focus.length + " 项";
    // 本周无已确认事件时给出可操作提示，避免被误认为图表未渲染
    var period = $("statPeriod").value || "week";
    var weekEmpty = period === "week" && !(t.confirmed || 0);
    var emptyText = weekEmpty ? "本周暂无已确认事件，可切换「本月」查看" : "";
    var emptyAction = weekEmpty ? {
      text: "查看本月",
      onClick: function () {
        $("statPeriod").value = "month";
        loadStats();
      }
    } : null;
    renderStatsChart("trend", "statTrend", d.daily || [], {
      height: 280, emptyText: emptyText, emptyAction: emptyAction
    });
    renderStatsChart("criteriaMix", "statCriteriaMix", d.criteria_breakdown || [], {
      emptyText: weekEmpty ? "本周暂无指标明细，可切换「本月」查看" : "", emptyAction: emptyAction
    });
    renderStatsChart("classBars", "statClassBars", d.classes || [], {
      onSelect: function (classId) {
        $("statClass").value = String(classId);
        loadStats();
      }
    });
    renderStatsChart("focusList", "statFocusCards", focus);
    renderStatsClasses(d.classes || []);
  }

  function renderStatsClasses(items) {
    var body = $("statClassBody");
    body.innerHTML = "";
    items.forEach(function (c) {
      var tr = el("tr");
      tr.innerHTML =
        '<td>' + esc(c.name || c.class_id) + '</td>' +
        '<td class="mono">' + signed(c.net) + '</td>' +
        '<td class="mono">' + signed(c.positive) + ' / ' + signed(c.negative) + '</td>' +
        '<td>' + bandBadge(c.band) + '</td>';
      body.appendChild(tr);
    });
    $("statClassEmpty").hidden = items.length > 0;
  }

  function exportStats() {
    fetch(API + "/deyu/stats/export?" + statsQuery(), { credentials: "include" })
      .then(function (r) {
        if (r.status === 401) {
          location.href = LOGIN;
          throw new Error("未登录或登录已过期");
        }
        if (!r.ok) {
          return r.json().then(function (j) {
            throw new Error((j && (j.message || j.error)) || "导出失败");
          }, function () {
            throw new Error("导出失败");
          });
        }
        return r.blob();
      })
      .then(function (blob) {
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "全校德育统计_" + todayStr() + ".xlsx";
        document.body.appendChild(a);
        a.click();
        setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 0);
        toast("已导出 Excel", "ok");
      })
      .catch(errToast);
  }

  /* ---------------- 名单与寝室 ---------------- */
  function loadRoster() {
    switchRosterTab(state.roster.tab || "students");
    return loadRosterClasses().then(function () {
      if (state.roster.tab === "dorms" && !state.roster.dormLoaded) {
        state.roster.dormLoaded = true;
        return loadDormList();
      }
    }).catch(errToast);
  }

  function switchRosterTab(tab) {
    state.roster.tab = tab;
    [].forEach.call(document.querySelectorAll("#rosterTabs button"), function (b) {
      b.classList.toggle("on", b.getAttribute("data-tab") === tab);
    });
    $("rosterStudents").hidden = tab !== "students";
    $("rosterDorms").hidden = tab !== "dorms";
    if (tab === "dorms" && !state.roster.dormLoaded) {
      state.roster.dormLoaded = true;
      loadDormList().catch(errToast);
    }
  }

  function loadRosterClasses() {
    return api("/deyu/classes").then(function (j) {
      state.roster.classes = (j && j.data && j.data.items) || [];
      fillRosterClassSelect($("rosterClass"));
      fillRosterClassSelect($("dormClass"));
    });
  }

  function fillRosterClassSelect(sel) {
    var prev = sel.value;
    sel.innerHTML = '<option value="">请选择班级</option>';
    state.roster.classes.forEach(function (c) {
      var opt = document.createElement("option");
      opt.value = c.class_id;
      opt.textContent = (c.name || c.class_id) + "（" + (c.student_count || 0) + "人）";
      sel.appendChild(opt);
    });
    if (prev) sel.value = prev;
  }

  function uploadRoster(file, overwrite) {
    if (!file) return;
    var fd = new FormData();
    fd.append("file", file);
    if (overwrite) fd.append("overwrite", "true");
    $("rosterUploadBtn").disabled = true;
    fetch(API + "/deyu/students/import", {
      method: "POST", credentials: "include", body: fd
    }).then(function (r) {
      if (r.status === 401) { location.href = LOGIN; throw new Error("未登录或登录已过期"); }
      return r.json().then(function (j) {
        if (!j || j.code !== 0) throw new Error((j && (j.error || j.message)) || "导入失败");
        return j.data;
      });
    }).then(function (data) {
      renderImportResult(data);
      var msg = "导入完成：成功 " + data.ok_count + " 行";
      if (data.conflict_count) msg += "，冲突 " + data.conflict_count + " 行";
      if (data.failed_count) msg += "，错误 " + data.failed_count + " 行";
      toast(msg, data.failed_count ? "err" : "ok");
      if (state.roster.classId) loadRosterStudents(state.roster.classId).catch(errToast);
      loadRosterClasses().catch(errToast);
      if (!overwrite && data.conflicts && data.conflicts.length) {
        state.roster.pendingFile = file;
        openConflictModal(data.conflicts);
      } else {
        state.roster.pendingFile = null;
      }
    }).catch(errToast).then(function () {
      $("rosterUploadBtn").disabled = false;
      $("rosterFile").value = "";
    });
  }

  function renderImportResult(data) {
    var body = $("importBody");
    body.innerHTML = "";
    (data.rows || []).forEach(function (r) {
      var tr = el("tr");
      var badge;
      if (r.status === "ok") badge = '<span class="badge ok">成功</span>';
      else if (r.status === "conflict") badge = '<span class="badge warn">冲突</span>';
      else badge = '<span class="badge danger">错误</span>';
      tr.innerHTML =
        '<td class="mono">' + esc(r.row) + '</td>' +
        '<td>' + esc(r.class_id || "—") + '</td>' +
        '<td>' + esc(r.name || "—") + '</td>' +
        '<td class="mono">' + esc(r.student_no || "—") + '</td>' +
        '<td>' + badge + '</td>' +
        '<td class="focus-reason">' + esc(r.message || "") + '</td>';
      body.appendChild(tr);
    });
    state.roster.importErrors = data.errors || [];
    $("importBadge").textContent =
      "成功 " + (data.ok_count || 0) +
      " / 冲突 " + (data.conflict_count || 0) +
      " / 错误 " + (data.failed_count || 0) + " 行";
    var errBtn = $("importErrBtn");
    if (errBtn) {
      errBtn.hidden = !state.roster.importErrors.length;
      errBtn.onclick = downloadImportErrors;
    }
    $("importEmpty").hidden = !!(data.rows && data.rows.length);
  }

  /* ---------------- 导入错误明细导出（CSV，带 UTF-8 BOM） ---------------- */
  function csvCell(v) {
    var s = v == null ? "" : String(v);
    if (/[",\r\n]/.test(s)) s = '"' + s.replace(/"/g, '""') + '"';
    return s;
  }

  function downloadImportErrors() {
    var errors = state.roster.importErrors || [];
    if (!errors.length) return;
    var lines = ["行号,学号,姓名,原因"];
    errors.forEach(function (e) {
      lines.push([csvCell(e.row), csvCell(e.student_no), csvCell(e.name),
        csvCell(e.reason)].join(","));
    });
    var blob = new Blob(["\ufeff" + lines.join("\r\n")],
      { type: "text/csv;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "导入错误明细.csv";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  /* ---------------- 名单冲突确认 ---------------- */
  function openConflictModal(conflicts) {
    var body = $("conflictBody");
    body.innerHTML = "";
    conflicts.forEach(function (c) {
      var tr = el("tr");
      tr.innerHTML =
        '<td class="mono">' + esc(c.row) + '</td>' +
        '<td>' + esc(c.class_id || "—") + '</td>' +
        '<td class="mono">' + esc(c.student_no || c.student_id || "—") + '</td>' +
        '<td>' + esc(c.name || "—") + '</td>' +
        '<td><span class="badge warn">待确认</span></td>';
      body.appendChild(tr);
    });
    $("conflictText").textContent =
      "检测到 " + conflicts.length + " 名学生与现有名单冲突（见下表学号与姓名）。" +
      "请选择使用新上传的数据覆盖，或保留旧数据。";
    var m = $("conflictModal");
    m.hidden = false;
    function close(v) {
      m.hidden = true;
      $("conflictClose").onclick = null;
      $("conflictKeep").onclick = null;
      $("conflictOverwrite").onclick = null;
      return v;
    }
    $("conflictClose").onclick = function () {
      close("keep");
      state.roster.pendingFile = null;
    };
    $("conflictKeep").onclick = function () {
      close("keep");
      state.roster.pendingFile = null;
      toast("已保留旧数据", "ok");
    };
    $("conflictOverwrite").onclick = function () {
      close("overwrite");
      var file = state.roster.pendingFile;
      state.roster.pendingFile = null;
      if (file) uploadRoster(file, true);
    };
  }

  function previewNumbering() {
    var cid = $("rosterClass").value;
    if (!cid) { toast("请先选择班级", "err"); return Promise.resolve(); }
    var width = parseInt($("numberWidth").value, 10) || 2;
    return apiJson("/deyu/students/numbering/preview", "POST", {
      class_id: cid, prefix: $("numberPrefix").value.trim(), width: width
    }).then(function (j) {
      state.roster.numbering = j.data;
      renderNumbering(j.data);
    }).catch(errToast);
  }

  function renderNumbering(data) {
    var body = $("numberBody");
    body.innerHTML = "";
    var items = (data && data.items) || [];
    items.forEach(function (it) {
      var tr = el("tr");
      var badge;
      if (it.skipped) badge = '<span class="badge">已有学号</span>';
      else if (it.conflict) badge = '<span class="badge danger">冲突</span>';
      else badge = '<span class="badge warn">待写入</span>';
      tr.innerHTML =
        '<td class="mono">' + esc(it.student_no) + '</td>' +
        '<td class="mono">' + esc(it.student_id) + '</td>' +
        '<td>' + esc(it.name) + '</td>' +
        '<td>' + badge + '</td>';
      body.appendChild(tr);
    });
    var rule = "规则：" + ((data && data.rule) || "—");
    if (data && data.conflict_count) rule += " · 冲突 " + data.conflict_count + " 项，请调整前缀";
    $("numberRule").textContent = rule;
    $("numberEmpty").hidden = items.length > 0;
    var pending = items.filter(function (it) { return !it.skipped && !it.conflict; });
    $("numberApply").disabled = !pending.length || !!(data && data.conflict_count);
  }

  function applyNumbering() {
    var data = state.roster.numbering;
    if (!data) return;
    var items = (data.items || []).filter(function (it) { return !it.skipped; })
      .map(function (it) {
        return { student_id: it.student_id, student_no: it.student_no };
      });
    if (!items.length) { toast("没有需要写入的学号", "err"); return; }
    $("numberApply").disabled = true;
    apiJson("/deyu/students/numbering/apply", "POST",
            { class_id: data.class_id, items: items }).then(function (j) {
      var d = j.data || {};
      toast("已写入 " + (d.updated || 0) + " 个学号，跳过 " + (d.skipped || 0) + " 个已有学号", "ok");
      return previewNumbering();
    }).catch(function (e) {
      $("numberApply").disabled = false;
      errToast(e);
    });
  }

  function loadDormList() {
    return api("/deyu/dorms").then(function (j) {
      state.roster.dorms = (j && j.data) || [];
      renderDorms();
    });
  }

  function renderDorms() {
    var box = $("dormGrid");
    box.innerHTML = "";
    var items = state.roster.dorms || [];
    items.forEach(function (d) {
      var cls = "dorm-card" + (d.remaining <= 0 ? " full" : "") +
        (String(state.roster.dormId) === String(d.id) ? " sel" : "");
      var card = el("button", cls);
      card.type = "button";
      card.setAttribute("data-dorm-id", d.id);
      card.innerHTML =
        '<div class="t">' + esc(d.label || ((d.building || "") + d.room_no)) + '</div>' +
        '<div class="m">' + esc(d.gender || "不限") + ' · 已住 ' +
        esc(d.occupied) + ' / ' + esc(d.capacity) + '</div>' +
        '<div class="r">余量 ' + esc(d.remaining) +
        (d.status && d.status !== "active" ? " · " + esc(d.status) : "") + '</div>';
      box.appendChild(card);
    });
    $("dormBadge").textContent = items.length + " 间";
    $("dormEmpty").hidden = items.length > 0;
    updateDormSelection();
  }

  function loadRosterStudents(cid) {
    state.roster.classId = cid || "";
    state.roster.checked = {};
    state.roster.picked = {};
    state.roster.pendingFile = null;
    if (!cid) {
      state.roster.students = [];
      renderRosterTable();
      renderDormStudents();
      return Promise.resolve([]);
    }
    return api("/deyu/students?class_id=" + encodeURIComponent(cid)).then(function (j) {
      state.roster.students = (j && j.data && j.data.items) || [];
      renderRosterTable();
      renderDormStudents();
      return state.roster.students;
    });
  }

  function renderRosterTable() {
    var body = $("rosterBody");
    if (!body) return;
    var items = state.roster.students || [];
    body.innerHTML = items.map(function (s) {
      return '<tr>' +
        '<td><input type="checkbox" data-pick value="' + esc(s.student_id) + '"' +
        (state.roster.picked[s.student_id] ? ' checked' : '') + '></td>' +
        '<td class="mono">' + esc(s.student_no || s.student_id) + '</td>' +
        '<td>' + esc(s.name) + '</td>' +
        '<td>' + esc(s.gender || "") + '</td>' +
        '<td>' + esc(s.major || "") + '</td>' +
        '<td>' + esc(s.grade || "") + '</td>' +
        '<td>' + esc(s.class_id || "") + '</td>' +
        '<td>' + esc(s.dorm || "") + '</td>' +
        '<td>' + esc(s.boarding_type || "") + '</td>' +
        '<td>' + esc(s.guardian_name || "") + '</td>' +
        '<td>' + esc(s.guardian_relation || "") + '</td>' +
        '<td class="mono">' + esc(s.guardian_phone || "") + '</td>' +
        '<td>' + esc(s.bed_no || "") + '</td>' +
        '<td>' + esc(s.address || "") + '</td>' +
        '<td>' + esc(s.status || "") + '</td>' +
        '<td><button type="button" class="btn sm danger" data-stu-del="' +
        esc(s.student_id) + '">删除</button></td>' +
        '</tr>';
    }).join("");
    $("rosterStuBadge").textContent = items.length + " 人";
    $("rosterEmpty").textContent = state.roster.classId
      ? "该班级暂无学生，可上传名单导入" : "选择班级后加载学生名单";
    $("rosterEmpty").hidden = items.length > 0;
    updateRosterSelection();
  }

  function pickedStudents() {
    return Object.keys(state.roster.picked).filter(function (k) {
      return state.roster.picked[k];
    });
  }

  function updateRosterSelection() {
    var ids = pickedStudents();
    var total = (state.roster.students || []).length;
    $("rosterDelete").disabled = !ids.length;
    $("rosterSelHint").textContent = ids.length ? ("已选 " + ids.length + " 人") : "未选择学生";
    $("rosterPickAll").checked = total > 0 && ids.length === total;
    $("rosterPickAll").indeterminate = ids.length > 0 && ids.length < total;
  }

  function togglePickAll(checked) {
    state.roster.picked = {};
    if (checked) {
      (state.roster.students || []).forEach(function (s) {
        state.roster.picked[s.student_id] = true;
      });
    }
    renderRosterTable();
  }

  function removeRosterStudents(ids) {
    var cid = state.roster.classId;
    if (!cid || !ids.length) return Promise.resolve();
    return openConfirm({
      title: "删除学生",
      text: "确定删除选中的 " + ids.length + " 名学生？删除后不可恢复。",
      okText: "删除"
    }).then(function (ok) {
      if (!ok) return;
      return apiJson("/deyu/students/delete", "POST",
                     { class_id: cid, student_ids: ids }).then(function (j) {
        var d = j.data || {};
        toast("已删除 " + (d.deleted || 0) + " 名学生", "ok");
        return loadRosterStudents(cid).then(function () {
          return loadRosterClasses();
        });
      });
    }).catch(errToast);
  }

  function selectedClass() {
    var cid = String(state.roster.classId || "");
    var hit = (state.roster.classes || []).filter(function (c) {
      return String(c.class_id) === cid;
    })[0];
    return hit || null;
  }

  function openClassEditForm() {
    var c = selectedClass();
    if (!c) {
      toast("请先选择班级", "err");
      return;
    }
    openForm({
      title: "编辑班级：" + c.class_id,
      fields: [
        { name: "class_id", label: "班级编号", value: c.class_id, readonly: true },
        { name: "name", label: "班级名称", value: c.name || "", placeholder: "留空默认「编号+班」" },
        { name: "grade", label: "年级", value: c.grade || "" }
      ],
      tip: "班级编号不可修改；名称与年级保存后立即生效。",
      onSubmit: function (v) {
        return apiJson("/deyu/classes/update", "POST", {
          class_id: c.class_id, name: v.name, grade: v.grade
        }).then(function () {
          toast("班级已更新", "ok");
          return loadRosterClasses();
        });
      }
    });
  }

  function deleteClass() {
    var c = selectedClass();
    if (!c) {
      toast("请先选择班级", "err");
      return;
    }
    return openConfirm({
      title: "删除班级",
      text: "确定删除 " + (c.name || c.class_id) + "？班内仍有学生时无法删除。",
      okText: "删除"
    }).then(function (ok) {
      if (!ok) return;
      return apiJson("/deyu/classes/delete", "POST", { class_id: c.class_id }).then(function () {
        toast("班级已删除", "ok");
        state.roster.classId = "";
        state.roster.students = [];
        state.roster.picked = {};
        return loadRosterClasses().then(function () {
          $("rosterClass").value = "";
          renderRosterTable();
        });
      });
    }).catch(errToast);
  }

  function openClassForm() {
    openForm({
      title: "新增班级",
      fields: [
        { name: "class_id", label: "班级编号", required: true, placeholder: "如 2403" },
        { name: "name", label: "班级名称", placeholder: "留空默认「编号+班」" },
        { name: "grade", label: "年级", placeholder: "如 2024" }
      ],
      tip: "班级编号创建后作为学生归属班级，不可重复。",
      onSubmit: function (v) {
        return apiJson("/deyu/classes/create", "POST", {
          class_id: v.class_id, name: v.name, grade: v.grade
        }).then(function (j) {
          var cid = (j.data && j.data.class_id) || v.class_id;
          toast("班级已创建", "ok");
          return loadRosterClasses().then(function () {
            $("rosterClass").value = cid;
            return loadRosterStudents(cid);
          });
        });
      }
    });
  }

  function openStudentForm() {
    var cid = state.roster.classId;
    if (!cid) {
      toast("请先选择班级", "err");
      return;
    }
    var clsOpts = state.roster.classes.map(function (c) {
      return { v: c.class_id, t: (c.name || c.class_id) + "（" + (c.student_count || 0) + "人）" };
    });
    openForm({
      title: "新增学生", wide: true,
      fields: [
        { name: "class_id", label: "班级", type: "select", required: true, value: cid, options: clsOpts },
        { name: "student_no", label: "学号", placeholder: "可留空，系统自动生成" },
        { name: "name", label: "姓名", required: true },
        { name: "gender", label: "性别", type: "select", required: true, value: "",
          options: [{ v: "", t: "请选择" }, { v: "男", t: "男" }, { v: "女", t: "女" }] },
        { name: "major", label: "专业" },
        { name: "grade", label: "年级" },
        { name: "dorm", label: "宿舍号" },
        { name: "boarding_type", label: "住宿类型", type: "select",
          options: [{ v: "住校", t: "住校" }, { v: "走读", t: "走读" }] },
        { name: "bed_no", label: "床位号" },
        { name: "guardian_name", label: "家长姓名" },
        { name: "guardian_relation", label: "家长关系" },
        { name: "guardian_phone", label: "家长电话" },
        { name: "address", label: "家庭住址", full: true },
        { name: "phone", label: "学生电话" },
        { name: "status", label: "状态", type: "select", value: "在读",
          options: ["在读", "休学", "毕业", "退学"].map(function (s) { return { v: s, t: s }; }) }
      ],
      tip: "姓名、性别、班级为必填项；学号留空时自动生成。",
      onSubmit: function (v) {
        return apiJson("/deyu/students/create", "POST", v).then(function (j) {
          var target = (j.data && j.data.class_id) || v.class_id;
          toast("学生已添加", "ok");
          $("rosterClass").value = target;
          return loadRosterClasses().then(function () {
            return loadRosterStudents(target);
          });
        });
      }
    });
  }

  function renderDormStudents() {
    var box = $("dormStudents");
    box.innerHTML = "";
    var items = state.roster.students || [];
    items.forEach(function (s) {
      var label = el("label");
      var cb = document.createElement("input");
      cb.type = "checkbox";
      cb.value = s.student_id;
      cb.checked = !!state.roster.checked[s.student_id];
      cb.addEventListener("change", function () {
        state.roster.checked[s.student_id] = cb.checked;
        updateDormSelection();
      });
      label.appendChild(cb);
      var meta = el("span", "stu-meta");
      meta.innerHTML = '<b class="mono">' + esc(s.student_no || s.student_id) + '</b> ' +
        esc(s.name) + ' <em>' + esc(s.gender || "未登记") + '</em> ' +
        (s.dorm
          ? '<span class="badge">' + esc(s.dorm) + '</span>'
          : '<span class="badge warn">未分配</span>');
      label.appendChild(meta);
      box.appendChild(label);
    });
    $("dormStuEmpty").hidden = items.length > 0;
    updateDormSelection();
  }

  function checkedStudents() {
    return Object.keys(state.roster.checked).filter(function (k) {
      return state.roster.checked[k];
    });
  }

  function selectedDorm() {
    var found = null;
    (state.roster.dorms || []).forEach(function (d) {
      if (String(d.id) === String(state.roster.dormId)) found = d;
    });
    return found;
  }

  function updateDormSelection() {
    var dorm = selectedDorm();
    var count = checkedStudents().length;
    $("dormSelHint").textContent = dorm
      ? ("已选：" + (dorm.label || dorm.room_no) + " · " + (dorm.gender || "不限") +
         " · 余量 " + dorm.remaining)
      : "未选择寝室";
    $("dormPickBadge").textContent = "已选 " + count + " 人";
    $("dormAssign").disabled = !dorm || !count || dorm.remaining <= 0;
    $("dormUnassign").disabled = !count;
  }

  function onDormPick(e) {
    var card = e.target.closest("[data-dorm-id]");
    if (!card) return;
    state.roster.dormId = card.getAttribute("data-dorm-id");
    renderDorms();
  }

  function assignDorm() {
    var dorm = selectedDorm();
    var ids = checkedStudents();
    var cid = $("dormClass").value;
    if (!dorm) { toast("请先选择寝室", "err"); return; }
    if (!ids.length) { toast("请勾选学生", "err"); return; }
    $("dormAssign").disabled = true;
    apiJson("/deyu/dorms/assign", "POST",
            { dorm_id: dorm.id, student_ids: ids, class_id: cid }).then(function (j) {
      var d = j.data || {};
      toast("已分配 " + (d.assigned || 0) + " 人到 " + (d.label || dorm.label || ""), "ok");
      return Promise.all([loadDormList(), loadRosterStudents(cid)]);
    }).catch(function (e) {
      $("dormAssign").disabled = false;
      errToast(e);
    });
  }

  function unassignDorm() {
    var ids = checkedStudents();
    var cid = $("dormClass").value;
    if (!ids.length) { toast("请勾选学生", "err"); return; }
    $("dormUnassign").disabled = true;
    apiJson("/deyu/dorms/unassign", "POST",
            { student_ids: ids, class_id: cid }).then(function (j) {
      var d = j.data || {};
      toast("已移出 " + (d.cleared || 0) + " 人", "ok");
      return Promise.all([loadDormList(), loadRosterStudents(cid)]);
    }).catch(function (e) {
      $("dormUnassign").disabled = false;
      errToast(e);
    });
  }

  /* ---------------- 启动 ---------------- */
  function init() {
    var d = new Date();
    $("today").textContent = d.getFullYear() + "年" + (d.getMonth() + 1) + "月" + d.getDate() + "日";
    $("regDate").value = todayStr();

    $("nav").addEventListener("click", function (e) {
      var btn = e.target.closest("[data-view]");
      if (btn) switchView(btn.getAttribute("data-view"));
    });

    $("logout").addEventListener("click", function () {
      location.href = "/api/v1/logout";
    });

    $("criteriaAddBtn").addEventListener("click", function () {
      if (!state.criteria.length) {
        loadCriteria().then(function () { openCriteriaForm(null); });
      } else {
        openCriteriaForm(null);
      }
    });
    $("criteriaPraise").addEventListener("click", onCriteriaAction);
    $("criteriaImprove").addEventListener("click", onCriteriaAction);

    $("regClass").addEventListener("change", function () {
      loadStudents(this.value).catch(errToast);
    });
    $("regSubmit").addEventListener("click", submitRegister);
    $("pendingBody").addEventListener("click", onReviewAction);

    $("statPeriod").addEventListener("change", loadStats);
    $("statGrade").addEventListener("change", function () {
      fillStatsClassOptions();
      loadStats();
    });
    $("statClass").addEventListener("change", loadStats);
    $("statCriteria").addEventListener("change", loadStats);
    $("statRefresh").addEventListener("click", loadStats);
    $("statExport").addEventListener("click", exportStats);

    $("rosterTabs").addEventListener("click", function (e) {
      var btn = e.target.closest("[data-tab]");
      if (btn) switchRosterTab(btn.getAttribute("data-tab"));
    });
    $("rosterUploadBtn").addEventListener("click", function () { $("rosterFile").click(); });
    $("rosterFile").addEventListener("change", function () {
      uploadRoster(this.files && this.files[0]);
    });
    $("rosterClass").addEventListener("change", function () {
      state.roster.numbering = null;
      $("numberBody").innerHTML = "";
      $("numberEmpty").hidden = false;
      $("numberApply").disabled = true;
      loadRosterStudents(this.value).catch(errToast);
    });
    $("rosterBody").addEventListener("change", function (e) {
      var cb = e.target.closest("input[data-pick]");
      if (!cb) return;
      state.roster.picked[cb.value] = cb.checked;
      updateRosterSelection();
    });
    $("rosterBody").addEventListener("click", function (e) {
      var btn = e.target.closest("[data-stu-del]");
      if (btn) removeRosterStudents([btn.getAttribute("data-stu-del")]);
    });
    $("rosterPickAll").addEventListener("change", function () {
      togglePickAll(this.checked);
    });
    $("rosterDelete").addEventListener("click", function () {
      removeRosterStudents(pickedStudents());
    });
    $("rosterClassAdd").addEventListener("click", openClassForm);
    $("rosterClassEdit").addEventListener("click", openClassEditForm);
    $("rosterClassDel").addEventListener("click", deleteClass);
    $("rosterAddStu").addEventListener("click", openStudentForm);
    $("numberPreview").addEventListener("click", previewNumbering);
    $("numberApply").addEventListener("click", applyNumbering);

    $("dormClass").addEventListener("change", function () {
      loadRosterStudents(this.value).catch(errToast);
    });
    $("dormGrid").addEventListener("click", onDormPick);
    $("dormAssign").addEventListener("click", assignDorm);
    $("dormUnassign").addEventListener("click", unassignDorm);

    api("/me").then(function (j) {
      state.me = j.data || {};
      var name = state.me.name || state.me.user_id || "政教处";
      $("userName").textContent = name;
      $("userRole").textContent = state.me.category || "管理员";
      $("avatar").textContent = name.slice(0, 1);
    }).catch(errToast);

    switchView("home");
  }

  init();
})();
