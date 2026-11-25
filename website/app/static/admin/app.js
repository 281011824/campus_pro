/* 学校管理后台 · 前端逻辑（无依赖，原生 JS） */
(function () {
  "use strict";

  var API = "/api/v1/admin";
  var LOGIN = "/api/v1/login?next=/api/admin";

  var state = { view: "home", me: null, classes: [], classList: [], classFilter: "", dorms: [], categories: [], headteachers: [], teachers: [] };
  var pg = {
    teacher: { page: 1, q: "", category: "" },
    student: { page: 1, q: "", class_id: "" },
    sa: { page: 1, q: "", class_id: "" },
    head: { page: 1, q: "" }
  };
  var fileKind = null; // 待导入类型
  var stuPicked = {};  // 学生管理中已勾选的学生（key: class_id/student_id）

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
  function fmtTs(s) {
    if (!s) return "—";
    return String(s).replace("T", " ").slice(0, 19);
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
            throw new Error(j.message || "操作失败");
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
  function download(url) {
    // 同源 GET 会携带登录 cookie，浏览器按 Content-Disposition 触发下载
    location.href = API + url;
  }

  /* ---------------- Toast ---------------- */
  var toastTimer = null;
  function toast(msg, kind) {
    var t = $("toast");
    t.textContent = msg;
    t.className = "toast" + (kind ? " " + kind : "");
    t.style.display = "block";
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.style.display = "none"; }, 2600);
  }

  /* ---------------- 确认弹窗 ---------------- */
  function openConfirm(o) {
    o = o || {};
    $("confirmTitle").textContent = o.title || "确认操作";
    $("confirmText").textContent = o.text || "";
    $("confirmOk").textContent = o.okText || "确定";
    $("confirmOk").className = "btn " + (o.danger === false ? "primary" : "danger");
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
      if (f.type === "checkbox") {
        input = document.createElement("input");
        input.type = "checkbox";
        input.name = f.name;
        input.checked = !!f.value;
        label.innerHTML = "";
        label.className = "check-label";
        label.appendChild(input);
        label.appendChild(document.createTextNode(" " + (f.label || f.name)));
        wrap.classList.add("full");
        wrap.appendChild(label);
        grid.appendChild(wrap);
        return;
      }
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
      } else if (f.type === "multiselect") {
        input = document.createElement("select");
        input.name = f.name;
        input.multiple = true;
        input.size = f.size || 8;
        var mopts = f.options || [];
        var mvals = (f.value || []).map(String);
        mopts.forEach(function (op) {
          var mopt = document.createElement("option");
          mopt.value = op.v; mopt.textContent = op.t;
          if (mvals.indexOf(String(op.v)) >= 0) mopt.selected = true;
          input.appendChild(mopt);
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
      }
      wrap.appendChild(input);
      grid.appendChild(wrap);
    });
    if (o.tip) { var tip = el("p", "form-tip", esc(o.tip)); body.appendChild(tip); }

    var m = $("formModal");
    m.hidden = false;
    function close() { m.hidden = true; }
    $("formClose").onclick = close;
    $("formCancel").onclick = close;
    $("formSubmit").onclick = function () {
      var values = {};
      var ok = true;
      [].forEach.call(grid.querySelectorAll("[name]"), function (inp) {
        if (inp.type === "checkbox") values[inp.name] = inp.checked;
        else if (inp.multiple) values[inp.name] = Array.from(inp.selectedOptions).map(function (o) { return o.value; });
        else values[inp.name] = inp.value;
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
    home: { title: "管理台概览", sub: "全校账号与学生主数据统一维护" },
    teachers: { title: "教工管理", sub: "维护本校教职工的登录账号、部门、职务与状态" },
    studentAccounts: { title: "学生账号", sub: "为在册学生生成 / 重置登录账号，默认密码 123456" },
    students: { title: "学生管理（全校）", sub: "学号、班级、专业、宿舍与家长联系信息的分配与维护" },
    classes: { title: "班级管理", sub: "全校班级字典，学生主数据引用此处" },
    headteachers: { title: "班主任管理", sub: "从全校教职工中指定班主任名单，作为班级绑定范围" },
    dorms: { title: "寝室管理", sub: "楼栋 / 房号 / 容量与入住统计" },
    system: { title: "系统", sub: "修改登录密码与查看管理审计" }
  };
  function switchView(v) {
    state.view = v;
    [].forEach.call(document.querySelectorAll(".nav button"), function (b) {
      b.classList.toggle("on", b.getAttribute("data-view") === v);
    });
    [].forEach.call(document.querySelectorAll(".view"), function (s) {
      s.classList.toggle("on", s.id === "view-" + v);
    });
    var meta = VIEW_META[v] || {};
    $("pageTitle").textContent = meta.title || "";
    $("pageSub").textContent = meta.sub || "";
    loadView(v);
  }
  function loadView(v) {
    if (v === "home") loadDashboard();
    else if (v === "teachers") loadTeachers();
    else if (v === "studentAccounts") loadStudentAccounts();
    else if (v === "students") loadStudents();
    else if (v === "classes") loadClassMgmt();
    else if (v === "headteachers") loadHeadteachers();
    else if (v === "dorms") loadDormMgmt();
    else if (v === "system") loadSystem();
  }

  /* ---------------- 通用：状态徽章 ---------------- */
  function accountStatusBadge(s) {
    s = s || "";
    if (s === "停用" || s === "disabled") return '<span class="badge danger"><span class="status-dot off"></span>停用</span>';
    return '<span class="badge ok"><span class="status-dot on"></span>' + esc(s || "本校") + '</span>';
  }
  function stuStatusBadge(s) {
    s = s || "在读";
    if (s === "在读") return '<span class="badge ok">' + esc(s) + '</span>';
    if (s === "休学" || s === "毕业") return '<span class="badge warn">' + esc(s) + '</span>';
    if (s === "退学") return '<span class="badge danger">' + esc(s) + '</span>';
    return '<span class="badge">' + esc(s) + '</span>';
  }

  /* ---------------- 概览 ---------------- */
  function loadDashboard() {
    api("/dashboard").then(function (j) {
      var d = j.data || {};
      var k = d.kpi || {};
      var items = [
        { k: "教师 / 领导", v: k.teachers },
        { k: "在校学生", v: k.students },
        { k: "班级", v: k.classes },
        { k: "寝室", v: k.dorms },
        { k: "学生账号", v: k.student_accounts },
        { k: "管理员", v: k.admins }
      ];
      $("kpis").innerHTML = items.map(function (it) {
        return '<div class="kpi"><div class="k">' + esc(it.k) + '</div>' +
          '<div class="v mono">' + esc(it.v == null ? "—" : it.v) + '</div></div>';
      }).join("");
      renderAudit($("recentAudit"), d.recent_audit || [], 6);
    }).catch(function (e) { toast(e.message, "err"); });
  }
  function renderAudit(tbody, rows, limit) {
    if (!rows || !rows.length) {
      tbody.innerHTML = '<tr><td colspan="6" class="empty">暂无操作记录</td></tr>';
      return;
    }
    if (limit) rows = rows.slice(0, limit);
    tbody.innerHTML = rows.map(function (r) {
      return '<tr>' +
        '<td class="audit-ts">' + esc(fmtTs(r.ts)) + '</td>' +
        '<td>' + esc(r.user_id) + '</td>' +
        '<td class="audit-act">' + esc(r.action) + '</td>' +
        '<td>' + esc(r.resource || "") + '</td>' +
        '<td>' + esc(r.result || "") + '</td>' +
        '<td class="muted">' + esc(r.detail || "") + '</td>' +
        '</tr>';
    }).join("");
  }

  /* ---------------- 班级 / 寝室字典（供下拉与筛选） ---------------- */
  function loadClasses() {
    return api("/classes").then(function (j) {
      state.classes = j.data || [];
      refreshClassSelects();
      return state.classes;
    }).catch(function () { state.classes = []; });
  }
  function loadDorms() {
    return api("/dorms").then(function (j) {
      state.dorms = j.data || [];
      return state.dorms;
    }).catch(function () { state.dorms = []; });
  }
  function refreshClassSelects() {
    var opts = '<option value="">全部班级</option>' +
      state.classes.map(function (c) {
        return '<option value="' + esc(c.class_id) + '">' + esc(c.name || c.class_id) + '</option>';
      }).join("");
    var curS = $("sClass") ? $("sClass").value : "";
    var curSa = $("saClass") ? $("saClass").value : "";
    if ($("sClass")) $("sClass").innerHTML = opts;
    if ($("saClass")) $("saClass").innerHTML = opts;
    if (curS && $("sClass")) $("sClass").value = curS;
    if (curSa && $("saClass")) $("saClass").value = curSa;
  }
  function classOptions(sel) {
    return (sel ? [] : [{ v: "", t: "请选择班级" }]).concat(
      state.classes.map(function (c) { return { v: c.class_id, t: (c.name || c.class_id) }; }));
  }
  function dormOptions(sel) {
    return (sel ? [{ v: "", t: "（不分配）" }] : [{ v: "", t: "（不分配）" }]).concat(
      state.dorms.filter(function (d) { return d.status !== "停用"; })
        .map(function (d) { return { v: d.room_no, t: d.label + "（" + (d.gender || "不限") + "）" }; }));
  }

  /* ---------------- 分页 ---------------- */
  function renderPager(container, data, onChange) {
    if (!container) return;
    var total = data.total || 0, page = data.page || 1, size = data.size || 50;
    var pages = Math.max(1, Math.ceil(total / size));
    var html = '<span class="pg-info">共 ' + total + ' 条 · 第 ' + page + '/' + pages + ' 页</span>';
    html += '<button class="btn sm" data-pg="' + (page - 1) + '"' + (page <= 1 ? " disabled" : "") + '>上一页</button>';
    html += '<button class="btn sm" data-pg="' + (page + 1) + '"' + (page >= pages ? " disabled" : "") + '>下一页</button>';
    container.innerHTML = html;
    container.onclick = function (e) {
      var b = e.target.closest("button[data-pg]");
      if (!b || b.disabled) return;
      onChange(parseInt(b.getAttribute("data-pg"), 10));
    };
  }

  /* ---------------- 教师 / 领导账号 ---------------- */
  function loadTeachers() {
    var p = pg.teacher;
    $("teacherBody").innerHTML = '<tr><td colspan="7" class="loading">加载中…</td></tr>';
    var qs = "?page=" + p.page + "&size=50" +
      (p.q ? "&q=" + encodeURIComponent(p.q) : "") +
      (p.category ? "&category=" + encodeURIComponent(p.category) : "");
    api("/accounts/teachers" + qs).then(function (j) {
      var d = j.data || {};
      state.teachers = d.items || [];
      renderTeachers(state.teachers);
      renderPager($("teacherPager"), d, function (np) { p.page = np; loadTeachers(); });
      // 汇总类别选项
      var set = {};
      (d.items || []).forEach(function (it) { if (it.category) set[it.category] = 1; });
      ["教师", "领导", "行政", "政教处", "教官", "寝管", "教官寝管"].forEach(function (c) { set[c] = 1; });
      var sel = $("tCategory"), cur = sel.value;
      sel.innerHTML = '<option value="">全部类别</option>' +
        Object.keys(set).sort().map(function (c) { return '<option value="' + esc(c) + '">' + esc(c) + '</option>'; }).join("");
      sel.value = cur;
    }).catch(function (e) {
      $("teacherBody").innerHTML = '<tr><td colspan="7" class="empty">加载失败：' + esc(e.message) + '</td></tr>';
    });
  }
  function renderTeachers(items) {
    if (!items.length) {
      $("teacherBody").innerHTML = '<tr><td colspan="7" class="empty">暂无账号，点击右上角新增或批量导入</td></tr>';
      return;
    }
    $("teacherBody").innerHTML = items.map(function (it) {
      return '<tr>' +
        '<td class="mono">' + esc(it.userid) + '</td>' +
        '<td>' + esc(it.name) + '</td>' +
        '<td>' + esc(it.dept || "") + '</td>' +
        '<td>' + esc(it.post_name || "") + '</td>' +
        '<td>' + esc(it.category || "") + '</td>' +
        '<td>' + accountStatusBadge(it.status) + '</td>' +
        '<td><div class="row-actions">' +
        '<button type="button" class="btn sm" data-teacher-edit="' + esc(it.userid) + '">编辑</button>' +
        '<button type="button" class="btn sm" data-teacher-reset="' + esc(it.userid) + '">重置密码</button>' +
        '<button type="button" class="btn sm" data-teacher-toggle="' + esc(it.userid) + '" data-status="' + esc(it.status) + '">' +
        (it.status === "停用" ? "启用" : "停用") + '</button>' +
        '<button type="button" class="btn sm" data-teacher-del="' + esc(it.userid) + '">删除</button>' +
        '</div></td></tr>';
    }).join("");
  }
  function teacherForm(it) {
    it = it || {};
    var edit = !!it.userid;
    openForm({
      title: edit ? "编辑教工账号：" + it.userid : "新增教工账号",
      fields: [
        { name: "userid", label: "登录账号", required: true, value: it.userid, readonly: edit, placeholder: "如 JS0001" },
        { name: "name", label: "姓名", required: true, value: it.name },
        { name: "password", label: edit ? "新密码" : "初始密码", type: "password",
          placeholder: edit ? "留空则不修改" : "至少 6 位", required: !edit },
        { name: "wecom_userid", label: "企业微信 userid", value: it.wecom_userid || "" },
        { name: "dept", label: "部门", value: it.dept || "" },
        { name: "post_name", label: "职务", value: it.post_name || "" },
        { name: "category", label: "类别", type: "select", value: it.category || "教师",
          options: [{ v: "教师", t: "教师" }, { v: "领导", t: "领导" }, { v: "行政", t: "行政" }, { v: "政教处", t: "政教处" }, { v: "教官", t: "教官" }, { v: "寝管", t: "寝管" }, { v: "教官寝管", t: "教官寝管" }, { v: "其他", t: "其他" }] },
        { name: "status", label: "状态", type: "select", value: it.status || "本校",
          options: [{ v: "本校", t: "本校" }, { v: "停用", t: "停用" }] },
        { name: "is_headteacher", label: "指定为班主任（勾选后可被班级绑定）",
          type: "checkbox", value: !!it.is_headteacher }
      ],
      onSubmit: function (v) {
        return apiJson("/accounts/teachers", "POST", v).then(function (j) {
          toast(edit ? "已保存" : "账号已创建", "ok");
          loadTeachers();
          loadHeadteacherCandidates();
          if (state.view === "headteachers") loadHeadteachers();
        });
      }
    });
  }

  /* ---------------- 学生账号 ---------------- */
  function loadStudentAccounts() {
    var p = pg.sa;
    $("saBody").innerHTML = '<tr><td colspan="5" class="loading">加载中…</td></tr>';
    var qs = "?page=" + p.page + "&size=50" +
      (p.class_id ? "&class_id=" + encodeURIComponent(p.class_id) : "") +
      (p.q ? "&q=" + encodeURIComponent(p.q) : "");
    api("/accounts/students" + qs).then(function (j) {
      var d = j.data || {};
      renderStudentAccounts(d.items || []);
      renderPager($("saPager"), d, function (np) { p.page = np; loadStudentAccounts(); });
    }).catch(function (e) {
      $("saBody").innerHTML = '<tr><td colspan="5" class="empty">加载失败：' + esc(e.message) + '</td></tr>';
    });
  }
  function renderStudentAccounts(items) {
    if (!items.length) {
      $("saBody").innerHTML = '<tr><td colspan="5" class="empty">暂无学生账号，点击「批量生成账号」为在册学生创建</td></tr>';
      return;
    }
    $("saBody").innerHTML = items.map(function (it) {
      var off = it.status === "disabled";
      return '<tr>' +
        '<td>' + esc(it.class_id) + '</td>' +
        '<td class="mono">' + esc(it.student_no || it.student_id) + '</td>' +
        '<td>' + esc(it.name || "") + '</td>' +
        '<td>' + (off
          ? '<span class="badge danger"><span class="status-dot off"></span>停用</span>'
          : '<span class="badge ok"><span class="status-dot on"></span>启用</span>') + '</td>' +
        '<td><div class="row-actions">' +
        '<button class="btn sm" data-sa-reset data-c="' + esc(it.class_id) + '" data-s="' + esc(it.student_id) + '">重置密码</button>' +
        '<button class="btn sm" data-sa-toggle data-c="' + esc(it.class_id) + '" data-s="' + esc(it.student_id) + '" data-st="' + esc(it.status) + '">' +
        (off ? "启用" : "停用") + '</button>' +
        '</div></td></tr>';
    }).join("");
  }

  /* ---------------- 学生管理 ---------------- */
  function loadStudents() {
    var p = pg.student;
    stuPicked = {};
    $("studentBody").innerHTML = '<tr><td colspan="16" class="loading">加载中…</td></tr>';
    var qs = "?page=" + p.page + "&size=50" +
      (p.q ? "&q=" + encodeURIComponent(p.q) : "") +
      (p.class_id ? "&class_id=" + encodeURIComponent(p.class_id) : "");
    api("/students" + qs).then(function (j) {
      var d = j.data || {};
      renderStudents(d.items || []);
      renderPager($("studentPager"), d, function (np) { p.page = np; loadStudents(); });
    }).catch(function (e) {
      $("studentBody").innerHTML = '<tr><td colspan="16" class="empty">加载失败：' + esc(e.message) + '</td></tr>';
    });
  }
  function renderStudents(items) {
    if (!items.length) {
      $("studentBody").innerHTML = '<tr><td colspan="16" class="empty">暂无学生，可新增或批量导入</td></tr>';
      return;
    }
    $("studentBody").innerHTML = items.map(function (it) {
      return '<tr>' +
        '<td><input type="checkbox" data-stu-pick data-c="' + esc(it.class_id) +
        '" data-s="' + esc(it.student_id) + '" data-n="' + esc(it.name || "") + '"></td>' +
        '<td>' + esc(it.class_id) + '</td>' +
        '<td class="mono">' + esc(it.student_no || it.student_id) + '</td>' +
        '<td>' + esc(it.name) + '</td>' +
        '<td>' + esc(it.gender || "") + '</td>' +
        '<td>' + esc(it.major || "") + '</td>' +
        '<td>' + esc(it.grade || "") + '</td>' +
        '<td>' + esc(it.dorm || "") + '</td>' +
        '<td>' + esc(it.boarding_type || "") + '</td>' +
        '<td>' + esc(it.guardian_name || "") + '</td>' +
        '<td>' + esc(it.guardian_relation || "") + '</td>' +
        '<td>' + esc(it.guardian_phone || "") + '</td>' +
        '<td>' + esc(it.bed_no || "") + '</td>' +
        '<td>' + esc(it.address || "") + '</td>' +
        '<td>' + stuStatusBadge(it.status) + '</td>' +
        '<td><div class="row-actions">' +
        '<button class="btn sm" data-stu-edit data-c="' + esc(it.class_id) + '" data-s="' + esc(it.student_id) + '">编辑</button>' +
        '<button class="btn sm" data-stu-move data-c="' + esc(it.class_id) + '" data-s="' + esc(it.student_id) + '" data-n="' + esc(it.name || "") + '">转班</button>' +
        '<button class="btn sm" data-stu-del data-c="' + esc(it.class_id) + '" data-s="' + esc(it.student_id) + '">删除</button>' +
        '</div></td></tr>';
    }).join("");
  }
  function pickedList() {
    return Object.keys(stuPicked).map(function (k) { return stuPicked[k]; });
  }

  /* 转班：选择目标班级（排除源班级）→ 二次确认 → 调接口 */
  function openTransferForm(refs) {
    if (!refs || !refs.length) { toast("请先勾选要转班的学生", "err"); return; }
    loadClasses().then(function () {
      var source = {};
      refs.forEach(function (r) { source[r.class_id] = true; });
      var opts = (state.classes || []).filter(function (c) {
        return !source[c.class_id];
      }).map(function (c) {
        return { v: c.class_id, t: (c.name || c.class_id) + "（" + (c.student_count || 0) + "人）" };
      });
      if (!opts.length) { toast("没有可转入的其他班级", "err"); return; }
      var fromDesc = Object.keys(source).join("、");
      var names = refs.map(function (r) { return r.name || r.student_id; }).join("、");
      openForm({
        title: "学生转班（" + refs.length + " 人）",
        fields: [
          { name: "target_class_id", label: "目标班级", type: "select", required: true, options: opts }
        ],
        tip: "源班级：" + fromDesc + "；学生：" + names + "。历史德育记录按原班级保留。",
        onSubmit: function (v) {
          var to = v.target_class_id;
          return openConfirm({
            title: "确认转班",
            text: "确认将 " + names + " 从 " + fromDesc + " 转入 " + to + "？",
            okText: "确认转班"
          }).then(function (y) {
            if (!y) return;
            return apiJson("/students/transfer", "POST", {
              target_class_id: to,
              students: refs
            }).then(function (j) {
              var d = j.data || {};
              toast("已转班 " + (d.moved || refs.length) + " 人", "ok");
              stuPicked = {};
              loadStudents();
              loadClasses();
              loadClassMgmt();
              loadDashboard();
            });
          });
        }
      });
    }).catch(function (e) { toast(e.message, "err"); });
  }
  function studentForm(it, clsOpts, dormOpts) {
    it = it || {};
    var edit = !!(it.class_id && it.student_id);
    var dopts = (dormOpts || []).slice();
    if (it.dorm && !dopts.some(function (o) { return String(o.v) === String(it.dorm); })) {
      dopts.push({ v: it.dorm, t: it.dorm + "（导入值）" });
    }
    openForm({
      title: edit ? "编辑学生：" + (it.student_no || it.student_id) : "新增学生", wide: true,
      fields: [
        { name: "class_id", label: "班级", type: "select", required: true, value: it.class_id, options: clsOpts },
        { name: "student_id", label: "学号", value: (it.student_no || it.student_id) || "", readonly: edit,
          placeholder: edit ? "" : "可留空，系统自动生成" },
        { name: "name", label: "姓名", required: true, value: it.name },
        { name: "gender", label: "性别", type: "select", required: true, value: it.gender || "",
          options: [{ v: "", t: "请选择" }, { v: "男", t: "男" }, { v: "女", t: "女" }] },
        { name: "major", label: "专业", value: it.major || "" },
        { name: "grade", label: "年级", value: it.grade || "" },
        { name: "dorm", label: "宿舍号", type: "select", value: it.dorm || "", options: dopts },
        { name: "boarding_type", label: "住宿类型", type: "select", value: it.boarding_type || "",
          options: [{ v: "住校", t: "住校" }, { v: "走读", t: "走读" }] },
        { name: "bed_no", label: "床位号", value: it.bed_no || "" },
        { name: "guardian_name", label: "家长姓名", value: it.guardian_name || "" },
        { name: "guardian_relation", label: "家长关系", value: it.guardian_relation || "" },
        { name: "guardian_phone", label: "家长电话", value: it.guardian_phone || "" },
        { name: "address", label: "家庭住址", full: true, value: it.address || "" },
        { name: "phone", label: "学生电话", value: it.phone || "" },
        { name: "status", label: "状态", type: "select", value: it.status || "在读",
          options: ["在读", "休学", "毕业", "退学"].map(function (s) { return { v: s, t: s }; }) }
      ],
      tip: "姓名、性别、班级为必填项；学号留空时自动生成。修改班级 / 学号即视为调班。",
      onSubmit: function (v) {
        var body = {
          class_id: v.class_id, student_id: edit ? it.student_id : v.student_id, name: v.name,
          gender: v.gender, major: v.major, grade: v.grade, dorm: v.dorm,
          boarding_type: v.boarding_type, bed_no: v.bed_no,
          guardian_name: v.guardian_name, guardian_relation: v.guardian_relation,
          guardian_phone: v.guardian_phone, address: v.address,
          phone: v.phone, status: v.status
        };
        if (edit) {
          return apiJson("/students/" + encodeURIComponent(it.class_id) + "/" + encodeURIComponent(it.student_id), "PUT", body)
            .then(function () { toast("已保存", "ok"); loadStudents(); loadClasses(); loadDorms(); });
        }
        return apiJson("/students", "POST", body).then(function () {
          toast("学生已添加", "ok"); loadStudents(); loadClasses();
        });
      }
    });
  }

  /* ---------------- 班级管理 ---------------- */
  function loadHeadteacherCandidates() {
    return api("/headteachers/candidates").then(function (j) {
      state.headteachers = j.data || [];
      return state.headteachers;
    }).catch(function () { state.headteachers = []; });
  }

  function headTeacherOptions(cur) {
    var opts = [];
    (state.headteachers || []).forEach(function (h) {
      opts.push({ v: h.userid, t: (h.name || h.userid) + "（" + h.userid + "）" });
    });
    if (cur && !opts.some(function (o) { return o.v === cur; })) {
      opts.push({ v: cur, t: cur + "（当前，未列入班主任名单）" });
    }
    return opts;
  }

  function loadClassMgmt() {
    var tbody = $("classBody");
    tbody.innerHTML = '<tr><td colspan="8" class="loading">加载中…</td></tr>';
    loadHeadteacherCandidates();
    api("/classes").then(function (j) {
      state.classList = j.data || [];
      renderClassRows();
    }).catch(function (e) { tbody.innerHTML = '<tr><td colspan="8" class="empty">加载失败：' + esc(e.message) + '</td></tr>'; });
  }
  function renderClassRows() {
    var tbody = $("classBody");
    var all = state.classList || [];
    if (!all.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty">暂无班级</td></tr>'; return;
    }
    var kw = String(state.classFilter || "").trim().toLowerCase();
    var items = all.filter(function (c) {
      if (!kw) return true;
      return [c.class_id, c.name, c.major].some(function (v) {
        return String(v || "").toLowerCase().indexOf(kw) >= 0;
      });
    });
    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty">没有匹配的班级</td></tr>'; return;
    }
    tbody.innerHTML = items.map(function (c) {
      var head = c.head_teacher_name
        ? esc(c.head_teacher_name) + ' <small class="muted">' + esc(c.head_teacher_userid) + '</small>'
        : '<span class="muted">未指定</span>';
      return '<tr>' +
        '<td class="mono">' + esc(c.class_id) + '</td>' +
        '<td>' + esc(c.name || "") + '</td>' +
        '<td>' + esc(c.grade || "") + '</td>' +
        '<td>' + esc(c.major || "") + '</td>' +
        '<td>' + head + '</td>' +
        '<td class="mono">' + esc(c.student_count || 0) + '</td>' +
        '<td>' + (c.status === "停用"
          ? '<span class="badge danger">停用</span>' : '<span class="badge ok">启用</span>') + '</td>' +
        '<td><div class="row-actions">' +
        '<button class="btn sm" data-class-edit="' + esc(c.class_id) + '">编辑</button>' +
        '<button class="btn sm" data-class-del="' + esc(c.class_id) + '">删除</button>' +
        '</div></td></tr>';
    }).join("");
  }
  function classMajorForm() {
    var source = (state.classList && state.classList.length) ? state.classList : (state.classes || []);
    var opts = source.map(function (c) {
      return { v: c.class_id, t: c.class_id + " " + (c.name || "") + (c.major ? "（" + c.major + "）" : "") };
    });
    if (!opts.length) { toast("暂无班级可设置", "err"); return; }
    openForm({
      title: "批量设置专业",
      wide: true,
      fields: [
        { name: "class_ids", label: "班级", type: "multiselect", size: 8, full: true,
          options: opts, required: true, value: [] },
        { name: "major", label: "专业名称", required: true, placeholder: "如 护理" }
      ],
      tip: "选中的班级将统一设置为该专业；不选班级或专业名称留空均无法提交。",
      onSubmit: function (v) {
        return apiJson("/classes/major", "POST",
          { class_ids: v.class_ids, major: v.major })
          .then(function (j) {
            var d = j.data || {};
            toast("已设置 " + (d.updated || 0) + " 个班级的专业", "ok");
            loadClassMgmt();
          });
      }
    });
  }
  function classForm(it) {
    it = it || {};
    var edit = !!it.class_id;
    openForm({
      title: edit ? "编辑班级：" + it.class_id : "新增班级",
      fields: [
        { name: "class_id", label: "班级编号", required: true, value: it.class_id, readonly: edit, placeholder: "如 2607" },
        { name: "name", label: "班级名称", value: it.name || "", placeholder: "如 2607班" },
        { name: "grade", label: "年级", value: it.grade || "" },
        { name: "major", label: "专业设置", value: it.major || "", placeholder: "如 直播电商服务" },
        { name: "head_teacher_userid", label: "班主任", type: "select",
          value: it.head_teacher_userid || "", options: headTeacherOptions(it.head_teacher_userid || "") },
        { name: "status", label: "状态", type: "select", value: it.status || "active",
          options: [{ v: "active", t: "启用" }, { v: "停用", t: "停用" }] }
      ],
      tip: "班主任只能从「班主任管理」指定的名单中选择；保存后该教师即获得本班班主任权限。",
      onSubmit: function (v) {
        if (edit) {
          return apiJson("/classes/" + encodeURIComponent(it.class_id), "PUT", v)
            .then(function () { toast("已保存", "ok"); loadClassMgmt(); loadClasses(); });
        }
        return apiJson("/classes", "POST", v).then(function () {
          toast("班级已创建", "ok"); loadClassMgmt(); loadClasses();
        });
      }
    });
  }

  /* ---------------- 班主任管理 ---------------- */
  function loadHeadteachers() {
    var tbody = $("htBody");
    tbody.innerHTML = '<tr><td colspan="5" class="loading">加载中…</td></tr>';
    api("/headteachers?q=" + encodeURIComponent(pg.head.q) + "&page=" + pg.head.page + "&size=50")
      .then(function (j) {
        var d = j.data || {}, items = d.items || [];
        $("htBadge").textContent = "共 " + (d.total || 0) + " 人";
        if (!items.length) {
          tbody.innerHTML = '<tr><td colspan="5" class="empty">暂无班主任，请在「教工管理」编辑中勾选「指定为班主任」</td></tr>';
          renderPager($("htPager"), d, function () {});
          return;
        }
        var start = ((d.page || 1) - 1) * (d.size || 50);
        tbody.innerHTML = items.map(function (x, i) {
          return '<tr>' +
            '<td class="mono">' + (start + i + 1) + '</td>' +
            '<td class="mono">' + esc(x.userid) + '</td>' +
            '<td>' + esc(x.name || "") + '</td>' +
            '<td>' + esc(x.class_names || "") + '</td>' +
            '<td class="mono">' + (x.student_count == null ? "" : esc(x.student_count)) + '</td>' +
            '</tr>';
        }).join("");
        renderPager($("htPager"), d, function (np) { pg.head.page = np; loadHeadteachers(); });
      }).catch(function (e) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty">加载失败：' + esc(e.message) + '</td></tr>';
      });
  }

  /* ---------------- 寝室管理 ---------------- */
  function loadDormMgmt() {
    var tbody = $("dormBody");
    tbody.innerHTML = '<tr><td colspan="7" class="loading">加载中…</td></tr>';
    api("/dorms").then(function (j) {
      var items = j.data || [];
      if (!items.length) {
        tbody.innerHTML = '<tr><td colspan="7" class="empty">暂无寝室</td></tr>'; return;
      }
      tbody.innerHTML = items.map(function (d) {
        var cap = d.capacity || 0, occ = d.occupied || 0;
        return '<tr>' +
          '<td>' + esc(d.building || "") + '</td>' +
          '<td class="mono">' + esc(d.room_no) + '</td>' +
          '<td>' + esc(d.gender || "不限") + '</td>' +
          '<td class="mono">' + cap + '</td>' +
          '<td class="mono">' + occ + (cap ? ' / ' + cap : '') + '</td>' +
          '<td>' + (d.status === "停用"
            ? '<span class="badge danger">停用</span>' : '<span class="badge ok">启用</span>') + '</td>' +
          '<td><div class="row-actions">' +
          '<button class="btn sm" data-dorm-edit="' + esc(d.id) + '">编辑</button>' +
          '<button class="btn sm" data-dorm-del="' + esc(d.id) + '">删除</button>' +
          '</div></td></tr>';
      }).join("");
    }).catch(function (e) { tbody.innerHTML = '<tr><td colspan="7" class="empty">加载失败：' + esc(e.message) + '</td></tr>'; });
  }
  function dormForm(it) {
    it = it || {};
    var edit = !!it.id;
    openForm({
      title: edit ? "编辑寝室：" + (it.label || it.id) : "新增寝室",
      fields: [
        { name: "building", label: "楼栋", value: it.building || "", placeholder: "如 1号楼" },
        { name: "room_no", label: "房号", required: true, value: it.room_no || "", placeholder: "如 1401" },
        { name: "gender", label: "类型", type: "select", value: it.gender || "",
          options: [{ v: "", t: "不限" }, { v: "男", t: "男" }, { v: "女", t: "女" }] },
        { name: "capacity", label: "容量", type: "number", value: it.capacity == null ? 6 : it.capacity },
        { name: "status", label: "状态", type: "select", value: it.status || "active",
          options: [{ v: "active", t: "启用" }, { v: "停用", t: "停用" }] }
      ],
      onSubmit: function (v) {
        if (edit) {
          return apiJson("/dorms/" + encodeURIComponent(it.id), "PUT", v)
            .then(function () { toast("已保存", "ok"); loadDormMgmt(); loadDorms(); });
        }
        return apiJson("/dorms", "POST", v).then(function () {
          toast("寝室已创建", "ok"); loadDormMgmt(); loadDorms();
        });
      }
    });
  }

  /* ---------------- 系统 ---------------- */
  function loadSystem() {
    if (state.me) $("curAccount").value = state.me.userid + "（" + (state.me.name || "") + "）";
    $("auditBody").innerHTML = '<tr><td colspan="5" class="loading">加载中…</td></tr>';
    api("/audit?limit=100").then(function (j) {
      var rows = j.data || [];
      $("auditBadge").textContent = rows.length + " 条";
      renderAudit($("auditBody"), rows, 100);
    }).catch(function (e) { $("auditBody").innerHTML = '<tr><td colspan="5" class="empty">加载失败：' + esc(e.message) + '</td></tr>'; });
  }
  function changePassword() {
    var old = $("oldPwd").value, nw = $("newPwd").value, nw2 = $("newPwd2").value;
    if (!old || !nw) { toast("请填写旧密码和新密码", "err"); return; }
    if (nw.length < 6) { toast("新密码至少 6 位", "err"); return; }
    if (nw !== nw2) { toast("两次输入的新密码不一致", "err"); return; }
    apiJson("/password/change", "POST", { old_password: old, new_password: nw }).then(function () {
      toast("密码已修改，请用新密码重新登录", "ok");
      $("oldPwd").value = $("newPwd").value = $("newPwd2").value = "";
      setTimeout(function () { location.href = "/api/v1/logout"; }, 1200);
    }).catch(function (e) { toast(e.message, "err"); });
  }

  /* ---------------- 文件导入 ---------------- */
  function triggerImport(kind) {
    fileKind = kind;
    $("fileInput").value = "";
    $("fileInput").click();
  }
  function handleImport(file) {
    if (!file) return;
    var kind = fileKind;
    var url = kind === "teacher" ? "/accounts/teachers/import" : "/students/import";
    var fd = new FormData();
    fd.append("file", file);
    toast("正在导入…");
    api(url, { method: "POST", body: fd }).then(function (j) {
      var d = j.data || {};
      if (kind === "teacher") {
        toast("导入完成：" + (d.imported != null ? d.imported + " 条" : "成功"), "ok");
        loadTeachers();
      } else {
        toast("导入完成：新增 " + (d.added || 0) + "、更新 " + (d.updated || 0) +
          "、跳过 " + (d.skipped || 0), "ok");
        loadStudents(); loadClasses();
      }
    }).catch(function (e) { toast(e.message || "导入失败", "err"); });
  }

  /* ---------------- 事件委托 ---------------- */
  function currentTeacherRow(userid, cb) {
    var hit = (state.teachers || []).filter(function (x) { return x.userid === userid; })[0];
    if (hit) { cb(hit); return; }
    api("/accounts/teachers?q=" + encodeURIComponent(userid) + "&size=5").then(function (j) {
      var it = (j.data && j.data.items || []).filter(function (x) { return x.userid === userid; })[0];
      cb(it || null);
    });
  }

  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-view]");
    if (t) { switchView(t.getAttribute("data-view")); return; }

    var act = e.target.closest("[data-action]");
    if (act) {
      var a = act.getAttribute("data-action");
      if (a === "change-pwd") { changePassword(); return; }
      if (a === "teacher-add") { teacherForm(null); return; }
      if (a === "teacher-export") { download("/accounts/teachers/export"); return; }
      if (a === "teacher-template") { download("/accounts/teachers/template"); return; }
      if (a === "teacher-import") { triggerImport("teacher"); return; }
      if (a === "student-add") { studentForm(null, classOptions(false), dormOptions(false)); return; }
      if (a === "student-export") { download("/students/export"); return; }
      if (a === "student-template") { download("/students/template"); return; }
      if (a === "student-import") { triggerImport("student"); return; }
      if (a === "student-transfer") { openTransferForm(pickedList()); return; }
      if (a === "class-add") { classForm(null); return; }
      if (a === "class-major") { classMajorForm(); return; }
      if (a === "class-export") { download("/classes/export"); return; }
      if (a === "dorm-add") { dormForm(null); return; }
      if (a === "sa-generate") {
        var cls = pg.sa.class_id;
        openConfirm({
          title: "批量生成学生账号",
          text: (cls ? "为班级 " + cls : "为全校") + "尚无账号的在册学生生成登录账号，默认密码 123456。继续？",
          okText: "生成"
        }).then(function (y) {
          if (!y) return;
          apiJson("/accounts/students/generate", "POST", { class_id: cls }).then(function (j) {
            var d = j.data || {};
            toast("已生成 " + (d.generated || 0) + " 个账号（默认密码 " + (d.password || "123456") + "）", "ok");
            loadStudentAccounts();
          }).catch(function (e) { toast(e.message, "err"); });
        });
        return;
      }
    }

    // 教师行操作
    var te = e.target.closest("[data-teacher-edit]");
    if (te) { currentTeacherRow(te.getAttribute("data-teacher-edit"), function (it) { teacherForm(it); }); return; }
    var tr = e.target.closest("[data-teacher-reset]");
    if (tr) {
      var uid = tr.getAttribute("data-teacher-reset");
      openConfirm({ title: "重置密码", text: "将账号 " + uid + " 的密码重置为默认 123456？", okText: "重置" })
        .then(function (y) {
          if (!y) return;
          apiJson("/accounts/teachers/" + encodeURIComponent(uid) + "/reset-password", "POST", {})
            .then(function (j) {
              openConfirm({ title: "密码已重置", text: "账号 " + uid + " 的新密码为：" + (j.data && j.data.password) + "（请妥善告知）", okText: "我知道了", danger: false });
            }).catch(function (e) { toast(e.message, "err"); });
        });
      return;
    }
    var tt = e.target.closest("[data-teacher-toggle]");
    if (tt) {
      var u2 = tt.getAttribute("data-teacher-toggle"), cur = tt.getAttribute("data-status");
      var next = cur === "停用" ? "本校" : "停用";
      apiJson("/accounts/teachers/" + encodeURIComponent(u2) + "/toggle-status", "POST", { status: next })
        .then(function () { toast("已" + (next === "停用" ? "停用" : "启用"), "ok"); loadTeachers(); })
        .catch(function (e) { toast(e.message, "err"); });
      return;
    }
    var td = e.target.closest("[data-teacher-del]");
    if (td) {
      var u3 = td.getAttribute("data-teacher-del");
      openConfirm({ title: "删除账号", text: "确定删除账号 " + u3 + "？此操作不可撤销。" })
        .then(function (y) {
          if (!y) return;
          api("/accounts/teachers/" + encodeURIComponent(u3), { method: "DELETE" })
            .then(function () { toast("已删除", "ok"); loadTeachers(); })
            .catch(function (e) { toast(e.message, "err"); });
        });
      return;
    }

    // 学生行操作
    var sm = e.target.closest("[data-stu-move]");
    if (sm) {
      openTransferForm([{
        class_id: sm.getAttribute("data-c"),
        student_id: sm.getAttribute("data-s"),
        name: sm.getAttribute("data-n") || ""
      }]);
      return;
    }
    var se = e.target.closest("[data-stu-edit]");
    if (se) {
      var c1 = se.getAttribute("data-c"), s1 = se.getAttribute("data-s");
      api("/students?q=" + encodeURIComponent(s1) + "&class_id=" + encodeURIComponent(c1) + "&size=50")
        .then(function (j) {
          var it = (j.data && j.data.items || []).filter(function (x) { return x.class_id === c1 && x.student_id === s1; })[0];
          if (!it) { toast("未找到学生", "err"); return; }
          Promise.all([loadClasses(), loadDorms()]).then(function () {
            studentForm(it, classOptions(true), dormOptions(true));
          });
        }).catch(function (e) { toast(e.message, "err"); });
      return;
    }
    var sd = e.target.closest("[data-stu-del]");
    if (sd) {
      var c2 = sd.getAttribute("data-c"), s2 = sd.getAttribute("data-s");
      openConfirm({ title: "删除学生", text: "确定删除 " + c2 + " / " + s2 + "？将同时删除其学生账号，且不可撤销。" })
        .then(function (y) {
          if (!y) return;
          api("/students/" + encodeURIComponent(c2) + "/" + encodeURIComponent(s2), { method: "DELETE" })
            .then(function () { toast("已删除", "ok"); loadStudents(); loadDashboard(); })
            .catch(function (e) { toast(e.message, "err"); });
        });
      return;
    }

    // 学生账号行操作
    var sr = e.target.closest("[data-sa-reset]");
    if (sr) {
      var sc = sr.getAttribute("data-c"), ss = sr.getAttribute("data-s");
      openConfirm({ title: "重置密码", text: "将 " + sc + " / " + ss + " 的密码重置为默认 123456？", okText: "重置" })
        .then(function (y) {
          if (!y) return;
          apiJson("/accounts/students/reset-password", "POST", { class_id: sc, student_id: ss })
            .then(function (j) {
              openConfirm({ title: "密码已重置", text: "新密码为：" + (j.data && j.data.password) + "（请妥善告知学生）", okText: "我知道了", danger: false });
            }).catch(function (e) { toast(e.message, "err"); });
        });
      return;
    }
    var st = e.target.closest("[data-sa-toggle]");
    if (st) {
      var cc = st.getAttribute("data-c"), cs = st.getAttribute("data-s"), cst = st.getAttribute("data-st");
      var nst = cst === "disabled" ? "active" : "disabled";
      apiJson("/accounts/students/" + encodeURIComponent(cc) + "/" + encodeURIComponent(cs) + "/toggle-status", "POST", { status: nst })
        .then(function () { toast("已" + (nst === "disabled" ? "停用" : "启用"), "ok"); loadStudentAccounts(); })
        .catch(function (e) { toast(e.message, "err"); });
      return;
    }

    // 班级行操作
    var ce = e.target.closest("[data-class-edit]");
    if (ce) {
      var cid = ce.getAttribute("data-class-edit");
      var it = state.classes.filter(function (x) { return x.class_id === cid; })[0];
      if (it) classForm(it); else loadClasses().then(function () {
        var it2 = state.classes.filter(function (x) { return x.class_id === cid; })[0];
        if (it2) classForm(it2);
      });
      return;
    }
    var cd = e.target.closest("[data-class-del]");
    if (cd) {
      var cid2 = cd.getAttribute("data-class-del");
      openConfirm({ title: "删除班级", text: "确定删除班级 " + cid2 + "？若该班仍有学生将无法删除。" })
        .then(function (y) {
          if (!y) return;
          api("/classes/" + encodeURIComponent(cid2), { method: "DELETE" })
            .then(function () { toast("已删除", "ok"); loadClassMgmt(); loadClasses(); })
            .catch(function (e) { toast(e.message, "err"); });
        });
      return;
    }

    // 寝室行操作
    var de = e.target.closest("[data-dorm-edit]");
    if (de) {
      var did = parseInt(de.getAttribute("data-dorm-edit"), 10);
      var dit = state.dorms.filter(function (x) { return x.id === did; })[0];
      if (dit) dormForm(dit); else loadDorms().then(function () {
        var dit2 = state.dorms.filter(function (x) { return x.id === did; })[0];
        if (dit2) dormForm(dit2);
      });
      return;
    }
    var dd = e.target.closest("[data-dorm-del]");
    if (dd) {
      var did2 = parseInt(dd.getAttribute("data-dorm-del"), 10);
      openConfirm({ title: "删除寝室", text: "确定删除该寝室？若仍有学生入住将无法删除。" })
        .then(function (y) {
          if (!y) return;
          api("/dorms/" + did2, { method: "DELETE" })
            .then(function () { toast("已删除", "ok"); loadDormMgmt(); loadDorms(); })
            .catch(function (e) { toast(e.message, "err"); });
        });
      return;
    }
  });

  // 学生列表勾选（批量转班用）
  document.addEventListener("change", function (e) {
    var p = e.target.closest("[data-stu-pick]");
    if (!p) return;
    var key = p.getAttribute("data-c") + "/" + p.getAttribute("data-s");
    if (p.checked) {
      stuPicked[key] = {
        class_id: p.getAttribute("data-c"),
        student_id: p.getAttribute("data-s"),
        name: p.getAttribute("data-n") || ""
      };
    } else {
      delete stuPicked[key];
    }
  });

  // 筛选 / 搜索输入
  function bindFilter(id, getter, setter, loader) {
    var node = $(id);
    if (!node) return;
    node.addEventListener("input", debounce(function () {
      setter(getter());
      loader();
    }, 320));
    node.addEventListener("change", function () { setter(getter()); loader(); });
  }
  function debounce(fn, ms) { var t; return function () { var a = arguments, x = this; clearTimeout(t); t = setTimeout(function () { fn.apply(x, a); }, ms); }; }

  // 退出
  $("logout").addEventListener("click", function () { location.href = "/api/v1/logout"; });
  $("fileInput").addEventListener("change", function (e) { handleImport(e.target.files[0]); });

  /* ---------------- 启动 ---------------- */
  function init() {
    var d = new Date();
    $("today").textContent = d.getFullYear() + "年" + (d.getMonth() + 1) + "月" + d.getDate() + "日";
    api("/me").then(function (j) {
      state.me = j.data || {};
      $("userName").textContent = state.me.name || state.me.userid || "管理员";
      $("userRole").textContent = state.me.role === "superadmin" ? "超级管理员" : (state.me.role || "管理员");
      $("avatar").textContent = (state.me.name || "管").slice(0, 1);
      $("curAccount").value = (state.me.userid || "") + "（" + (state.me.name || "") + "）";
    }).catch(function () { /* 401 已跳转 */ });

    Promise.all([loadClasses(), loadDorms(), loadHeadteacherCandidates()]).then(function () {
      bindFilter("tSearch", function () { return $("tSearch").value; }, function (v) { pg.teacher.q = v; pg.teacher.page = 1; }, loadTeachers);
      bindFilter("tCategory", function () { return $("tCategory").value; }, function (v) { pg.teacher.category = v; pg.teacher.page = 1; }, loadTeachers);
      bindFilter("sSearch", function () { return $("sSearch").value; }, function (v) { pg.student.q = v; pg.student.page = 1; }, loadStudents);
      bindFilter("sClass", function () { return $("sClass").value; }, function (v) { pg.student.class_id = v; pg.student.page = 1; }, loadStudents);
      bindFilter("saSearch", function () { return $("saSearch").value; }, function (v) { pg.sa.q = v; pg.sa.page = 1; }, loadStudentAccounts);
      bindFilter("saClass", function () { return $("saClass").value; }, function (v) { pg.sa.class_id = v; pg.sa.page = 1; }, loadStudentAccounts);
      bindFilter("htSearch", function () { return $("htSearch").value; }, function (v) { pg.head.q = v; pg.head.page = 1; }, loadHeadteachers);
      // 班级筛选只重渲染本地缓存，不发请求
      var cSearch = $("classSearch");
      if (cSearch) cSearch.addEventListener("input", function () {
        state.classFilter = cSearch.value;
        renderClassRows();
      });
      switchView("home");
    });
  }
  init();
})();
