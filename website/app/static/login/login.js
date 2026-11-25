/* 统一登录页交互：三身份切换、教师/学生双表单、家长入口折叠 */
(function ($) {
  'use strict';

  var $seg = $('#roleSeg');
  var $panes = $('.role-pane');
  var $staffForm = $('#loginForm');
  var $stuForm = $('#loginFormStudent');
  var currentRole = 'staff';
  var storeKey = 'htw_login_account';

  // Tab 切换
  function switchRole(role) {
    currentRole = role;
    $('.seg-btn', $seg).each(function () {
      var $b = $(this);
      var on = $b.data('role') === role;
      $b.toggleClass('on', on).attr('aria-selected', on ? 'true' : 'false');
    });
    $panes.each(function () {
      $(this).prop('hidden', $(this).data('pane') !== role);
    });
    if (role === 'staff') {
      $staffForm.find('input').first().trigger('focus');
    } else if (role === 'student') {
      $stuForm.find('input').first().trigger('focus');
    }
  }

  $('.seg-btn', $seg).on('click', function () {
    switchRole($(this).data('role'));
  });

  // 初始化：如果 URL 有 ?role=student / parent，或学生端被 401 踢回来
  var hash = window.location.hash || '';
  var qs = new URLSearchParams(window.location.search);
  var initRole = qs.get('role') || hash.replace('#', '');
  if (initRole && $('.seg-btn[data-role="' + initRole + '"]').length) {
    switchRole(initRole);
  }

  // ========== 共用：记住账号 ==========
  function readSaved() {
    try { return window.localStorage.getItem(storeKey) || ''; } catch (e) { return ''; }
  }
  function saveAccount(name) {
    try {
      window.localStorage.setItem(storeKey, name || '');
    } catch (e) { /* 隐私模式忽略 */ }
  }

  // ========== 共用：密码切换 ==========
  function bindPwdToggle(toggleId, inputId) {
    var $t = $('#' + toggleId);
    var $p = $('#' + inputId);
    $t.on('click', function () {
      var show = $p.attr('type') === 'password';
      $p.attr('type', show ? 'text' : 'password');
      $t.text(show ? '隐藏' : '显示').attr('aria-pressed', show ? 'true' : 'false');
      $p.trigger('focus');
    });
  }
  bindPwdToggle('pwdToggle', 'password');
  bindPwdToggle('pwdToggleStudent', 'student_pw');

  // ========== 教师 / 管理员 / 政教处 / 教官 / 班主任 表单 ==========
  (function () {
    var $form = $staffForm;
    var $username = $('#username');
    var $password = $('#password');
    var $remember = $('#rememberMe');
    var $alert = $('#formAlert');
    var $btn = $('#submitBtn');
    var nextUrl = $form.data('next') || '/api/head_teacher_workbench';
    var submitting = false;

    function showAlert(m) { $alert.text(m).addClass('is-visible'); }
    function clearAlert() { $alert.text('').removeClass('is-visible'); }
    function setLoading(v) {
      submitting = v;
      $btn.prop('disabled', v).text(v ? '登 录 中…' : '登 录');
    }

    var saved = readSaved();
    if (saved) { $username.val(saved); $remember.prop('checked', true); $password.trigger('focus'); }
    else { $username.trigger('focus'); }

    $form.on('input', 'input', clearAlert);

    $form.on('submit', function (e) {
      e.preventDefault();
      if (submitting) { return; }
      var username = $.trim($username.val());
      var password = $password.val();
      if (!username) { showAlert('请输入工号或账号'); $username.trigger('focus'); return; }
      if (!password) { showAlert('请输入密码'); $password.trigger('focus'); return; }

      clearAlert(); setLoading(true);

      $.ajax({
        url: '/api/v1/login', method: 'POST',
        contentType: 'application/json; charset=utf-8', dataType: 'json',
        data: JSON.stringify({ username: username, password: password })
      }).done(function (result) {
        if (result && result.code === 0) {
          if ($remember.is(':checked')) { saveAccount(username); }
          else { saveAccount(''); }
          window.location.href = (result.data && result.data.next) || nextUrl;
          return;
        }
        setLoading(false);
        showAlert((result && result.error) || '登录失败，请稍后重试');
        $password.val('').trigger('focus');
      }).fail(function (xhr) {
        setLoading(false);
        var message = '网络异常，请稍后重试';
        var body = xhr.responseJSON;
        if (body && body.error) { message = body.error; }
        else if (xhr.status === 403) { message = '访问被网关拦截，请重新从入口链接进入'; }
        showAlert(message);
        $password.val('').trigger('focus');
      });
    });
  })();

  // ========== 学生表单（同一 POST /api/v1/login，后端按学号识别） ==========
  (function () {
    var $form = $stuForm;
    var $no = $('#student_no');
    var $pw = $('#student_pw');
    var $alert = $('#formAlertStudent');
    var $btn = $('#submitBtnStudent');
    var nextUrl = $form.data('next') || '/api/student';
    var submitting = false;

    function showAlert(m) { $alert.text(m).addClass('is-visible'); }
    function clearAlert() { $alert.text('').removeClass('is-visible'); }
    function setLoading(v) {
      submitting = v;
      $btn.prop('disabled', v).text(v ? '登 录 中…' : '登 录');
    }

    // 记住学号（独立键）
    var saved = (function () { try { return window.localStorage.getItem(storeKey + '_stu') || ''; } catch (e) { return ''; } })();
    if (saved) { $no.val(saved); $pw.trigger('focus'); }

    $form.on('input', 'input', clearAlert);

    $form.on('submit', function (e) {
      e.preventDefault();
      if (submitting) { return; }
      var no = $.trim($no.val());
      var pw = $pw.val();
      if (!no) { showAlert('请输入学号'); $no.trigger('focus'); return; }
      if (!pw) { showAlert('请输入密码'); $pw.trigger('focus'); return; }

      clearAlert(); setLoading(true);

      $.ajax({
        url: '/api/v1/login', method: 'POST',
        contentType: 'application/json; charset=utf-8', dataType: 'json',
        data: JSON.stringify({ username: no, password: pw })
      }).done(function (result) {
        if (result && result.code === 0) {
          try { window.localStorage.setItem(storeKey + '_stu', no); } catch (e) {}
          window.location.href = (result.data && result.data.next) || nextUrl;
          return;
        }
        setLoading(false);
        var msg = (result && result.error) || '登录失败，请稍后重试';
        if (msg === '账号或密码错误') { msg = '学号或密码错误（初始密码=学号，首次登录后请修改）'; }
        showAlert(msg);
        $pw.val('').trigger('focus');
      }).fail(function (xhr) {
        setLoading(false);
        var message = '网络异常，请稍后重试';
        var body = xhr.responseJSON;
        if (body && body.error) { message = body.error; }
        else if (xhr.status === 403) { message = '访问被网关拦截，请重新从入口链接进入'; }
        showAlert(message);
      });
    });
  })();

  // ========== 家长入口 · 折叠块 ==========
  (function () {
    var $tog = $('#parentHowtoToggle');
    var $body = $('#parentHowtoBody');
    if (!$tog.length) { return; }
    $tog.on('click', function () {
      var open = !$body.prop('hidden');
      $body.prop('hidden', open);
      $tog.attr('aria-expanded', open ? 'false' : 'true');
    });
  })();
})(jQuery);
