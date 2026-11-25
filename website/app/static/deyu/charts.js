/* 政教处 · 德育统计图表组件库（原生 JS + SVG，零依赖）
 *
 * 与 /api/v1/deyu/stats 返回结构直接对齐：
 *   totals / daily / classes / criteria_breakdown / focus
 *
 * 用法：
 *   const chart = DeyuCharts.trend(el, data.daily, { height: 260 });
 *   chart.update(next.daily);   // 筛选条件变化时原地刷新
 *   chart.destroy();            // 视图卸载时调用
 *
 * 约定：
 * - 配色全部读取政务风 CSS 变量（--ok/--danger/--gold/--red…），带同色回退；
 * - 空数据统一渲染空态；所有文本经 textContent/转义，杜绝 XSS；
 * - 仅做统计与关注标注，不输出任何名次（区间只给标签）。
 */
(function (global) {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var PALETTE = {
    positive: "var(--ok,#2E7D5B)",
    negative: "var(--danger,#B03A2E)",
    net: "var(--gold,#C9A84C)",
    ink: "var(--ink,#1E1C19)",
    sub: "var(--sub,#6E675C)",
    muted: "var(--muted,#9A9386)",
    line: "var(--line,#E7E1D5)",
    lineSoft: "var(--line-soft,#F0EBE1)",
    red: "var(--red,#4A0C0C)",
    goldSoft: "var(--gold-soft,#F1E7CB)",
    dangerBg: "var(--danger-bg,#FBEAE8)",
    okBg: "var(--ok-bg,#EAF5EF)",
    warnBg: "var(--warn-bg,#FBF3DF)"
  };

  /* ---------------- 基础工具 ---------------- */

  function clear(el) { while (el && el.firstChild) el.removeChild(el.firstChild); }

  function h(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function s(tag, attrs, text) {
    var node = document.createElementNS(NS, tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        if (attrs[k] !== undefined && attrs[k] !== null) node.setAttribute(k, attrs[k]);
      });
    }
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function num(v) { var n = Number(v); return isFinite(n) ? n : 0; }

  function signed(v) { var n = num(v); return (n > 0 ? "+" : "") + n; }

  function shortDate(iso, compact) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
    if (!m) { return String(iso || ""); }
    var d = Number(m[3]);
    if (compact) { return d; }
    return Number(m[2]) + "-" + d;
  }

  function empty(el, msg, action) {
    clear(el);
    var box = h("div", "dc-empty");
    box.appendChild(h("span", null, msg || "该周期暂无数据"));
    if (action && action.text && action.onClick) {
      var btn = h("button", "dc-empty-action", action.text);
      btn.type = "button";
      btn.addEventListener("click", function () { action.onClick(); });
      box.appendChild(btn);
    }
    el.appendChild(box);
  }

  function mount(el, cls) {
    clear(el);
    var root = h("div", "dc " + (cls || ""));
    el.appendChild(root);
    return root;
  }

  function makeChart(el, root, render, opts) {
    var current = opts || {};
    return {
      el: root,
      // 筛选切换时整体替换选项，空态提示与按钮才能随周期变化
      update: function (data, nextOpts) {
        if (nextOpts) current = nextOpts;
        clear(root);
        render(root, data || [], current);
      },
      destroy: function () { if (root.parentNode) root.parentNode.removeChild(root); }
    };
  }

  /* ---------------- KPI 卡片组 ---------------- */
  /* totals: {confirmed,pending,positive_points,negative_points,net,students,classes} */
  function kpis(el, totals, opts) {
    var root = mount(el, "dc-kpis");
    function render(node, t, o) {
      o = o || {};
      t = t || {};
      var items = o.items || [
        { key: "confirmed", label: "已确认事件", unit: "条", tone: "ink" },
        { key: "pending", label: "待复核", unit: "条", tone: "warn" },
        { key: "positive_points", label: "加分合计", unit: "分", tone: "ok", sign: true },
        { key: "negative_points", label: "扣分合计", unit: "分", tone: "danger" },
        { key: "net", label: "净分", unit: "分", tone: "gold", sign: true }
      ];
      items.forEach(function (it) {
        var card = h("div", "dc-kpi dc-tone-" + it.tone);
        card.appendChild(h("div", "dc-kpi-label", it.label));
        var val = h("div", "dc-kpi-value");
        val.appendChild(h("b", null, it.sign ? signed(t[it.key]) : num(t[it.key])));
        val.appendChild(h("small", null, it.unit));
        card.appendChild(val);
        if (it.key === "confirmed" && (t.students || t.classes)) {
          card.appendChild(h("div", "dc-kpi-foot",
            "覆盖 " + num(t.classes) + " 个班 / " + num(t.students) + " 名学生"));
        }
        node.appendChild(card);
      });
    }
    render(root, totals, opts);
    return makeChart(el, root, render, opts);
  }

  /* ---------------- 逐日趋势：加分/扣分柱 + 净分折线 ---------------- */
  /* daily: [{date,positive,negative,net,count}] */
  function trend(el, daily, opts) {
    var root = mount(el, "dc-trend");
    function render(node, rows, o) {
      o = o || {};
      // 让 SVG viewBox 按数据量自适应变宽，容器 overflow-x:auto 让它可以横向滚动
      var W = o.width || Math.max(780, (rows.length || 7) * 36 + 120), H = num(o.height) || 260;
      rows = (rows || []).filter(function (r) { return r && r.date; });
      var has = rows.some(function (r) {
        return num(r.positive) || num(r.negative) || num(r.count);
      });
      if (!has) {
        empty(node, o.emptyText || "该周期暂无已确认事件，趋势图待数据", o.emptyAction);
        return;
      }

      var padL = 40, padR = 14, padT = 18, padB = 30;
      var iw = W - padL - padR, ih = H - padT - padB;
      var maxPos = Math.max(1, Math.max.apply(null, rows.map(function (r) { return num(r.positive); })));
      var maxNeg = Math.max(1, Math.max.apply(null, rows.map(function (r) { return Math.abs(num(r.negative)); })));
      var maxNet = Math.max(1, Math.max.apply(null, rows.map(function (r) { return Math.abs(num(r.net)); })));
      var up = Math.max(maxPos, maxNet), down = Math.max(maxNeg, maxNet);
      var zeroY = padT + ih * (up / (up + down));      // 零线位置（上下非对称）
      var step = iw / rows.length;
      var bw = Math.min(16, step * 0.32);

      // compact=true 横坐标只显示日号（弹窗标题含周期范围，不再重复月份）
      var compact = o.compact !== false;
      var total = rows.length;
      // 稀疏策略：点越多越稀；最少 8 条，最多 ceil(n/6)
      var skip = Math.max(1, Math.ceil(total / 8));

      var svg = s("svg", { viewBox: "0 0 " + W + " " + H, role: "img",
        "aria-label": "逐日加分、扣分与净分趋势图" });

      // 网格 + 刻度（上正下负，共用零线）
      [1, 0.5, 0, -0.5, -1].forEach(function (f) {
        var y = f >= 0 ? zeroY - f * (zeroY - padT) : zeroY + (-f) * (H - padB - zeroY);
        svg.appendChild(s("line", { x1: padL, x2: W - padR, y1: y, y2: y,
          stroke: f === 0 ? PALETTE.line : PALETTE.lineSoft,
          "stroke-width": f === 0 ? 1.2 : 1 }));
        svg.appendChild(s("text", { x: padL - 6, y: y + 3, "text-anchor": "end",
          "class": "dc-axis" }, Math.round(f >= 0 ? f * up : f * down)));
      });

      var pts = [];
      rows.forEach(function (r, i) {
        var cx = padL + step * i + step / 2;
        var pos = num(r.positive), neg = num(r.negative), net = num(r.net);
        var ph = pos ? (pos / up) * (zeroY - padT) : 0;
        var nh = neg ? (Math.abs(neg) / down) * (H - padB - zeroY) : 0;
        if (ph > 0) {
          var rp = s("rect", { x: cx - bw - 2, y: zeroY - ph, width: bw, height: ph,
            rx: 2, fill: PALETTE.positive });
          rp.appendChild(s("title", null, r.date + " 加分 +" + pos));
          svg.appendChild(rp);
        }
        if (nh > 0) {
          var rn = s("rect", { x: cx + 2, y: zeroY, width: bw, height: nh,
            rx: 2, fill: PALETTE.negative });
          rn.appendChild(s("title", null, r.date + " 扣分 " + neg));
          svg.appendChild(rn);
        }
        var ny = net >= 0 ? zeroY - (net / up) * (zeroY - padT)
                          : zeroY + (Math.abs(net) / down) * (H - padB - zeroY);
        pts.push([cx, ny, net, r.date]);
        if (i === 0 || i === total - 1 || i % skip === 0) {
          svg.appendChild(s("text", { x: cx, y: H - 10, "text-anchor": "middle",
            "class": "dc-axis" }, shortDate(r.date, compact)));
        }
      });

      var path = pts.map(function (p, i) {
        return (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1);
      }).join(" ");
      svg.appendChild(s("path", { d: path, fill: "none", stroke: PALETTE.net,
        "stroke-width": 2, "stroke-linejoin": "round" }));
      pts.forEach(function (p) {
        var dot = s("circle", { cx: p[0], cy: p[1], r: 3.2, fill: "#fff",
          stroke: PALETTE.net, "stroke-width": 2 });
        dot.appendChild(s("title", null, p[3] + " 净分 " + signed(p[2])));
        svg.appendChild(dot);
      });
      node.appendChild(svg);

      var legend = h("div", "dc-legend");
      [["加分", PALETTE.positive], ["扣分", PALETTE.negative], ["净分", PALETTE.net]]
        .forEach(function (pair) {
          var item = h("span", "dc-legend-item");
          item.appendChild(h("i", null));
          item.firstChild.style.background = pair[1];
          item.appendChild(h("span", null, pair[0]));
          legend.appendChild(item);
        });
      node.appendChild(legend);
    }
    render(root, daily, opts);
    return makeChart(el, root, render, opts);
  }

  /* ---------------- 班级对比：横向正负条形 + 区间标签（无排名） ---------------- */
  /* classes: [{class_id,name,grade,student_count,positive,negative,net,band}] */
  function classBars(el, classes, opts) {
    var root = mount(el, "dc-bars");
    function render(node, rows, o) {
      o = o || {};
      rows = (rows || []).filter(function (r) { return r && (r.name || r.class_id); });
      if (!rows.length) { empty(node, "该周期暂无班级统计数据", o.emptyAction); return; }
      var max = Math.max(1, Math.max.apply(null, rows.map(function (r) {
        return Math.abs(num(r.net));
      })));
      rows.forEach(function (r) {
        var net = num(r.net);
        var row = h("div", "dc-bar-row" + (o.onSelect ? " dc-clickable" : ""));
        row.appendChild(h("div", "dc-bar-name", r.name || r.class_id));
        var track = h("div", "dc-bar-track");
        track.appendChild(h("i", "dc-bar-zero"));
        var fill = h("b", "dc-bar-fill " + (net >= 0 ? "is-pos" : "is-neg"));
        var pct = Math.max(2, Math.abs(net) / max * 50);
        fill.style.width = pct + "%";
        if (net >= 0) fill.style.left = "50%";
        else fill.style.left = (50 - pct) + "%";
        fill.title = (r.name || r.class_id) + " 净分 " + signed(net) +
          "（加分 " + signed(r.positive) + " / 扣分 " + num(r.negative) + "）";
        track.appendChild(fill);
        row.appendChild(track);
        row.appendChild(h("div", "dc-bar-num " + (net < 0 ? "is-neg" : "is-pos"), signed(net)));
        if (r.band) row.appendChild(h("span", "dc-band", r.band));   // 区间标签，不是名次
        if (o.onSelect) {
          row.setAttribute("tabindex", "0");
          row.setAttribute("role", "button");
          row.addEventListener("click", function () { o.onSelect(r.class_id, r); });
          row.addEventListener("keydown", function (ev) {
            if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); o.onSelect(r.class_id, r); }
          });
        }
        node.appendChild(row);
      });
      node.appendChild(h("div", "dc-note",
        "条形为周期净分（加分−扣分）；区间为管理标签，不作排名。"));
    }
    render(root, classes, opts);
    return makeChart(el, root, render, opts);
  }

  /* ---------------- 指标构成：掌声鼓励 / 有待改善 双栏 ---------------- */
  /* criteria_breakdown: [{criteria_id,category,direction,points,count}] */
  function criteriaMix(el, breakdown, opts) {
    var root = mount(el, "dc-mix");
    function render(node, rows, o) {
      o = o || {};
      rows = rows || [];
      var groups = [
        { key: "praise", title: "掌声鼓励", cls: "is-pos" },
        { key: "improve", title: "有待改善", cls: "is-neg" }
      ];
      var any = rows.some(function (r) { return num(r.count) > 0; });
      if (!any) {
        empty(node, o.emptyText || "该周期暂无指标明细", o.emptyAction);
        return;
      }
      var max = Math.max(1, Math.max.apply(null, rows.map(function (r) {
        return Math.abs(num(r.points));
      })));
      groups.forEach(function (g) {
        var col = h("div", "dc-mix-col");
        col.appendChild(h("h3", "dc-mix-title " + g.cls, g.title));
        var list = rows.filter(function (r) { return r.direction === g.key; });
        if (!list.length) {
          col.appendChild(h("div", "dc-empty", "暂无记录"));
        } else {
          list.forEach(function (r) {
            var item = h("div", "dc-mix-row");
            var head = h("div", "dc-mix-head");
            head.appendChild(h("span", "dc-mix-name",
              (r.category || "未分类") + (r.criteria_id ? "" : "（自定义）")));
            head.appendChild(h("span", "dc-mix-val " + g.cls,
              signed(r.points) + " 分 / " + num(r.count) + " 次"));
            item.appendChild(head);
            var track = h("div", "dc-mix-track");
            var fill = h("b", g.cls);
            fill.style.width = Math.max(3, Math.abs(num(r.points)) / max * 100) + "%";
            track.appendChild(fill);
            item.appendChild(track);
            col.appendChild(item);
          });
        }
        node.appendChild(col);
      });
    }
    render(root, breakdown, opts);
    return makeChart(el, root, render, opts);
  }

  /* ---------------- 重点识别：学生/班级关注标注列表 ---------------- */
  /* focus: [{type,id,name,class_id,class_name,reasons[],score}] */
  function focusList(el, focus, opts) {
    var root = mount(el, "dc-focus");
    function render(node, rows, o) {
      o = o || {};
      rows = rows || [];
      if (!rows.length) {
        empty(node, "本周期未命中重点识别规则，保持常规关注。");
        return;
      }
      rows.forEach(function (f) {
        var isClass = f.type === "class";
        var card = h("div", "dc-focus-card " + (isClass ? "is-class" : "is-student"));
        var head = h("div", "dc-focus-head");
        head.appendChild(h("span", "dc-tag " + (isClass ? "dc-tag-class" : "dc-tag-student"),
          isClass ? "班级" : "学生"));
        head.appendChild(h("b", "dc-focus-name", f.name || f.id));
        head.appendChild(h("span", "dc-focus-cls", f.class_name || f.class_id || ""));
        head.appendChild(h("span", "dc-focus-score " + (num(f.score) < 0 ? "is-neg" : "is-pos"),
          signed(f.score)));
        card.appendChild(head);
        var ul = h("ul", "dc-focus-reasons");
        (f.reasons || []).forEach(function (r) { ul.appendChild(h("li", null, r)); });
        card.appendChild(ul);
        if (o.onOpen) {
          var btn = h("button", "dc-focus-btn", "查看明细");
          btn.type = "button";
          btn.addEventListener("click", function () { o.onOpen(f); });
          card.appendChild(btn);
        }
        node.appendChild(card);
      });
      node.appendChild(h("div", "dc-note",
        "识别口径：仅已确认事件参与；标注用于关注跟进，不合成总分、不排名。"));
    }
    render(root, focus, opts);
    return makeChart(el, root, render, opts);
  }

  /* ---------------- 一次性注入组件样式（dc- 前缀，不污染业务样式） ---------------- */
  var CSS = ""
    + ".dc{color:var(--ink,#1E1C19);font-size:13px}"
    + ".dc-empty{padding:26px 12px;text-align:center;color:var(--muted,#9A9386);"
    + "background:var(--paper,#F4F1EA);border:1px dashed var(--line,#E7E1D5);border-radius:6px}"
    + ".dc-empty-action{margin-left:10px;padding:3px 12px;font-size:12px;border-radius:3px;"
    + "cursor:pointer;border:1px solid var(--gold,#C9A84C);background:var(--card,#fff);"
    + "color:var(--red,#4A0C0C)}"
    + ".dc-empty-action:hover{background:var(--gold-soft,#F1E7CB)}"
    + ".dc-note{margin-top:10px;font-size:12px;color:var(--muted,#9A9386)}"
    + ".dc-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:14px}"
    + ".dc-kpi{background:var(--card,#fff);border:1px solid var(--line,#E7E1D5);"
    + "border-radius:6px;padding:12px 14px;box-shadow:0 1px 3px rgba(74,12,12,.04)}"
    + ".dc-kpi-label{font-size:12px;color:var(--sub,#6E675C)}"
    + ".dc-kpi-value{margin-top:6px;display:flex;align-items:baseline;gap:5px}"
    + ".dc-kpi-value b{font-size:26px;font-weight:600;line-height:1.1}"
    + ".dc-kpi-value small{color:var(--muted,#9A9386)}"
    + ".dc-kpi-foot{margin-top:6px;font-size:11px;color:var(--muted,#9A9386)}"
    + ".dc-tone-ok b{color:var(--ok,#2E7D5B)}.dc-tone-danger b{color:var(--danger,#B03A2E)}"
    + ".dc-tone-gold b{color:#A9862F}.dc-tone-warn b{color:var(--warn,#A97B12)}"
    + ".dc-tone-ink b{color:var(--red,#4A0C0C)}"
    + ".dc-trend{overflow-x:auto;overflow-y:hidden}"
    + ".dc-trend svg{width:auto;min-width:100%;height:auto;display:block}"
    + ".dc-axis{font-size:10px;fill:var(--muted,#9A9386)}"
    + ".dc-legend{display:flex;gap:16px;justify-content:center;margin-top:6px;"
    + "font-size:12px;color:var(--sub,#6E675C)}"
    + ".dc-legend-item{display:inline-flex;align-items:center;gap:6px}"
    + ".dc-legend-item i{width:10px;height:10px;border-radius:2px;display:inline-block}"
    + ".dc-bar-row{display:flex;align-items:center;gap:10px;padding:7px 0;"
    + "border-bottom:1px solid var(--line-soft,#F0EBE1)}"
    + ".dc-bar-row:last-child{border-bottom:0}"
    + ".dc-clickable{cursor:pointer}.dc-clickable:hover{background:#FDFBF6}"
    + ".dc-clickable:focus-visible{outline:2px solid var(--gold,#C9A84C);outline-offset:2px}"
    + ".dc-bar-name{flex:0 0 118px;font-weight:600;color:var(--red,#4A0C0C);"
    + "white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
    + ".dc-bar-track{position:relative;flex:1;height:16px;background:var(--paper,#F4F1EA);"
    + "border-radius:3px;overflow:hidden}"
    + ".dc-bar-zero{position:absolute;left:50%;top:0;bottom:0;width:1px;"
    + "background:var(--line,#E7E1D5)}"
    + ".dc-bar-fill{position:absolute;top:2px;bottom:2px;border-radius:2px;display:block}"
    + ".dc-bar-fill.is-pos{background:var(--ok,#2E7D5B)}"
    + ".dc-bar-fill.is-neg{background:var(--danger,#B03A2E)}"
    + ".dc-bar-num{flex:0 0 52px;text-align:right;font-weight:600}"
    + ".dc-bar-num.is-neg{color:var(--danger,#B03A2E)}.dc-bar-num.is-pos{color:var(--ok,#2E7D5B)}"
    + ".dc-band{flex:0 0 auto;font-size:11px;padding:1px 8px;border-radius:10px;"
    + "background:var(--gold-soft,#F1E7CB);color:#7A5E14}"
    + ".dc-mix{display:grid;grid-template-columns:1fr 1fr;gap:18px}"
    + ".dc-mix-title{margin:0 0 8px;font-size:13px;font-weight:600}"
    + ".dc-mix-title.is-pos{color:var(--ok,#2E7D5B)}.dc-mix-title.is-neg{color:var(--danger,#B03A2E)}"
    + ".dc-mix-row{margin-bottom:10px}"
    + ".dc-mix-head{display:flex;justify-content:space-between;gap:8px;font-size:12px}"
    + ".dc-mix-name{color:var(--sub,#6E675C)}"
    + ".dc-mix-val.is-pos{color:var(--ok,#2E7D5B)}.dc-mix-val.is-neg{color:var(--danger,#B03A2E)}"
    + ".dc-mix-track{height:8px;background:var(--paper,#F4F1EA);border-radius:4px;"
    + "overflow:hidden;margin-top:4px}"
    + ".dc-mix-track b{display:block;height:100%;border-radius:4px}"
    + ".dc-mix-track b.is-pos{background:var(--ok,#2E7D5B)}"
    + ".dc-mix-track b.is-neg{background:var(--danger,#B03A2E)}"
    + ".dc-focus-card{position:relative;border:1px solid var(--line,#E7E1D5);border-radius:6px;"
    + "padding:11px 14px;margin-bottom:10px;background:var(--card,#fff)}"
    + ".dc-focus-card::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;"
    + "border-radius:6px 0 0 6px;background:var(--danger,#B03A2E)}"
    + ".dc-focus-card.is-class::before{background:var(--gold,#C9A84C)}"
    + ".dc-focus-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}"
    + ".dc-tag{font-size:11px;padding:1px 7px;border-radius:3px}"
    + ".dc-tag-student{background:var(--danger-bg,#FBEAE8);color:var(--danger,#B03A2E)}"
    + ".dc-tag-class{background:var(--gold-soft,#F1E7CB);color:#7A5E14}"
    + ".dc-focus-name{font-size:14px;color:var(--red,#4A0C0C)}"
    + ".dc-focus-cls{color:var(--muted,#9A9386);font-size:12px}"
    + ".dc-focus-score{margin-left:auto;font-weight:600}"
    + ".dc-focus-score.is-neg{color:var(--danger,#B03A2E)}.dc-focus-score.is-pos{color:var(--ok,#2E7D5B)}"
    + ".dc-focus-reasons{margin:8px 0 0;padding-left:18px;color:var(--sub,#6E675C);font-size:12.5px}"
    + ".dc-focus-btn{margin-top:8px;padding:4px 12px;font-size:12px;border-radius:3px;cursor:pointer;"
    + "border:1px solid var(--line,#E7E1D5);background:#fff;color:var(--red,#4A0C0C)}"
    + ".dc-focus-btn:hover{background:var(--gold-soft,#F1E7CB)}"
    + "@media(max-width:720px){.dc-mix{grid-template-columns:1fr}"
    + ".dc-bar-name{flex-basis:86px}.dc-bar-num{flex-basis:44px}}";

  function injectStyle() {
    if (document.getElementById("deyu-charts-style")) return;
    var style = h("style");
    style.id = "deyu-charts-style";
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  global.DeyuCharts = {
    palette: PALETTE,
    kpis: function (el, d, o) { injectStyle(); return kpis(el, d, o); },
    trend: function (el, d, o) { injectStyle(); return trend(el, d, o); },
    classBars: function (el, d, o) { injectStyle(); return classBars(el, d, o); },
    criteriaMix: function (el, d, o) { injectStyle(); return criteriaMix(el, d, o); },
    focusList: function (el, d, o) { injectStyle(); return focusList(el, d, o); }
  };
})(window);
