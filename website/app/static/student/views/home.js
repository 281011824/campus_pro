/* 首页：问候 + 四频道卡（德育/考勤/作业/成长）+ 快捷入口 */
(function () {
  'use strict';
  var A = window.App;

  var STATUS = { present: '出勤', absent: '未到', late: '迟到', leave: '请假' };

  // 最新画像可能是对象 {term, tags}，统一转成可展示的短标签，避免渲染成 [object Object]
  function profileLabel(gp) {
    if (!gp) { return ''; }
    if (typeof gp === 'string') { return gp; }
    if (gp.tags && gp.tags.length) {
      return gp.tags.slice(0, 2).map(function (t) {
        return typeof t === 'string' ? t : (t.label || t.name || t.dim || '');
      }).filter(Boolean).join(' · ');
    }
    return gp.term || '已生成画像';
  }

  function miniBars(daily) {
    if (!daily || !daily.length) { return ''; }
    var W = 280, H = 52, gap = 6;
    var n = daily.length;
    var slot = (W - gap * (n - 1)) / n;
    var barW = Math.min(slot, 26);
    var max = 0;
    daily.forEach(function (d) {
      var v = Math.abs(Number(d.net) || 0);
      if (v > max) { max = v; }
    });
    if (max === 0) { max = 1; }
    var zero = H / 2;
    var half = H / 2 - 4;
    var svg = ['<svg class="mini" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" ' +
      'role="img" aria-label="本周每日德育净得分">'];
    svg.push('<line x1="0" y1="' + zero + '" x2="' + W + '" y2="' + zero +
      '" stroke="#e2e8f2" stroke-dasharray="3 3"/>');
    daily.forEach(function (d, i) {
      var v = Number(d.net) || 0;
      var h = Math.max(2, Math.abs(v) / max * half);
      var x = i * (slot + gap) + (slot - barW) / 2;
      var y = v >= 0 ? zero - h : zero;
      svg.push('<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + barW.toFixed(1) +
        '" height="' + h.toFixed(1) + '" rx="3" fill="' + (v >= 0 ? '#1f9d63' : '#c94a4a') + '"/>');
    });
    svg.push('</svg>');
    return svg.join('');
  }

  function moralCard(m, daily) {
    if (!m) {
      return '<div class="chan wide na"><div class="ch-top"><span class="ch-name">' + A.icon('chart') +
        '德育量化</span></div><div class="ch-val">暂不可用</div>' +
        '<div class="ch-sub">本周暂无已确认记录</div></div>';
    }
    var delta = Number(m.week_delta) || 0;
    var cls = delta >= 0 ? 'pos' : 'neg';
    return '<div class="chan wide">' +
      '<div class="ch-top"><span class="ch-name">' + A.icon('chart') + '德育量化</span>' +
      '<span class="chip ' + cls + '">本周 ' + (delta > 0 ? '+' : '') + delta + ' 分</span></div>' +
      '<div class="ch-val">' + A.na(m.total_score, ' 分') + '<small>基准 100 分</small></div>' +
      '<div class="ch-sub">已确认 ' + A.na(m.event_count, ' 条') + ' · 仅本人可见，不公开排名</div>' +
      (daily && daily.length ? miniBars(daily) : '') +
      '</div>';
  }

  function attendanceCard(a) {
    if (!a) {
      return '<div class="chan na"><div class="ch-top"><span class="ch-name">' + A.icon('clock') +
        '考勤</span></div><div class="ch-val">暂不可用</div><div class="ch-sub">本周暂无考勤记录</div></div>';
    }
    var status = a.today_status ? (STATUS[a.today_status] || a.today_status) : '暂无记录';
    var rate = a.week_rate;
    var warn = rate != null && rate < 90;
    return '<div class="chan">' +
      '<div class="ch-top"><span class="ch-name">' + A.icon('clock') + '考勤</span>' +
      '<span class="chip ' + (status === '出勤' ? 'pos' : (status === '暂无记录' ? 'none' : 'warn')) +
      '">今日 ' + A.esc(status) + '</span></div>' +
      '<div class="ch-val">' + A.na(rate, '%') + '<small>本周出勤率</small></div>' +
      '<div class="bar' + (warn ? ' warn' : '') + '"><i style="width:' + (rate == null ? 0 : rate) + '%"></i></div>' +
      '</div>';
  }

  function homeworkCard(h) {
    if (!h) {
      return '<div class="chan na"><div class="ch-top"><span class="ch-name">' + A.icon('book') +
        '作业</span></div><div class="ch-val">暂不可用</div><div class="ch-sub">本周暂无作业记录</div></div>';
    }
    var rate = h.rate;
    var warn = rate != null && rate < 80;
    return '<div class="chan">' +
      '<div class="ch-top"><span class="ch-name">' + A.icon('book') + '作业</span>' +
      '<span class="chip ' + (warn ? 'warn' : 'pos') + '">未交 ' + A.na(h.missed_count, ' 次') + '</span></div>' +
      '<div class="ch-val">' + A.na(rate, '%') + '<small>本周提交率</small></div>' +
      '<div class="ch-sub">已交 ' + A.na(h.submitted, ' 次') + ' / 共 ' + A.na(h.total, ' 次') + '</div>' +
      '<div class="bar' + (warn ? ' warn' : '') + '"><i style="width:' + (rate == null ? 0 : rate) + '%"></i></div>' +
      '</div>';
  }

  function growthCard(g) {
    if (!g) {
      return '<div class="chan wide na"><div class="ch-top"><span class="ch-name">' + A.icon('target') +
        '成长</span></div><div class="ch-val">暂不可用</div><div class="ch-sub">完成测评后生成画像</div></div>';
    }
    var done = g.assess_done, total = g.assess_total;
    if (done == null || total == null) {
      return '<div class="chan wide na"><div class="ch-top"><span class="ch-name">' + A.icon('target') +
        '成长</span></div><div class="ch-val">暂不可用</div>' +
        '<div class="ch-sub">' + A.esc(g.latest_profile || '测评进度待同步') + '</div></div>';
    }
    var pct = total ? Math.round((done || 0) / total * 100) : 0;
    var tag = profileLabel(g.latest_profile) || '尚未生成画像';
    return '<div class="chan wide">' +
      '<div class="ch-top"><span class="ch-name">' + A.icon('target') + '成长</span>' +
      '<span class="chip">' + A.esc(tag) + '</span></div>' +
      '<div class="ch-val">' + A.na(done, '') + '<small>/ ' + A.na(total, '') + ' 项测评已完成</small></div>' +
      '<div class="bar"><i style="width:' + pct + '%"></i></div>' +
      '<div class="ch-sub" style="margin-top:6px">' +
      (done > 0 ? '继续完成剩余量表，画像会更完整' : '先完成一项测评，给自己一个起点') + '</div>' +
      '</div>';
  }

  function quickLinks() {
    var items = [
      { href: '#/assess', icon: 'assess', label: '测评' },
      { href: '#/timeline', icon: 'timeline', label: '时间轴' },
      { href: '#/share', icon: 'share', label: '分享' },
      { href: '#/privacy', icon: 'shield', label: '隐私' }
    ];
    return '<div class="card"><div class="card-b">' +
      '<div class="between" style="margin-bottom:10px"><h2 style="font-size:15px">快捷入口</h2>' +
      '<span class="tiny">常用四件事</span></div>' +
      '<div class="quick">' + items.map(function (it) {
        return '<a href="' + it.href + '"><span class="qi">' + A.icon(it.icon) + '</span>' + it.label + '</a>';
      }).join('') + '</div></div></div>';
  }

  function render(el, params) {
    el.innerHTML = A.skeleton(4);

    function load() {
      Promise.all([
        A.get('/api/v1/student/home'),
        A.get('/api/v1/student/moral').catch(function () { return null; })
      ]).then(function (res) {
        var home = res[0] || {};
        var moralExtra = res[1];
        var p = home.profile || {};
        var daily = moralExtra && moralExtra.daily ? moralExtra.daily : null;

        var hello = '<div class="hello">' +
          '<h1>' + A.esc(A.greeting()) + '，' + A.esc(p.name || '同学') + '</h1>' +
          '<div class="id">' + A.esc(p.class_name || '班级待同步') +
          (p.student_no ? ' · 学号 ' + A.esc(p.student_no) : '') + '</div>' +
          '<div class="date"><span class="chip outline">' + A.todayISO() + '</span>' +
          (home.growth && home.growth.latest_profile
            ? '<span class="chip">' + A.esc(profileLabel(home.growth.latest_profile)) + '</span>' : '') +
          '</div></div>';

        var body = hello +
          '<div class="grid2">' +
          moralCard(home.moral, daily) +
          attendanceCard(home.attendance) +
          homeworkCard(home.homework) +
          growthCard(home.growth) +
          '</div>' +
          quickLinks();

        el.innerHTML = body;
      }).catch(function (err) {
        A.renderError(el, err, load);
      });
    }

    load();
  }

  window.Views = window.Views || {};
  window.Views.home = { render: render };
})();
