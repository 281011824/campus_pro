/* 隐私与数据权利：可见范围表、家长绑定（生成绑定码/撤回）、分享记录 */
(function () {
  'use strict';
  var A = window.App;
  var $ = function (s, h) { return (h || document).querySelector(s); };
  var $all = function (s, h) {
    return Array.prototype.slice.call((h || document).querySelectorAll(s));
  };

  var ROLES = [
    { key: 'self', label: '本人', text: '全部记录与成长画像' },
    { key: 'head_teacher', label: '班主任', text: '德育 / 考勤 / 作业 / 测评进度' },
    { key: 'dept', label: '政教处', text: '德育事件与考勤台账（汇总）' },
    { key: 'family', label: '家长', text: '仅经我授权的范围' },
    { key: 'guest', label: '分享访客', text: '仅分享码白名单内容' }
  ];
  var ALIAS = {
    self: 'self', student: 'self', me: 'self', 本人: 'self',
    head_teacher: 'head_teacher', teacher: 'head_teacher', class_teacher: 'head_teacher', 班主任: 'head_teacher',
    dept: 'dept', political: 'dept', moral_dept: 'dept', 政教处: 'dept',
    family: 'family', parent: 'family', parents: 'family', 家长: 'family',
    guest: 'guest', share: 'guest', visitor: 'guest', 分享访客: 'guest'
  };

  function normScopes(raw) {
    var result = ROLES.map(function (r) {
      return { key: r.key, label: r.label, text: r.text, visible: null };
    });
    if (!raw) { return result; }
    var list = [];
    if (Array.isArray(raw)) {
      raw.forEach(function (r) {
        if (!r) { return; }
        list.push({
          key: r.key || r.role || r.type,
          text: r.text || r.desc || r.scope || (Array.isArray(r.items) ? r.items.join(' / ') : ''),
          visible: r.visible != null ? !!r.visible : (r.enabled != null ? !!r.enabled : null)
        });
      });
    } else if (typeof raw === 'object') {
      Object.keys(raw).forEach(function (k) {
        var v = raw[k];
        if (v == null) { return; }
        if (typeof v === 'boolean') {
          list.push({ key: k, visible: v, text: '' });
        } else if (typeof v === 'string') {
          list.push({ key: k, visible: null, text: v });
        } else {
          list.push({
            key: v.key || v.role || k,
            text: v.text || v.desc || v.scope || (Array.isArray(v.items) ? v.items.join(' / ') : ''),
            visible: v.visible != null ? !!v.visible : (v.enabled != null ? !!v.enabled : null)
          });
        }
      });
    }
    list.forEach(function (row) {
      var mapped = ALIAS[String(row.key || '')] || row.key;
      result.forEach(function (base) {
        if (base.key !== mapped) { return; }
        if (row.text) { base.text = row.text; }
        base.visible = row.visible;
      });
    });
    return result;
  }

  function bindingsOf(p) {
    var raw = p.bindings || p.parents || p.family || [];
    return Array.isArray(raw) ? raw : [];
  }

  function render(el) {
    el.innerHTML = '<div class="hello"><h1>隐私与数据权利</h1>' +
      '<div class="id">谁能看到什么，由我决定；所有授权都可随时撤回。</div></div>' +
      '<div id="privacy-body">' + A.skeleton(4) + '</div>';

    function paint(p, shares) {
      p = p || {};
      var scopes = normScopes(p.scopes || p.visibility || p.visible_scope);
      var bindings = bindingsOf(p);

      var html = '<div class="card"><div class="card-h"><h2>可见范围</h2>' +
        '<span class="meta">默认最小可见</span></div><div class="card-b flush">' +
        '<table class="priv-table"><thead><tr><th>角色</th><th>可见内容</th><th>状态</th></tr></thead><tbody>' +
        scopes.map(function (s) {
          var status = s.visible === true ? '可见' : (s.visible === false ? '不可见' : '—');
          var cls = s.visible === true ? 'pos' : (s.visible === false ? 'none' : 'outline');
          return '<tr><td>' + A.esc(s.label) + '</td><td>' + A.esc(s.text || '—') +
            '</td><td><span class="chip ' + cls + '">' + status + '</span></td></tr>';
        }).join('') + '</tbody></table></div></div>';

      html += '<div class="card"><div class="card-h"><h2>家长绑定</h2>' +
        '<span class="meta">' + (bindings.length ? bindings.length + ' 位' : '暂无') + '</span></div>' +
        '<div class="card-b">' +
        '<p class="sub">家长绑定后只能看到基础情况；画像等增强内容需另行授权，可随时撤回。</p>' +
        '<div class="row" style="margin-top:10px">' +
        '<button type="button" class="btn ghost" id="gen-code">生成绑定码</button>' +
        '<span id="bind-code"></span></div>' +
        '<div id="bind-list" style="margin-top:6px">' +
        (bindings.length ? bindings.map(function (b) {
          return '<div class="parent-item"><div class="between"><b>' +
            A.esc(b.parent_name || b.name || b.relation || '家长') + '</b>' +
            '<span class="tiny">' + A.esc(b.mobile || b.phone || b.mobile_masked || '') + '</span></div>' +
            '<p class="tiny" style="margin-top:2px">绑定于 ' +
            A.esc(A.fmtDate(b.created_at || b.bind_at)) + '</p>' +
            '<div class="tacts" style="margin-top:8px"><button type="button" class="btn danger sm" ' +
            'data-unbind="' + A.esc(b.id || b.binding_id) + '">撤回</button></div></div>';
        }).join('') : '<p class="tiny" style="margin-top:6px">还没有绑定家长。生成绑定码，让家长在家长端输入即可。</p>') +
        '</div></div></div>';

      var list = Array.isArray(shares) ? shares : [];
      html += '<div class="card"><div class="card-h"><h2>分享记录</h2>' +
        '<span class="meta">' + (list.length ? list.length + ' 条' : '暂无') + '</span></div>' +
        '<div class="card-b">' +
        (list.length ? list.map(function (it) {
          var status = it.status || 'active';
          var label = status === 'active' ? '生效中' : (status === 'revoked' ? '已撤销' : '已过期');
          return '<div class="rowitem"><div class="body"><b>分享码 ' + A.esc(it.code || it.id) + '</b>' +
            '<p>' + A.esc(A.fmtDT(it.expires_at)) + ' 到期 · ' + A.esc(label) + '</p></div></div>';
        }).join('') : '<p class="tiny">还没有分享记录。</p>') +
        '<div class="row" style="margin-top:10px"><a class="btn ghost sm" href="#/share">去分享管理</a></div>' +
        '</div></div>';

      html += '<p class="foot-note">心理数据等敏感信息单独授权；不签不影响其他功能。</p>';
      document.getElementById('privacy-body').innerHTML = html;
      bind();
    }

    function bind() {
      var body = document.getElementById('privacy-body');
      var gen = $('#gen-code', body);
      if (gen) {
        gen.addEventListener('click', function () {
          gen.disabled = true;
          A.post('/api/v1/student/privacy/binding-code').then(function (d) {
            gen.disabled = false;
            var box = $('#bind-code', body);
            if (box && d && d.code) {
              box.innerHTML = '<span class="bindcode">' + A.esc(d.code) + '</span>' +
                '<div class="tiny" style="margin-top:4px">' + A.esc(A.fmtDT(d.expires_at)) + ' 前有效</div>';
            }
            A.toast('绑定码已生成');
          }).catch(function (err) {
            gen.disabled = false;
            A.toast((err && err.message) || '生成失败');
          });
        });
      }

      $all('[data-unbind]', body).forEach(function (btn) {
        btn.addEventListener('click', function () {
          var id = btn.getAttribute('data-unbind');
          if (!id || id === 'undefined') { A.toast('缺少绑定记录 ID'); return; }
          if (!window.confirm('撤回后对方将看不到你的信息，确定？')) { return; }
          btn.disabled = true;
          A.del('/api/v1/student/privacy/bindings/' + encodeURIComponent(id))
            .then(function () { A.toast('已撤回'); load(); })
            .catch(function (err) {
              btn.disabled = false;
              A.toast((err && err.message) || '撤回失败');
            });
        });
      });
    }

    function load() {
      Promise.all([
        A.get('/api/v1/student/privacy'),
        A.get('/api/v1/student/shares').catch(function () { return null; })
      ]).then(function (res) {
        var p = res[0] || {};
        var shares = res[1] && res[1].items ? res[1].items : (p.shares || []);
        paint(p, shares);
      }).catch(function (err) {
        var body = document.getElementById('privacy-body');
        if (body) { A.renderError(body, err, load); }
      });
    }

    load();
  }

  window.Views = window.Views || {};
  window.Views.privacy = { render: render };
})();
