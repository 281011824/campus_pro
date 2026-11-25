/* 我的：身份卡、班级与专业、学号、隐私设置入口、退出登录 */
(function () {
  'use strict';
  var A = window.App;

  function row(label, value) {
    return '<div class="between" style="padding:9px 0;border-top:1px solid var(--line)">' +
      '<span class="tiny">' + A.esc(label) + '</span>' +
      '<b style="font-size:13px;text-align:right;word-break:break-all">' + A.esc(value || '—') + '</b></div>';
  }

  function render(el) {
    el.innerHTML = A.skeleton(3);

    function load() {
      A.loadMe().then(function (me) {
        me = me || {};
        if (me.student) { me = me.student; } else if (me.profile) { me = me.profile; }
        var name = me.name || '同学';
        var initial = name.slice(0, 1);
        var html = '<div class="card"><div class="card-b me-card">' +
          '<div class="avatar">' + A.esc(initial) + '</div>' +
          '<div class="mbody"><h2>' + A.esc(name) + '</h2>' +
          '<div class="mid">' + A.esc(me.class_name || '班级待同步') +
          (me.major ? ' · ' + A.esc(me.major) : '') + '</div>' +
          '<div class="mid">学号 ' + A.esc(me.student_no || me.student_id || '—') + '</div>' +
          '</div></div></div>';

        html += '<div class="card"><div class="card-h"><h2>基本信息</h2></div><div class="card-b" style="padding-top:0">' +
          row('学号', me.student_no || me.student_id) +
          row('班级', me.class_name) +
          row('专业', me.major) +
          row('年级', me.grade) +
          '</div></div>';

        html += '<div class="card"><div class="card-h"><h2>我的</h2></div><div class="card-b">' +
          '<div class="menu">' +
          '<a href="#/privacy"><span class="mi">' + A.icon('shield') + '</span><span>隐私与数据权利</span><em>›</em></a>' +
          '<a href="#/profile"><span class="mi">' + A.icon('chart') + '</span><span>我的画像</span><em>›</em></a>' +
          '<a href="#/plan"><span class="mi">' + A.icon('target') + '</span><span>计划与打卡</span><em>›</em></a>' +
          '<a href="#/batch"><span class="mi">' + A.icon('assess') + '</span><span>批次进度</span><em>›</em></a>' +
          '<a href="#/share"><span class="mi">' + A.icon('share') + '</span><span>分享成长</span><em>›</em></a>' +
          '</div></div></div>';

        html += '<div class="card"><div class="card-b">' +
          '<button type="button" class="btn danger block" id="logout">' + A.icon('logout') + '退出登录</button>' +
          '</div></div>' +
          '<p class="foot-note" style="text-align:center">京山市中等职业技术学校 · 学生成长门户<br>' +
          '数据只对你本人与授权对象可见。</p>';

        el.innerHTML = html;
        var out = document.getElementById('logout');
        if (out) {
          out.addEventListener('click', function () {
            if (!window.confirm('确定退出登录？')) { return; }
            location.href = '/api/v1/logout';
          });
        }
      }).catch(function (err) {
        A.renderError(el, err, load);
      });
    }

    load();
  }

  window.Views = window.Views || {};
  window.Views.mine = { render: render };
})();
