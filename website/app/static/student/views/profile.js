/* 我的画像：原生 SVG 雷达（5—8 维自适应）、优势/待发展、三条建议、更新日期 */
(function () {
  'use strict';
  var A = window.App;

  function labelOf(key) {
    var s = String(key == null ? '' : key);
    return s.indexOf(':') >= 0 ? s.split(':').slice(1).join(':') : s;
  }

  function dimsOf(p) {
    var src = p.radar || p.dimensions || p.dims || p.scores || null;
    if (!src) { return []; }
    var list = [];
    if (Array.isArray(src)) {
      src.forEach(function (it, i) {
        if (typeof it === 'number') {
          list.push({ name: '维度' + (i + 1), value: it });
        } else if (it && typeof it === 'object') {
          list.push({
            name: labelOf(it.dim || it.key || it.name || ('维度' + (i + 1))),
            value: Number(it.score != null ? it.score : it.value) || 0
          });
        }
      });
    } else {
      Object.keys(src).forEach(function (k) {
        list.push({ name: labelOf(k), value: Number(src[k]) || 0 });
      });
    }
    return list;
  }

  function tagsOf(p) {
    var raw = Array.isArray(p.tags) ? p.tags : [];
    var out = { strength: [], develop: [] };
    raw.forEach(function (t) {
      if (!t) { return; }
      if (typeof t === 'string') { out.strength.push({ name: t }); return; }
      var type = t.type || (t.kind === 'strength' ? 'strength' : (t.kind === 'develop' ? 'develop' : ''));
      var name = labelOf(t.dim || t.name || t.key);
      var item = { name: name, score: t.score };
      if (type === 'develop' || type === 'weak' || t.type === '待发展') {
        out.develop.push(item);
      } else if (type === 'strength' || type === '优势') {
        out.strength.push(item);
      } else if (t.score != null) {
        if (Number(t.score) >= 70) { out.strength.push(item); }
        if (Number(t.score) <= 40) { out.develop.push(item); }
      }
    });
    return out;
  }

  function adviceOf(p) {
    var raw = p.advice || p.suggestions || [];
    if (!Array.isArray(raw)) {
      if (!raw || typeof raw !== 'object') { return []; }
      raw = Object.keys(raw).map(function (k) {
        var v = raw[k];
        return typeof v === 'string' ? { title: k, text: v } :
          { title: k, text: (v && (v.text || v.content)) || '' };
      });
    }
    return raw.map(function (a) {
      if (typeof a === 'string') { return { title: '', text: a }; }
      if (!a) { return null; }
      return {
        title: a.track || a.dimension || a.title || '',
        text: a.text || a.content || a.suggestion || ''
      };
    }).filter(function (a) { return a && a.text; }).slice(0, 3);
  }

  function radarSVG(dims) {
    var n = dims.length;
    if (n < 3) { return ''; }
    if (n > 8) { dims = dims.slice(0, 8); n = 8; }
    var W = 360, H = 330;
    var cx = 180, cy = 160, R = 102;
    var levels = 4;
    function pt(i, ratio) {
      var ang = -Math.PI / 2 + i * 2 * Math.PI / n;
      return [cx + Math.cos(ang) * R * ratio, cy + Math.sin(ang) * R * ratio];
    }
    var svg = ['<svg class="radar" viewBox="0 0 ' + W + ' ' + H + '" role="img" ' +
      'aria-label="成长画像雷达图，共 ' + n + ' 个维度">'];
    for (var lv = 1; lv <= levels; lv++) {
      var pts = [];
      for (var i = 0; i < n; i++) {
        var p = pt(i, lv / levels);
        pts.push(p[0].toFixed(1) + ',' + p[1].toFixed(1));
      }
      svg.push('<polygon points="' + pts.join(' ') + '" fill="none" stroke="#e2e8f2" stroke-width="1"/>');
    }
    for (var a = 0; a < n; a++) {
      var e = pt(a, 1);
      svg.push('<line x1="' + cx + '" y1="' + cy + '" x2="' + e[0].toFixed(1) + '" y2="' + e[1].toFixed(1) +
        '" stroke="#e2e8f2" stroke-width="1"/>');
    }
    var poly = [];
    for (var j = 0; j < n; j++) {
      var v = Math.max(0, Math.min(100, Number(dims[j].value) || 0));
      var q = pt(j, v / 100);
      poly.push(q[0].toFixed(1) + ',' + q[1].toFixed(1));
    }
    svg.push('<polygon points="' + poly.join(' ') + '" fill="rgba(31,95,191,.16)" ' +
      'stroke="#1f5fbf" stroke-width="2" stroke-linejoin="round"/>');
    for (var k = 0; k < n; k++) {
      var d = poly[k].split(',');
      svg.push('<circle cx="' + d[0] + '" cy="' + d[1] + '" r="3" fill="#1f5fbf"/>');
      var lp = pt(k, 1.2);
      var anchor = 'middle';
      if (lp[0] < cx - 12) { anchor = 'end'; }
      if (lp[0] > cx + 12) { anchor = 'start'; }
      var name = dims[k].name;
      if (name.length > 5) { name = name.slice(0, 5); }
      svg.push('<text x="' + lp[0].toFixed(1) + '" y="' + (lp[1] + 4).toFixed(1) +
        '" text-anchor="' + anchor + '">' + A.esc(name) + '</text>');
    }
    svg.push('</svg>');
    return svg.join('');
  }

  function render(el) {
    el.innerHTML = A.skeleton(4);

    function load() {
      Promise.all([
        A.get('/api/v1/student/profile'),
        A.get('/api/v1/student/profile/history').catch(function () { return null; })
      ]).then(function (res) {
        var p = res[0] || {};
        var history = res[1];
        var dims = dimsOf(p);
        var tags = tagsOf(p);
        var advice = adviceOf(p);
        var updated = p.latest_test_at || p.latestTestAt || p.updated_at || p.generated_at || '';

        if (!dims.length && !tags.strength.length && !tags.develop.length && !advice.length) {
          el.innerHTML = '<div class="card"><div class="empty"><div class="eic">🌱</div>' +
            '<p>还没有画像</p><p class="tiny" style="margin-top:4px">完成测评后，这里会自动生成你的成长画像。</p>' +
            '<a class="btn primary" href="#/assess" style="margin-top:14px">去测评</a></div></div>';
          return;
        }

        var html = '<div class="hello"><h1>' + A.esc(p.term || '本学期') + ' · 我的画像</h1>' +
          '<div class="id">只和自己的过去比，不与他人排名；对外分享须经你授权。</div>' +
          '<div class="date"><span class="chip outline">更新于 ' + A.esc(A.fmtDate(updated) || '—') + '</span></div>' +
          '</div>';

        if (dims.length >= 3) {
          html += '<div class="card"><div class="card-h"><h2>成长雷达</h2>' +
            '<span class="meta">' + dims.length + ' 个维度</span></div>' +
            '<div class="card-b radar-wrap">' + radarSVG(dims) + '</div></div>';
        }

        html += '<div class="card"><div class="card-h"><h2>标签</h2>' +
          '<span class="meta">优势 ≥70 · 待发展 ≤40</span></div><div class="card-b">' +
          '<div class="row">' +
          (tags.strength.length ? tags.strength.map(function (t) {
            return '<span class="chip pos">优势 · ' + A.esc(t.name) +
              (t.score != null ? '（' + A.esc(t.score) + '）' : '') + '</span>';
          }).join('') : '<span class="tiny">暂无优势标签</span>') +
          '</div><div class="row" style="margin-top:8px">' +
          (tags.develop.length ? tags.develop.map(function (t) {
            return '<span class="chip warn">待发展 · ' + A.esc(t.name) +
              (t.score != null ? '（' + A.esc(t.score) + '）' : '') + '</span>';
          }).join('') : '<span class="tiny">暂无待发展标签</span>') +
          '</div></div></div>';

        html += '<div class="card"><div class="card-h"><h2>三条建议</h2>' +
          '<span class="meta">从画像里长出来的行动</span></div><div class="card-b">' +
          (advice.length ? advice.map(function (a, i) {
            return '<div class="rowitem"><div class="body"><b>' +
              (a.title ? A.esc(a.title) + ' · ' : '') + '建议 ' + (i + 1) + '</b>' +
              '<p>' + A.esc(a.text) + '</p></div></div>';
          }).join('') : '<p class="tiny">暂无建议；完成更多测评后会自动生成。</p>') +
          '</div></div>';

        var his = history && history.items ? history.items : (Array.isArray(history) ? history : []);
        if (his.length) {
          html += '<div class="card"><div class="card-h"><h2>历史学期</h2></div><div class="card-b">' +
            his.map(function (h) {
              return '<div class="rowitem"><div class="body"><b>' + A.esc(h.term || '历史画像') + '</b>' +
                '<p>' + A.esc(A.fmtDate(h.created_at || h.createdAt)) + '</p></div></div>';
            }).join('') + '</div></div>';
        }

        html += '<p class="foot-note">画像是给你用的，不是给你定性的。不同意哪条建议，可以找班主任沟通复核。</p>';
        el.innerHTML = html;
      }).catch(function (err) {
        A.renderError(el, err, load);
      });
    }

    load();
  }

  window.Views = window.Views || {};
  window.Views.profile = { render: render };
})();
