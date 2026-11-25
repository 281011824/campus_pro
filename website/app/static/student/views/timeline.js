/* 成长时间轴：类型 Chip 筛选 + 按日期分组 + 加载更多 */
(function () {
  'use strict';
  var A = window.App;
  var $ = function (s, h) { return (h || document).querySelector(s); };
  var $all = function (s, h) {
    return Array.prototype.slice.call((h || document).querySelectorAll(s));
  };

  var TYPES = [
    { key: 'all', label: '全部' },
    { key: 'moral', label: '德育' },
    { key: 'assess', label: '测评' },
    { key: 'attendance', label: '考勤' },
    { key: 'homework', label: '作业' },
    { key: 'plan', label: '计划' }
  ];
  var TYPE_NAME = { moral: '德育', assess: '测评', attendance: '考勤', homework: '作业', plan: '计划' };

  function groupByDate(items) {
    var groups = [];
    var map = {};
    items.forEach(function (it) {
      var day = String(it.date || '').slice(0, 10) || '未注明日期';
      if (!map[day]) {
        map[day] = { date: day, items: [] };
        groups.push(map[day]);
      }
      map[day].items.push(it);
    });
    return groups;
  }

  function render(el) {
    var st = { type: 'all', page: 1, items: [], hasMore: false, busy: false };

    el.innerHTML = '<div class="hello"><h1>成长时间轴</h1>' +
      '<div class="id">德育 · 测评 · 考勤 · 作业 · 计划，按时间留痕</div></div>' +
      '<div class="seg" id="tl-filter">' + TYPES.map(function (t) {
        return '<button type="button" data-type="' + t.key + '"' +
          (t.key === 'all' ? ' class="on"' : '') + '>' + t.label + '</button>';
      }).join('') + '</div>' +
      '<div class="card"><div class="card-b" id="tl-list"></div></div>' +
      '<div class="row" style="justify-content:center;margin-bottom:12px">' +
      '<button type="button" class="btn ghost" id="tl-more" hidden>加载更多</button></div>';

    $all('#tl-filter button', el).forEach(function (btn) {
      btn.addEventListener('click', function () {
        var t = btn.getAttribute('data-type');
        if (t === st.type) { return; }
        st.type = t;
        st.page = 1;
        st.items = [];
        $all('#tl-filter button', el).forEach(function (b) { b.classList.remove('on'); });
        btn.classList.add('on');
        load(true);
      });
    });

    $('#tl-more', el).addEventListener('click', function () {
      if (st.busy) { return; }
      st.page += 1;
      load(false);
    });

    function listHTML() {
      if (!st.items.length) {
        return A.emptyHTML('还没有成长记录', '<p class="tiny" style="margin-top:4px">完成第一项测评或第一次打卡后，这里就是你的成长轨迹。</p>');
      }
      var groups = groupByDate(st.items);
      return groups.map(function (g) {
        return '<div class="tl-group"><div class="tl-date">' + A.esc(g.date) + '</div>' +
          '<div class="tl">' + g.items.map(function (it) {
            var pts = Number(it.points) || 0;
            var ptsHTML = pts ? '<span class="tp ' + (pts > 0 ? 'pos' : 'neg') + '">' +
              (pts > 0 ? '+' : '') + pts + '</span>' : '';
            var kind = it.type === 'moral' && pts < 0 ? ' t-neg' : (it.type === 'moral' ? ' t-moral' : '');
            return '<div class="tl-item' + kind + '">' +
              '<div class="tt">' + A.esc(it.title || TYPE_NAME[it.type] || '记录') + ptsHTML + '</div>' +
              (it.detail ? '<div class="td">' + A.esc(it.detail) + '</div>' : '') +
              (TYPE_NAME[it.type] ? '<div class="tiny" style="margin-top:2px">' +
                A.esc(TYPE_NAME[it.type]) + '</div>' : '') +
              '</div>';
          }).join('') + '</div></div>';
      }).join('');
    }

    function paint() {
      var list = $('#tl-list', el);
      if (list) { list.innerHTML = listHTML(); }
      var more = $('#tl-more', el);
      if (more) {
        more.hidden = !st.hasMore;
        more.disabled = st.busy;
        more.textContent = st.busy ? '加载中…' : '加载更多';
      }
    }

    function load(reset) {
      st.busy = true;
      var list = $('#tl-list', el);
      if (reset && list) { list.innerHTML = A.skeleton(2); }
      var url = '/api/v1/student/timeline?type=' + encodeURIComponent(st.type) +
        '&page=' + st.page + '&size=20';
      A.get(url).then(function (d) {
        d = d || {};
        st.items = reset ? (d.items || []) : st.items.concat(d.items || []);
        st.hasMore = !!d.has_more;
        st.busy = false;
        paint();
      }).catch(function (err) {
        st.busy = false;
        if (reset) {
          A.renderError(el, err, function () { load(true); });
          return;
        }
        paint();
        A.toast((err && err.message) || '加载失败');
      });
    }

    load(true);
  }

  window.Views = window.Views || {};
  window.Views.timeline = { render: render };
})();
