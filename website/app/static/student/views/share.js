/* 分享成长：时长选择、生成分享码、复制链接、我的分享列表（撤销） */
(function () {
  'use strict';
  var A = window.App;
  var $ = function (s, h) { return (h || document).querySelector(s); };
  var $all = function (s, h) {
    return Array.prototype.slice.call((h || document).querySelectorAll(s));
  };

  var DURATIONS = [
    { hours: 24, label: '24 小时' },
    { hours: 72, label: '72 小时' },
    { hours: 168, label: '7 天' }
  ];
  var STATUS_TEXT = { active: '生效中', expired: '已过期', revoked: '已撤销' };

  function guestURL(code) {
    return location.origin + '/student/share?code=' + encodeURIComponent(code || '');
  }

  function copyText(text, btn, label) {
    function done() {
      btn.textContent = '已复制 ✓';
      setTimeout(function () { btn.textContent = label; }, 1800);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallback(); });
    } else {
      fallback();
    }
    function fallback() {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', 'readonly');
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand('copy'); done(); } catch (e) { A.toast('复制失败，请长按选择复制'); }
      document.body.removeChild(ta);
    }
  }

  function render(el) {
    var hours = 24;

    el.innerHTML = '<div class="hello"><h1>分享成长</h1>' +
      '<div class="id">只分享你选定的内容；访客免登录，但必须凭 8 位分享码查看。</div></div>' +
      '<div class="card"><div class="card-h"><h2>生成分享码</h2>' +
      '<span class="meta">白名单内容</span></div><div class="card-b">' +
      '<p class="sub">选择有效期，生成后把码或链接发给对方；到期或撤销后立即失效。</p>' +
      '<div class="seg" id="share-dur" style="margin-top:10px">' + DURATIONS.map(function (d) {
        return '<button type="button" data-hours="' + d.hours + '"' +
          (d.hours === 24 ? ' class="on"' : '') + '>' + d.label + '</button>';
      }).join('') + '</div>' +
      '<button type="button" class="btn primary block" id="share-create">生成分享码</button>' +
      '<div id="share-result"></div>' +
      '</div></div>' +
      '<div class="card"><div class="card-h"><h2>我发出的分享</h2>' +
      '<span class="meta" id="share-count"></span></div>' +
      '<div class="card-b" id="share-list">' + A.skeleton(2) + '</div></div>';

    $all('#share-dur button', el).forEach(function (btn) {
      btn.addEventListener('click', function () {
        hours = Number(btn.getAttribute('data-hours')) || 24;
        $all('#share-dur button', el).forEach(function (b) { b.classList.remove('on'); });
        btn.classList.add('on');
      });
    });

    $('#share-create', el).addEventListener('click', function () {
      var btn = this;
      btn.disabled = true;
      A.post('/api/v1/student/shares', { hours: hours }).then(function (d) {
        btn.disabled = false;
        paintResult(d);
        A.toast('分享码已生成');
        loadList();
      }).catch(function (err) {
        btn.disabled = false;
        A.toast((err && err.message) || '生成失败');
      });
    });

    function paintResult(d) {
      var box = $('#share-result', el);
      if (!box || !d || !d.code) { return; }
      var url = d.url || guestURL(d.code);
      box.innerHTML = '<div class="codebox"><div class="tiny">分享码（8 位）</div>' +
        '<div class="code">' + A.esc(d.code) + '</div>' +
        '<div class="tiny">' + A.esc(A.fmtDT(d.expires_at)) + ' 到期</div>' +
        '<div class="row" style="justify-content:center;margin-top:10px">' +
        '<button type="button" class="btn ghost sm" id="copy-link">复制链接</button>' +
        '<button type="button" class="btn sm" id="copy-code">复制分享码</button></div>' +
        '<p class="tiny" style="margin-top:8px;word-break:break-all">' + A.esc(url) + '</p></div>';

      $('#copy-link', box).addEventListener('click', function () {
        copyText(url, this, '复制链接');
      });
      $('#copy-code', box).addEventListener('click', function () {
        copyText(d.code, this, '复制分享码');
      });
    }

    function paintList(items) {
      var list = $('#share-list', el);
      var count = $('#share-count', el);
      if (count) { count.textContent = items.length ? items.length + ' 条' : '暂无'; }
      if (!list) { return; }
      if (!items.length) {
        list.innerHTML = A.emptyHTML('还没有分享记录', '<p class="tiny" style="margin-top:4px">生成分享码后，这里会记录有效期与撤销入口。</p>');
        return;
      }
      list.innerHTML = items.map(function (it) {
        var status = it.status || 'active';
        if (status === 'active' && it.expires_at && String(it.expires_at).slice(0, 10) < A.todayISO()) {
          status = 'expired';
        }
        var cls = status === 'active' ? 'pos' : 'none';
        return '<div class="rowitem"><div class="body">' +
          '<div class="between"><b>分享码 ' + A.esc(it.code || it.id) + '</b>' +
          '<span class="badge ' + (status === 'active' ? 'ok' : '') + '">' +
          A.esc(STATUS_TEXT[status] || status) + '</span></div>' +
          '<p>' + A.esc(A.fmtDT(it.expires_at)) + ' 到期' +
          (it.visit_count != null ? ' · 访问 ' + A.esc(it.visit_count) + ' 次' : '') + '</p>' +
          (status === 'active' ? '<div class="tacts"><button type="button" class="btn danger sm" ' +
            'data-revoke="' + A.esc(it.id) + '">撤销</button></div>' : '') +
          '</div></div>';
      }).join('');

      $all('[data-revoke]', list).forEach(function (btn) {
        btn.addEventListener('click', function () {
          if (!window.confirm('撤销后访客立即失效，确定？')) { return; }
          btn.disabled = true;
          A.del('/api/v1/student/shares/' + encodeURIComponent(btn.getAttribute('data-revoke')))
            .then(function () { A.toast('已撤销'); loadList(); })
            .catch(function (err) {
              btn.disabled = false;
              A.toast((err && err.message) || '撤销失败');
            });
        });
      });
    }

    function loadList() {
      A.get('/api/v1/student/shares').then(function (d) {
        paintList((d && d.items) || []);
      }).catch(function (err) {
        var list = $('#share-list', el);
        if (list) { A.renderError(list, err, loadList); }
      });
    }

    loadList();
  }

  window.Views = window.Views || {};
  window.Views.share = { render: render };
})();
