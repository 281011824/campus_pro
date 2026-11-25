/* 校园巡查 · 教官/寝管前端逻辑（原生 JS，无依赖） */
(function () {
  "use strict";

  var API = "/api/v1/inspector";
  var LOGIN = "/api/v1/login?next=/api/inspector";

  var state = {
    me: null,
    items: { violation: [], appearance: [], sanitation: [] },
    classes: [],
    dorms: [],
    picked: null,
    sanObject: "classroom",
    dormValid: null,
    category: "",
    mine: false,
    records: [],
    summary: null,
    busy: false,
    searchSeq: 0
  };

  var searchTimer = null;
  var toastTimer = null;
  var deniedShown = false;

  /* ---------------- 基础工具 ---------------- */
  function $(id) { return document.getElementById(id); }

  function esc(s) {
    if (s == null) return "";
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c];
    });
  }

  function closest(node, sel) {
    while (node && node.nodeType === 1) {
      if (node.matches ? node.matches(sel) : false) return node;
      node = node.parentNode;
    }
    return null;
  }

  function pad2(n) { return n < 10 ? "0" + n : "" + n; }

  function today() {
    var d = new Date();
    return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
  }

  function signed(n) {
    n = Number(n) || 0;
    return n > 0 ? "+" + n : String(n);
  }

  function fmtTime(ts) {
    if (ts == null || ts === "") return "--:--";
    if (typeof ts === "number") {
      var d = new Date(ts * 1000);
      return pad2(d.getHours()) + ":" + pad2(d.getMinutes());
    }
    var s = String(ts).replace("T", " ");
    var m = s.match(/(\d{1,2}:\d{2})/);
    return m ? m[1] : s;
  }

  /* ---------------- Toast ---------------- */
  function toast(msg, kind) {
    var t = $("toast");
    if (!t) return;
    t.textContent = msg;
    t.className = "toast" + (kind ? " " + kind : "");
    t.style.display = "block";
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.style.display = "none"; }, 2600);
  }

  /* ---------------- 通信 ---------------- */
  function api(path, opts) {
    opts = opts || {};
    opts.credentials = "include";
    if (opts.method && opts.method !== "GET") {
      opts.headers = opts.headers || {};
      if (!opts.headers["Content-Type"]) opts.headers["Content-Type"] = "application/json";
    }
    return fetch(API + path, opts).then(function (r) {
      if (r.status === 401) {
        location.href = LOGIN;
        var e401 = new Error("登录已过期");
        e401.silent = true;
        throw e401;
      }
      if (r.status === 403) {
        showDenied();
        var e403 = new Error("当前账号无巡查权限");
        e403.silent = true;
        throw e403;
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
    }).catch(function (err) {
      if (!err.silent) {
        var msg = err && err.message;
        if (!msg || /Failed to fetch|NetworkError|Load failed|fetch/i.test(msg)) {
          msg = "网络异常，请检查网络后重试";
        }
        toast(msg, "err");
      }
      throw err;
    });
  }

  function postJson(path, body) {
    return api(path, { method: "POST", body: JSON.stringify(body || {}) });
  }

  function showDenied() {
    var box = $("denied");
    if (box) box.hidden = false;
    if (!deniedShown) {
      deniedShown = true;
      toast("当前账号无巡查权限", "err");
    }
  }

  /* ---------------- 确认弹窗 ---------------- */
  function confirmBox(o) {
    o = o || {};
    $("confirmTitle").textContent = o.title || "确认操作";
    $("confirmText").textContent = o.text || "";
    $("confirmOk").textContent = o.okText || "确定";
    var m = $("confirmModal");
    m.hidden = false;
    return new Promise(function (resolve) {
      function done(v) {
        m.hidden = true;
        $("confirmOk").onclick = null;
        $("confirmCancel").onclick = null;
        resolve(v);
      }
      $("confirmOk").onclick = function () { done(true); };
      $("confirmCancel").onclick = function () { done(false); };
    });
  }

  /* ---------------- 渲染：顶部用户 ---------------- */
  function renderMe() {
    var me = state.me || {};
    $("meName").textContent = me.name || "未知用户";
    $("meCat").textContent = me.category || "巡查";
  }

  /* ---------------- 渲染：学生选中条 ---------------- */
  function renderPicked() {
    var p = state.picked;
    var bar = $("picked");
    if (!p) {
      bar.hidden = true;
    } else {
      bar.hidden = false;
      $("pickedName").textContent = p.name + "（" + (p.student_no || "") + "）";
      $("pickedMeta").textContent = (p.class_name ? " · " + p.class_name : "") +
        (p.head_teacher_name ? " · 班主任 " + p.head_teacher_name : "");
    }
    $("searchHint").textContent = p
      ? "已选中学生，违纪、仪容事项点击即记录；点「更换」可切换学生。"
      : "搜索并选中学生后可记录违纪与仪容；不选学生也可记录卫生。";
    syncItemDisabled();
  }

  /* ---------------- 渲染：事项 ---------------- */
  function renderGroup(boxId, list, cat, cls) {
    var box = $(boxId);
    if (!list.length) {
      box.innerHTML = '<p class="empty-tip">暂无可用事项，请刷新页面重试。</p>';
      return;
    }
    var html = "";
    for (var i = 0; i < list.length; i++) {
      var it = list[i];
      html += '<button type="button" class="item-btn ' + cls + '"' +
        ' data-act="record" data-cat="' + cat + '"' +
        ' data-code="' + esc(it.code) + '"' +
        ' data-name="' + esc(it.name) + '"' +
        ' data-points="' + esc(it.points) + '">' +
        '<span class="nm">' + esc(it.name) + '</span>' +
        '<span class="pt">' + signed(it.points) + '</span>' +
        '</button>';
    }
    box.innerHTML = html;
  }

  function renderItems() {
    renderGroup("violationItems", state.items.violation, "violation", "danger");
    renderGroup("appearanceItems", state.items.appearance, "appearance", "warn");
    syncItemDisabled();
    updateSanButtons();
  }

  function syncItemDisabled() {
    var need = !state.picked;
    var btns = document.querySelectorAll('#violationItems .item-btn, #appearanceItems .item-btn');
    for (var i = 0; i < btns.length; i++) btns[i].disabled = need;
  }

  /* ---------------- 渲染：卫生 ---------------- */
  function normRoom(v) {
    return String(v == null ? "" : v).replace(/\s+/g, "").toUpperCase();
  }

  // 按输入内容在已有寝室中逐字匹配（房号或展示名包含关键字）
  function matchDorms(q) {
    var key = normRoom(q);
    var out = [];
    if (!key) return out;
    for (var i = 0; i < state.dorms.length; i++) {
      var it = state.dorms[i];
      var room = normRoom(it.room_no);
      var label = normRoom(it.label);
      if (room.indexOf(key) >= 0 || label.indexOf(key) >= 0) out.push(it);
      if (out.length >= 20) break;
    }
    return out;
  }

  // 精确命中已有寝室（房号或展示名完全一致才算有效）
  function findDormExact(text) {
    var key = normRoom(text);
    if (!key) return null;
    for (var i = 0; i < state.dorms.length; i++) {
      var it = state.dorms[i];
      if (normRoom(it.room_no) === key || normRoom(it.label) === key) return it;
    }
    return null;
  }

  function dormName(it) {
    return String(it.label || it.room_no || "").trim() || String(it.room_no || "");
  }

  function renderSan() {
    var segs = document.querySelectorAll("#sanObjects .seg-btn");
    for (var i = 0; i < segs.length; i++) {
      var on = segs[i].getAttribute("data-obj") === state.sanObject;
      segs[i].className = "seg-btn" + (on ? " on" : "");
    }

    var isDorm = state.sanObject === "dorm";
    var sel = $("sanTarget");
    var picker = $("dormPicker");
    var inp = $("sanTargetInput");
    $("sanTargetLabel").textContent = isDorm ? "寝室号（输入查找）" : "选择班级";
    $("sanTargetLabel").setAttribute("for", isDorm ? "sanTargetInput" : "sanTarget");

    state.dormValid = null;
    hideSanSuggest();
    setSanHint("");

    if (isDorm) {
      sel.classList.add("hidden");
      sel.disabled = true;
      picker.classList.remove("hidden");
      inp.classList.remove("valid", "invalid");
      inp.disabled = false;
      inp.value = "";
    } else {
      picker.classList.add("hidden");
      inp.disabled = true;
      inp.value = "";
      sel.classList.remove("hidden");
      sel.disabled = false;
      var list = state.classes;
      var opts = '<option value="">请选择班级</option>';
      for (var k = 0; k < list.length; k++) {
        opts += '<option value="' + esc(list[k].class_id) + '">' + esc(list[k].name) + "</option>";
      }
      sel.innerHTML = opts;
      sel.value = "";
    }
    updateSanButtons();
  }

  function setSanHint(text, kind) {
    var el = $("sanHint");
    if (!text) { el.hidden = true; el.textContent = ""; el.className = "field-hint"; return; }
    el.hidden = false;
    el.textContent = text;
    el.className = "field-hint" + (kind ? " " + kind : "");
  }

  function hideSanSuggest() {
    var box = $("sanSuggest");
    if (box) { box.hidden = true; box.innerHTML = ""; }
  }

  // 输入即匹配：展示候选、校验有效性、联动按钮
  function onDormInput() {
    var inp = $("sanTargetInput");
    var text = String(inp.value || "").trim();
    var exact = findDormExact(text);
    state.dormValid = exact;
    inp.classList.remove("valid", "invalid");

    if (!text) {
      hideSanSuggest();
      setSanHint("");
      updateSanButtons();
      return;
    }

    if (exact) {
      hideSanSuggest();
      inp.classList.add("valid");
      var extra = exact.occupied ? "，已住 " + exact.occupied + " 人" : "";
      setSanHint("已匹配寝室：" + dormName(exact) + extra, "ok");
      updateSanButtons();
      return;
    }

    inp.classList.add("invalid");
    setSanHint("寝室号不存在，请从下面的匹配结果中选择", "err");

    var hits = matchDorms(text);
    var box = $("sanSuggest");
    if (!hits.length) {
      // 无任何匹配时只保留红色提示，不再重复弹一块空列表
      hideSanSuggest();
    } else {
      box.hidden = false;
      box.innerHTML = hits.map(function (it) {
        var meta = [];
        if (it.building) meta.push(it.building);
        if (it.occupied) meta.push("已住 " + it.occupied + " 人");
        return '<button type="button" class="suggest-item" data-act="san-pick" data-room="' +
          esc(it.room_no || dormName(it)) + '">' +
          '<span class="s-room">' + esc(dormName(it)) + "</span>" +
          '<span class="s-meta">' + esc(meta.join(" · ")) + "</span></button>";
      }).join("");
    }
    updateSanButtons();
  }

  function applyDormPick(room) {
    var inp = $("sanTargetInput");
    inp.value = room || "";
    onDormInput();
    inp.focus();
  }

  function pickSan(points) {
    var arr = state.items.sanitation;
    for (var i = 0; i < arr.length; i++) {
      if (arr[i].object === state.sanObject && Number(arr[i].points) === points) return arr[i];
    }
    return null;
  }

  function updateSanButtons() {
    if (state.busy) return;
    var hasTarget;
    if (state.sanObject === "dorm") {
      // 寝室：只有输入的寝室号精确命中已有寝室才解禁
      hasTarget = !!state.dormValid;
    } else {
      var sel = $("sanTarget");
      hasTarget = !!(sel && sel.value);
    }
    var good = pickSan(1);
    var bad = pickSan(-1);

    var gb = $("sanGood");
    var bb = $("sanBad");
    gb.disabled = !good || !hasTarget;
    bb.disabled = !bad || !hasTarget;
    gb.setAttribute("data-code", good ? good.code : "");
    gb.setAttribute("data-name", good ? good.name : "优");
    bb.setAttribute("data-code", bad ? bad.code : "");
    bb.setAttribute("data-name", bad ? bad.name : "差");
  }

  /* ---------------- 渲染：概览 / 记录 ---------------- */
  function countText(v) {
    return (v == null || v === "") ? "—" : String(v);
  }

  function countLine(label, v) {
    return label + " " + ((v == null || v === "") ? "—" : v + " 条");
  }

  function renderSummary() {
    var s = state.summary || {};
    var pts = Number(s.total_points);
    if (s.total_points == null || isNaN(pts)) pts = null;

    $("sumCount").textContent = countText(s.total_count);
    var pv = $("sumPoints");
    pv.textContent = pts == null ? "—" : signed(pts);
    pv.className = "ov-v" + (pts > 0 ? " pos" : pts < 0 ? " neg" : "");

    $("sumSub").textContent = countLine("违纪", s.violation_count) +
      " · " + countLine("仪容", s.appearance_count) +
      " · " + countLine("卫生", s.sanitation_count);
  }

  function renderRecords() {
    var list = state.records || [];
    $("recCount").textContent = list.length + " 条";

    var box = $("recList");
    if (!list.length) {
      box.innerHTML = '<p class="empty-tip">' +
        (state.category || state.mine ? "当前筛选条件下暂无记录。" : "今日暂无记录，选中事项点击即可记录。") +
        "</p>";
      return;
    }

    var html = "";
    for (var i = 0; i < list.length; i++) {
      var r = list[i];
      var st = String(r.status || "").toLowerCase();
      var voided = st.indexOf("void") >= 0;
      var pts = Number(r.points) || 0;

      var meta = [];
      if (r.target_label) meta.push(r.target_label);
      if (r.student_name) {
        meta.push(r.student_name + (r.student_no ? "（" + r.student_no + "）" : ""));
      }
      if (r.operator) {
        meta.push((r.operator_category ? r.operator_category + " " : "") + r.operator);
      }

      html += '<div class="rec' + (voided ? " voided" : "") + '">' +
        '<div class="rec-line">' +
          '<span class="rec-time">' + esc(fmtTime(r.ts)) + '</span>' +
          '<span class="rec-item">' + esc(r.item_name || "未命名事项") + '</span>' +
          '<span class="rec-pts ' + (pts > 0 ? "pos" : pts < 0 ? "neg" : "") + '">' +
            signed(pts) + '</span>' +
        '</div>' +
        '<div class="rec-meta">' + esc(meta.join(" · ")) + '</div>' +
        '<div class="rec-foot">' +
          '<span class="tag ' + (voided ? "muted" : "ok") + '">' +
            (voided ? "已撤回" : "有效") + '</span>' +
          (!voided && r.can_void
            ? '<button type="button" class="btn ghost sm" data-act="void"' +
              ' data-id="' + esc(r.id) + '" data-name="' + esc(r.item_name || "") + '">撤回</button>'
            : "") +
        '</div>' +
      '</div>';
    }
    box.innerHTML = html;
  }

  function refreshToday() {
    var d = today();
    var url = "/records?date=" + encodeURIComponent(d) + "&limit=50";
    if (state.category) url += "&category=" + encodeURIComponent(state.category);
    if (state.mine) url += "&mine=1";

    return Promise.all([
      api(url),
      api("/summary?date=" + encodeURIComponent(d))
    ]).then(function (res) {
      state.records = ((res[0] && res[0].data) || {}).items || [];
      state.summary = (res[1] && res[1].data) || null;
      renderRecords();
      renderSummary();
    }).catch(function () {
      $("recList").innerHTML = '<p class="empty-tip">记录加载失败，请稍后重试。</p>';
    });
  }

  /* ---------------- 学生搜索 ---------------- */
  function hideResults() {
    var box = $("searchResults");
    box.hidden = true;
  }

  function renderResults(items) {
    var box = $("searchResults");
    box.hidden = false;
    if (!items.length) {
      box.innerHTML = '<p class="res-empty">未找到匹配的学生，请检查姓名或学号。</p>';
      return;
    }
    var html = "";
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      var sid = (it.student_id != null && it.student_id !== "") ? it.student_id : it.student_no;
      html += '<button type="button" class="res-item" data-act="pick"' +
        ' data-sid="' + esc(sid) + '"' +
        ' data-sno="' + esc(it.student_no) + '"' +
        ' data-name="' + esc(it.name) + '"' +
        ' data-cid="' + esc(it.class_id) + '"' +
        ' data-cname="' + esc(it.class_name) + '"' +
        ' data-ht="' + esc(it.head_teacher_name || "") + '">' +
        '<span class="res-name">' + esc(it.name) + '</span>' +
        '<span class="res-meta">' + esc(it.student_no) +
          (it.class_name ? " · " + esc(it.class_name) : "") +
          (it.head_teacher_name ? " · 班主任 " + esc(it.head_teacher_name) : "") +
        '</span>' +
        '</button>';
    }
    box.innerHTML = html;
  }

  function doSearch(q) {
    var seq = ++state.searchSeq;
    var box = $("searchResults");
    box.hidden = false;
    box.innerHTML = '<p class="res-empty">搜索中…</p>';
    api("/students/search?q=" + encodeURIComponent(q)).then(function (j) {
      if (seq !== state.searchSeq) return;
      renderResults(((j && j.data) || {}).items || []);
    }).catch(function () {
      if (seq !== state.searchSeq) return;
      box.hidden = false;
      box.innerHTML = '<p class="res-empty">搜索失败，请检查网络后重试。</p>';
    });
  }

  function onSearchInput() {
    var q = ($("q").value || "").replace(/^\s+|\s+$/g, "");
    if (searchTimer) clearTimeout(searchTimer);
    if (!q) {
      state.searchSeq++;
      hideResults();
      return;
    }
    searchTimer = setTimeout(function () { doSearch(q); }, 250);
  }

  function pickStudent(btn) {
    state.picked = {
      student_id: btn.getAttribute("data-sid"),
      student_no: btn.getAttribute("data-sno") || "",
      name: btn.getAttribute("data-name") || "",
      class_id: btn.getAttribute("data-cid"),
      class_name: btn.getAttribute("data-cname") || "",
      head_teacher_name: btn.getAttribute("data-ht") || ""
    };
    $("q").value = "";
    hideResults();
    renderPicked();
    toast("已选择：" + state.picked.name, "ok");
  }

  /* ---------------- 提交 ---------------- */
  function setBusy(b) {
    state.busy = b;
    if (b) {
      var nodes = document.querySelectorAll('[data-act="record"], .san-btn');
      for (var i = 0; i < nodes.length; i++) nodes[i].disabled = true;
    } else {
      syncItemDisabled();
      updateSanButtons();
    }
  }

  function submitItem(cat, code, points, name) {
    if (state.busy) return;
    if (!code) {
      toast("该事项暂不可用，请刷新页面重试", "err");
      return;
    }

    var url;
    var payload = { item_code: code };

    if (cat === "sanitation") {
      if (state.sanObject === "dorm") {
        // 必须精确命中已有寝室才允许提交
        var matched = state.dormValid;
        if (!matched) {
          toast("寝室号无效，请输入并选择已有寝室", "err");
          return;
        }
        url = "/records/dorm";
        payload.dorm_label = matched.room_no || dormName(matched);
        if (matched.id != null) { payload.dorm_id = matched.id; }
      } else {
        var sel = $("sanTarget");
        var target = sel ? sel.value : "";
        if (!target) { toast("请先选择班级", "err"); return; }
        url = "/records/class";
        payload.class_id = target;
      }
    } else {
      if (!state.picked) {
        toast("请先选择学生", "err");
        return;
      }
      url = "/records";
      payload.class_id = state.picked.class_id;
      payload.student_id = state.picked.student_id;
    }

    var noteInput = $("noteInput");
    var note = noteInput ? String(noteInput.value || "").replace(/^\s+|\s+$/g, "") : "";
    if (note) payload.note = note;

    setBusy(true);
    postJson(url, payload).then(function () {
      toast("已记录：" + (name || "事项") + " " + signed(points), "ok");
      if (noteInput) noteInput.value = "";
      refreshToday();
    }).catch(function () {}).then(function () {
      setBusy(false);
    });
  }

  function voidRecord(id, name) {
    if (!id) return;
    confirmBox({
      title: "撤回记录",
      text: "确认撤回「" + (name || "该记录") + "」？撤回后分数回退，且不可恢复。",
      okText: "确认撤回"
    }).then(function (ok) {
      if (!ok) return;
      postJson("/records/" + encodeURIComponent(id) + "/void", { reason: "本人撤回" })
        .then(function () {
          toast("已撤回：" + (name || "记录"), "ok");
          refreshToday();
        }).catch(function () {});
    });
  }

  /* ---------------- 事件 ---------------- */
  function syncCatTabs() {
    var btns = document.querySelectorAll("#catFilter .seg-btn");
    for (var i = 0; i < btns.length; i++) {
      var on = (btns[i].getAttribute("data-cat") || "") === state.category;
      btns[i].className = "seg-btn" + (on ? " on" : "");
    }
  }

  function toggleNote() {
    var field = $("noteField");
    field.hidden = !field.hidden;
    $("noteToggle").textContent = field.hidden ? "加备注" : "收起备注";
    if (!field.hidden) $("noteInput").focus();
  }

  function onClick(ev) {
    var node = closest(ev.target, "[data-act]");
    if (!node) {
      if (!closest(ev.target, "#searchResults") && ev.target !== $("q")) hideResults();
      if (!closest(ev.target, "#dormPicker")) hideSanSuggest();
      return;
    }
    var act = node.getAttribute("data-act");
    if (act !== "pick") hideResults();

    if (act === "record") {
      submitItem(
        node.getAttribute("data-cat"),
        node.getAttribute("data-code"),
        Number(node.getAttribute("data-points")),
        node.getAttribute("data-name")
      );
      return;
    }

    if (act === "san-submit") {
      submitItem(
        "sanitation",
        node.getAttribute("data-code"),
        Number(node.getAttribute("data-pts")),
        node.getAttribute("data-name")
      );
      return;
    }

    if (act === "san-object") {
      var obj = node.getAttribute("data-obj");
      if (obj === state.sanObject) return;
      state.sanObject = obj;
      renderSan();
      return;
    }

    if (act === "san-pick") {
      applyDormPick(node.getAttribute("data-room") || "");
      return;
    }

    if (act === "pick") {
      pickStudent(node);
      return;
    }

    if (act === "change-student") {
      $("q").value = "";
      hideResults();
      if ($("q").scrollIntoView) $("q").scrollIntoView({ behavior: "smooth", block: "center" });
      $("q").focus();
      return;
    }

    if (act === "clear-student") {
      state.picked = null;
      renderPicked();
      return;
    }

    if (act === "toggle-note") {
      toggleNote();
      return;
    }

    if (act === "cat") {
      state.category = node.getAttribute("data-cat") || "";
      syncCatTabs();
      refreshToday();
      return;
    }

    if (act === "void") {
      voidRecord(node.getAttribute("data-id"), node.getAttribute("data-name"));
      return;
    }
  }

  function bind() {
    $("q").addEventListener("input", onSearchInput);
    $("q").addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.keyCode === 13) {
        ev.preventDefault();
        if (searchTimer) clearTimeout(searchTimer);
        var q = ($("q").value || "").replace(/^\s+|\s+$/g, "");
        if (q) doSearch(q);
      }
    });
    $("sanTarget").addEventListener("change", updateSanButtons);
    $("sanTargetInput").addEventListener("input", onDormInput);
    $("sanTargetInput").addEventListener("focus", onDormInput);
    $("sanTargetInput").addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.keyCode === 13) {
        ev.preventDefault();
        // 回车时若已有唯一匹配候选，直接填入
        var hits = matchDorms($("sanTargetInput").value);
        if (!state.dormValid && hits.length === 1) applyDormPick(hits[0].room_no || dormName(hits[0]));
      }
    });
    $("mineFilter").addEventListener("change", function () {
      state.mine = this.checked;
      refreshToday();
    });
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" || ev.keyCode === 27) {
        if (!$("confirmModal").hidden) {
          $("confirmCancel").click();
        } else {
          hideResults();
        }
      }
    });
  }

  /* ---------------- 启动 ---------------- */
  function init() {
    bind();
    renderPicked();

    Promise.all([
      api("/me").catch(function () { return null; }),
      api("/items").catch(function () { return null; }),
      api("/classes").catch(function () { return null; }),
      api("/dorms").catch(function () { return null; })
    ]).then(function (res) {
      state.me = (res[0] && res[0].data) || {};
      renderMe();

      var items = (res[1] && res[1].data) || {};
      state.items.violation = items.violation || [];
      state.items.appearance = items.appearance || [];
      state.items.sanitation = items.sanitation || [];

      state.classes = ((res[2] && res[2].data) || {}).items || [];
      state.dorms = ((res[3] && res[3].data) || {}).items || [];

      renderItems();
      renderSan();
    });

    refreshToday();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
