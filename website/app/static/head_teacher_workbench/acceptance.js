/* 德育工作台部署样本 · 前端（调用真实 API，零框架）
   前端只持 userid 与目标 post_id；level / agent_id / data_scope / space_id 均由服务端下发。 */
var CTX=null, SID='', POSTS=[], CUR_DESK='home', LEVELS=[], DUN_TARGETS=[], LAST_DUN=null;
var PORTAL_GROUPS=[], PORTALS_DEF=[], PORTAL_ORDER=['teacher','headteacher','admin'];
var ENTRY=null, ENTRY_USER='zhangmin', SPACE=null, SPACE_MODULES=[];
var FED=null, FED_RESULT=null;
var COEDU=null, COEDU_RESULT=null;

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
  return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function $(id){return document.getElementById(id)}
function toast(m){var t=$('toast');t.textContent=m;t.style.display='block';clearTimeout(window._tt);
  window._tt=setTimeout(function(){t.style.display='none'},2600)}

async function api(path,body,method){
  var opt={method:method||(body?'POST':'GET'),headers:{'Content-Type':'application/json'}};
  if(body)opt.body=JSON.stringify(body);
  try{
    var r=await fetch(path,opt);
    if(r.status===401){location.href='/api/v1/login?next='+encodeURIComponent(location.pathname+location.search);return null}
    var j=await r.json();
    if(!r.ok||j.code!==0){toast('['+(j.code||r.status)+'] '+(j.error||'请求失败'));return null}
    return j.data;
  }catch(e){toast('网络错误：'+e.message);return null}
}

function pushMsg(role,text,danger){
  var d=document.createElement('div');d.className='msg '+role;
  d.innerHTML='<div class="b'+(danger?' danger':'')+'">'+text+'</div>';
  $('chat').appendChild(d);$('chat').scrollTop=$('chat').scrollHeight;
}
function sys(t){pushMsg('s',esc(t))}

function cardHtml(c){
  if(!c)return '';
  var h='<div class="cardbox"><div class="t">'+esc(c.title||c.type||'卡片')+'</div>';
  if(c.lines) h+=c.lines.map(function(x){return esc(x)}).join('<br>');
  else if(c.items) h+=c.items.map(function(x){
    return '<div class="row"><div class="v">'+esc(x.name_masked||x.student_id||'')+' ｜ '+
      esc(x.mark||'')+' ｜ '+esc(x.action||'')+' ｜ '+esc(x.status||'')+'</div></div>'}).join('');
  else if(c.posts) h+=c.posts.map(function(x){
    return '<div class="row"><div class="v">'+esc(x.post_id)+' → '+esc(x.post_name)+
      ' ／ '+esc(x.agent_id)+'（'+esc(x.level)+'）</div></div>'}).join('');
  else if(c.text) h+=esc(c.text);
  else if(c.payload) h+='<div class="mono">'+esc(JSON.stringify(c.payload,null,2))+'</div>';
  if(c.hint)h+='<div class="hint">'+esc(c.hint)+'</div>';
  if(c.status)h+='<div class="hint">状态：'+esc(c.status)+'</div>';
  return h+'</div>';
}

/* ---------------------------------------------------------------- 登录 / 职务 */
function refreshMe(){
  if(!CTX)return;
  var pend=CTX.level_pending?
    ' · <span style="color:#fca5a5">层级待确认（PC001，绑定表试挂 '+esc(CTX.level)+
    '；自动判层 '+esc(CTX.auto_level)+'）</span>':'';
  var chain=(CTX.in_chain===false)?
    ' · <span style="color:#fca5a5">不进德育推送链</span>':'';
  $('me').innerHTML='<b>【'+esc(CTX.portal_name||'—')+'】</b> 当前 <b>'+esc(CTX.name)+
    '</b>（userid '+esc(CTX.user_id)+'）· 职务 '+
    esc(CTX.post_name)+' · 智能体 '+esc(CTX.agent_id)+'（'+esc(CTX.agent_name)+'）· '+
    '<b>'+esc(CTX.level)+'</b> · 数据范围 '+esc(CTX.data_scope)+pend+chain;
}
async function loadPersons(){
  var d=await api('/api/v1/org/persons');if(!d)return;
  $('entryUser').innerHTML=d.persons.map(function(p){
    return '<option value="'+esc(p.user_id)+'">'+esc(p.name)+'（'+esc(p.user_id)+' · '+p.posts+'职'+
      (p.portal_count>1?'／'+p.portal_count+'端':'')+'）</option>'}).join('');
  PORTALS_DEF=d.portals||PORTALS_DEF;
}
async function login(userid,postId,portal){
  var useSwitch=!!(postId||portal);
  var body={userid:userid};
  if(postId)body.post_id=postId;
  if(portal)body.portal=portal;
  var d=await api('/api/v1/session/'+(useSwitch?'switch':'resolve'),body);
  if(!d)return;
  var switching=!!CTX && useSwitch;
  CTX=d.ctx;SID=CTX.session_id;
  ENTRY_USER=userid;
  $('entryUser').value=userid;
  refreshMe();
  var p=await api('/api/v1/org/posts?userid='+encodeURIComponent(userid));
  POSTS=p?p.posts:[];
  PORTAL_GROUPS=p?(p.portals||[]):[];
  renderPostList();renderPortalSel();
  if(switching||!window._greeted){
    $('chat').innerHTML='';
    sys('已按企业微信通讯录解析登录态：'+CTX.name+' → 【'+CTX.portal_name+'】'+CTX.post_name+
        ' · 装载 '+CTX.agent_id+'（'+CTX.agent_name+'）· 层级 '+CTX.level+
        ' 由服务端判定，前端不传 level／agent_id');
    sys('三端划分：教师端／班主任端／行政端；端是第一层导航、post_id 是第二层职务，三端数据互不打通');
    sys('当前成长导航为校内试用态：只读派生区；画像仅学籍／归寝／请假三类；不直连智慧校园平台');
    window._greeted=true;
    greeting();
  }
  renderChips();loadOps();
  // PC015：切换职务后空间已重建，重新读取当前空间
  if($('spaceShared'))loadSpace();
}
async function greeting(){
  var d=await api('/api/v1/chat',{session_id:SID,text:'能做什么'});
  if(d)pushMsg('a',d.reply.replace(/\n/g,'<br>'));
}
function renderPostList(){
  var groups={};
  POSTS.forEach(function(p){var k=p.portal||'admin';(groups[k]=groups[k]||[]).push(p)});
  var html='';
  PORTAL_ORDER.forEach(function(pid){
    var arr=groups[pid]||[];if(!arr.length)return;
    var g=PORTAL_GROUPS.filter(function(x){return x.portal===pid})[0]||{};
    html+='<div class="pgrp"><div class="ptitle">'+esc(g.name||pid)+'（'+arr.length+' 个职务）'+
      (CTX&&CTX.portal===pid?' · 【当前端】':'')+'</div>';
    html+=arr.map(function(p){
      var cur=p.post_id===CTX.post_id;
      return '<div class="item"><div><b>'+esc(p.post_name)+'</b>'+
        (p.level_pending?' <span class="tag a">层级待确认</span>':'')+
        (p.in_chain===0?' <span class="tag d">不进推送链</span>':'')+
        '<br><span style="font-size:12px;color:#6b7280">'+
        esc(p.post_id)+' → '+esc(p.agent_id)+'（'+esc(p.level)+
        (p.auto_level&&p.auto_level!==p.level?'；自动判层 '+esc(p.auto_level):'')+'）'+
        (cur?' · 【当前】':'')+'</span></div>'+
        (cur?'<span class="tag c">当前</span>':'<button class="btn mini" onclick="switchPost(\''+esc(p.post_id)+'\')">切换</button>')+
        '</div>'}).join('');
    html+='</div>';
  });
  $('postList').innerHTML=html||'<div class="hint">该账号无有效职务</div>';
}
function switchPost(pid){$('postModal').classList.remove('on');login(CTX.user_id,pid)}
function renderPortalSel(){
  var b=$('btnEntry');
  var n=ENTRY&&ENTRY.role_count?ENTRY.role_count:0;
  if(b)b.textContent=n?('我的角色（已自动匹配 '+n+' 个）'):'我的角色（自动匹配）';
}

/* -------- 企微角色自动匹配加载（PC014）：登录即自动进入，不出现手动选卡步骤 -------- */
function renderRoles(){
  if(!ENTRY||!ENTRY.roles)return;
  var d=ENTRY;
  $('entryRule').textContent=d.auto_rule||d.entry_rule||'';
  $('entryManages').textContent=(d.auto_note||'')+' '+(d.manages_note||'');
  $('entryFoot').textContent='当前账号：'+(d.name||'')+'（'+d.user_id+'）· 企业微信通讯录自动匹配 '+d.role_count+
    ' 个角色 · 已自动装载主职务，无需手动选择；其余角色仅就绪登记，不产生会话上下文。';
  $('entryCards').innerHTML=d.roles.map(function(r,i){
    return '<div class="entry-card'+(r.is_current?' cur':'')+'" onclick="switchRole(\''+esc(r.post_id)+'\')">'+
      '<div class="ec-no">角色 0'+(i+1)+' ／ '+d.role_count+' · '+esc(r.portal_name)+'</div>'+
      '<div class="ec-name">'+esc(r.post_name)+'</div>'+
      '<div class="ec-manages">'+esc(r.status)+' · '+esc(r.agent_id)+'</div>'+
      '<div class="ec-line">'+esc(r.one_liner||r.manages||'')+'</div>'+
      '<div class="ec-meta">'+esc(r.level)+' · '+esc(r.data_scope)+'<br>'+
        (r.in_chain?'进六级链':'不进推送链')+(r.committee_line?' · 团线单列':'')+'</div>'+
      '<div class="ec-go">'+(r.is_current?'当前已自动装载':'切换为该职务 →')+'</div>'+
    '</div>';
  }).join('');
  renderPortalSel();
}
function openRoles(){
  renderRoles();
  $('entryOverlay').classList.add('on');
}
async function autoEnter(userid){
  ENTRY_USER=userid||ENTRY_USER||'zhangmin';
  var d=await api('/api/v1/portal/auto',{userid:ENTRY_USER});
  if(!d)return;
  ENTRY=d;
  CTX=d.ctx;SID=CTX.session_id;
  SPACE=d.space||null;                    // PC015：自动匹配时已共建主职务空间
  $('entryOverlay').classList.remove('on');
  $('entryUser').value=ENTRY_USER;
  refreshMe();spaceBadge();
  var p=await api('/api/v1/org/posts?userid='+encodeURIComponent(ENTRY_USER));
  POSTS=p?p.posts:[];PORTAL_GROUPS=p?(p.portals||[]):[];
  renderPostList();renderRoles();
  $('chat').innerHTML='';
  sys('企业微信通讯录自动匹配：'+CTX.name+' 共 '+d.role_count+' 个角色，已自动装载主职务【'+CTX.portal_name+'】'+
      CTX.post_name+' · '+CTX.agent_id+'（'+CTX.agent_name+'），无需手动选择');
  sys('其余 '+(d.role_count-1)+' 个角色已自动匹配就绪，可在「我的角色」或职务列表直接切换；'+
      '切换职务仍作废旧会话、清空待确认写入与催办草稿，端间数据互不打通');
  sys('三端按管理对象区分：教师端管学生日常学习／班主任端管学生综合／行政端管老师与班主任');
  sys('共建空间：秘书智能体随本职务跟随工作台共建一个空间，对话与工作台模块共享上下文；切换职务即归档旧空间、重建新空间，空间间互不打通');
  sys('同类横向协同：同一类角色的智能体可横向只读搜索聚合脱敏数字，聚合结果不写回任何空间的共享上下文、不带入他人上下文（PC016）');
  sys('协同教育：教师端可把所代课程班级的平时考试／学习状态自动定向推送给班主任，非隶属管理、只协同育人，不进六级链、不打通三端、不污染上下文（PC017）');
  sys('当前成长导航为校内试用态：只读派生区；画像仅学籍／归寝／请假三类；不直连智慧校园平台');
  window._greeted=true;greeting();
  renderChips();renderDesk(CUR_DESK);loadOps();loadPortals();loadSpace();
}
async function switchRole(postId){
  if(!postId)return;
  await login(ENTRY_USER,postId);
  if(ENTRY&&ENTRY.roles)ENTRY.roles.forEach(function(r){r.is_current=(r.post_id===postId)});
  renderRoles();
  $('entryOverlay').classList.remove('on');
}
async function switchRoleAs(userid,postId){
  await autoEnter(userid);
  await switchRole(postId);
}
/* 兼容旧调用名：不再作为进入路径，均落到自动匹配或职务切换 */
async function openEntry(userid){
  if(userid&&userid!==ENTRY_USER)return autoEnter(userid);
  openRoles();
}
async function enterPortal(pid){
  if(!pid)return;
  var r=ENTRY&&ENTRY.roles?ENTRY.roles.filter(function(x){return x.portal===pid})[0]:null;
  if(r)return switchRole(r.post_id);
  return autoEnter(ENTRY_USER);
}
async function enterAs(userid,pid){
  await autoEnter(userid);
  if(ENTRY&&ENTRY.roles){
    var r=ENTRY.roles.filter(function(x){return x.portal===pid})[0];
    if(r)await switchRole(r.post_id);
  }
}

/* ---------------------------------------------------------------- 秘书对话 */
var CHIPS=[
  ['本周周报','生成本周周报'],['需关注','本班需关注有谁'],['记德育','记一笔：张××上课玩手机扣2分'],
  ['查成绩','查一下成绩学情'],['查特长','看看特长兴趣'],['查交友','看看本班交友情况'],
  ['目标跟进','六级目标进度'],['工具就绪','工具就绪度'],['切换职务','我的职务'],
  ['待确认红点','本周待确认红点'],
  ['共建空间','共建空间'],['横向协同','横向协同'],['协同教育','协同教育'],['本级职责','能做什么']
];
function renderChips(){
  $('chips').innerHTML=CHIPS.map(function(c){
    return '<button onclick="send(\''+esc(c[1])+'\')">'+esc(c[0])+'</button>'}).join('');
}
async function send(text){
  text=text==null?$('inp').value.trim():text;
  if(!text)return;
  $('inp').value='';pushMsg('u',esc(text));
  var d=await api('/api/v1/chat',{session_id:SID,text:text});
  if(!d)return;
  pushMsg('a',d.reply.replace(/\n/g,'<br>')+cardHtml(d.card),d.kind==='offline'||d.kind==='forbidden');
  if(d.view)switchView(d.view);
  if(d.card&&d.card.type==='weekly_report')window._reportId=d.card.report_id;
  if(d.pending_id)sys('已生成写入草稿；请点「确认写入」或「取消」（含糊回复需二次确认）');
  // PC015：秘书对话写入共享上下文，工作台立即可见
  if(d.space_shared&&$('spaceShared'))loadSpace();
}
async function confirmWrite(decision){
  var d=await api('/api/v1/write/confirm',{session_id:SID,decision:decision});
  if(d)pushMsg('a',d.reply.replace(/\n/g,'<br>')+cardHtml(d.card));
}

/* ---------------------------------------------------------------- 视图切换 */
function switchView(v){
  document.querySelectorAll('.tabs button').forEach(function(b){b.classList.toggle('on',b.dataset.v===v)});
  document.querySelectorAll('.view').forEach(function(x){x.classList.toggle('on',x.id==='view'+v.charAt(0).toUpperCase()+v.slice(1))});
  if(v==='desk')renderDesk(CUR_DESK);
  if(v==='todo')loadTodo();
  if(v==='space')loadSpace();
  if(v==='federation')loadFederation();
  if(v==='coedu')loadCoedu();
  if(v==='pilot')loadPilot();
  if(v==='portals')loadPortals();
  if(v==='flow')loadFlow();
  if(v==='ops')loadOps();
}

/* ---------------------------------------------------------------- 德育工作台 */
var DTABS=[['home','首页'],['roster','成长档案'],['att','出勤统计'],['warn','学情预警'],
           ['moral','德育量化'],['biz','班务减负'],['comm','家校协同'],['backup','数据备份']];
function renderDesk(tab){
  CUR_DESK=tab;
  // PC015：工作台切模块即写共享上下文 focus，秘书智能体在同一空间内立即可见
  var label=(DTABS.filter(function(x){return x[0]===tab})[0]||[tab,tab])[1];
  api('/api/v1/space/focus',{session_id:SID,module:label,
    class_id:(CTX&&CTX.class_ids&&CTX.class_ids[0])||''}).then(function(d){
      if(d&&$('spaceShared'))loadSpace();
    });
  $('dtabs').innerHTML=DTABS.map(function(p){
    return '<button class="'+(p[0]===tab?'on':'')+'" onclick="renderDesk(\''+p[0]+'\')">'+esc(p[1])+'</button>'}).join('');
  var body=$('deskBody');body.innerHTML='<div class="card"><h3>'+esc(DTABS.filter(function(x){return x[0]===tab})[0][1])+'</h3><div class="hint">加载中…</div></div>';
  var qs='?session_id='+encodeURIComponent(SID);
  if(tab==='home')deskHome(body,qs);
  else if(tab==='roster')deskRoster(body,qs);
  else if(tab==='att')deskAtt(body,qs);
  else if(tab==='warn')deskWarn(body,qs);
  else if(tab==='moral')deskMoral(body,qs);
  else if(tab==='biz')deskBiz(body);
  else if(tab==='comm')deskComm(body);
  else deskBackup(body,qs);
}
function rowsHtml(rows){return rows.map(function(r){
  return '<div class="row"><div class="k">'+esc(r[0])+'</div><div class="v">'+esc(r[1])+'</div></div>'}).join('')}
function card(title,inner,hint){return '<div class="card"><h3>'+title+'</h3>'+inner+(hint?'<div class="hint">'+hint+'</div>':'')+'</div>'}

async function deskHome(body,qs){
  var [ov,rd]=await Promise.all([api('/api/v1/growth/overview'+qs),api('/api/v1/growth/readiness'+qs)]);
  var n=ov?ov.data:{};
  body.innerHTML=card('班级概览 · 28 号（只读派生区，不查 answers／scores）',
    rowsHtml([['出勤率',n.attendance_rate],['需关注',n.attention_count+' 人'],
      ['四维失衡',n.balance_unbalanced+' 人'],['角色登记',n.role_registered],
      ['请假数',n.leave_count==null?'暂不可用':n.leave_count],['口径',n.leave_reconcile],
      ['数据源',n.source]]),
    '班主任工作四项＝成绩／特长／交友／目标制定（工作口径）；≠ 成长导航「四维平衡」（学习／交友／兴趣／健康）；≠ 学生「六级目标」')+
    card('当前工具就绪度',
      rowsHtml([['MCP 服务',rd.data.mcp_service],['已跑通工具',rd.data.mcp_tools.map(function(t){return t.name}).join('／')],
        ['画像覆盖',rd.data.coverage_ready.join('／')],['尚未接入',rd.data.coverage_pending.join('／')],
        ['Token 范围',rd.data.token_scope+(rd.data.token_scope_ok?'（合规）':'（一票否决）')],
        ['不直连平台',String(rd.data.no_direct_platform_access)]]),
      rd.data.no_full_profile);
}
async function deskRoster(body,qs){
  var [a,d]=await Promise.all([api('/api/v1/growth/attention'+qs),api('/api/v1/growth/derived'+qs+'&student_id=S007')]);
  var items=a?a.data.items:[];
  body.innerHTML=card('需关注清单 · 29 号（只含标记＋建议动作，不含原因与分数）',
    '<div class="tblwrap"><table><tr><th>学生</th><th>标记</th><th>建议动作</th><th>状态</th></tr>'+
    items.map(function(x){return '<tr><td>'+esc(x.name_masked)+'</td><td>'+esc(x.mark)+'</td><td>'+esc(x.action)+'</td><td>'+esc(x.status)+'</td></tr>'}).join('')+
    '</table></div>',a?a.data.note:'')+
    card('学生派生视图 · 30 号（心理内容不过河）',
      '<div class="mono">'+esc(JSON.stringify(d?d.data:{},null,2))+'</div>',
      '个人明细由学生本人在学生端查看，或经学生主动分享 A／B／C 授权片段（带水印、只读、有效期≤1学期、可撤销、访问留痕）；D 心理状态禁止');
}
async function deskAtt(body,qs){
  var [unready,ready,nums]=await Promise.all([
    api('/api/v1/mcp/call',{session_id:SID,tool:'list_class_unreturned',date:'2026-11-11'}),
    api('/api/v1/mcp/call',{session_id:SID,tool:'list_class_unreturned',date:'2026-11-10'}),
    api('/api/v1/growth/numbers'+qs)]);
  body.innerHTML=card('归寝 · 数据就绪日（未就绪 ≠ 未归）',
    '<div class="row"><div class="k">查询 11-11</div><div class="v"><b class="bad">'+esc(unready&&unready.data?unready.data.status:'—')+'</b> · 查寝数据未生成，不把未生成当未归</div></div>'+
    '<div class="row"><div class="k">查询 11-10</div><div class="v"><b class="good">'+esc(ready&&ready.data?ready.data.status:'—')+'</b> · 未归 '+((ready&&ready.data&&ready.data.unreturned)||[]).length+' 人（姓名掩码）</div></div>'+
    '<div class="mono">'+esc((unready&&unready.data&&unready.data.note)||'')+'</div>',
    '连续未归链条遇缺口日提示截断、不补算；所有派生数据标注「智慧校园平台同步」')+
    card('周报 4 数字 · 降级不估算',
      '<div class="mono">'+esc(JSON.stringify(nums?nums.data:{},null,2))+'</div>',
      '任一数据域失败或口径异常即标注「暂不可用」，禁止旧值或估算值填充；本级报告暂停该数字');
}
async function deskWarn(body,qs){
  var [w,a]=await Promise.all([api('/api/v1/mcp/call',{session_id:SID,tool:'get_warning_summary'}),
                               api('/api/v1/report/watchlist'+qs)]);
  var d=w?w.data:{};
  body.innerHTML=card('预警汇总（只写「需人工关注」与事实，不写结论、不带请假事由）',
    '<div class="mono">'+esc(JSON.stringify(d,null,2))+'</div>',
    '预警文案不进心理明细；请假事由、家长电话不进预警与大模型上下文')+
    card('需关注清单卡片',
      (a&&a.data&&a.data.card?a.data.card.items||[]:[]).map(function(x){
        return '<div class="row"><div class="v">'+esc(x.name_masked)+' ｜ '+esc(x.mark)+' ｜ '+esc(x.action)+'</div></div>'}).join('')||'<div class="hint">暂无数据</div>',
      '不含原因与分数；不得用于分班／分专业／评优／处分，不得在班级公开');
}
async function deskMoral(body,qs){
  var rec=await api('/api/v1/write/records');
  body.innerHTML=card('德育量化 · 写入两段式（先回显，确认后才落库）',
    '<div class="row"><div class="k">成长轨</div><div class="v">仅六类正向记录：表扬／进步／参与／志愿服务／岗位履职／合作任务</div></div>'+
    '<div class="row"><div class="k">底线轨</div><div class="v">扣分／通报／处分走校纪台账，两轨不串用</div></div>'+
    '<div class="row"><div class="k">人审点</div><div class="v">写入回显确认、周报确认归档</div></div>'+
    '<div style="margin-top:10px"><button class="btn mini" onclick="send(\'记一笔：张××上课玩手机扣2分\')">演示生成写入草稿</button> '+
    '<button class="btn mini gray" onclick="confirmWrite(\'确认\')">确认</button> '+
    '<button class="btn mini gray" onclick="confirmWrite(\'取消\')">取消</button></div>',
    '含糊回复需二次确认；未确认的草稿不落业务库')+
    card('已确认落库记录（三元组留痕）',
      '<div class="tblwrap"><table><tr><th>时间</th><th>userid</th><th>post_id</th><th>agent_id</th><th>类型</th></tr>'+
      (rec?rec.records:[]).map(function(r){return '<tr><td>'+esc(r.ts)+'</td><td>'+esc(r.user_id)+'</td><td>'+esc(r.post_id)+'</td><td>'+esc(r.agent_id)+'</td><td>'+esc(r.kind)+'</td></tr>'}).join('')+
      '</table></div>');
}
function deskBiz(body){
  body.innerHTML=card('交互分级（图形化操作保留界面，只把文字与数据类操作对话化）',
    rowsHtml([
      ['保留界面','课程表／座位表／值日表／批量导入导出／成绩录入表单／积分榜／数据备份'],
      ['已对话化','周报生成／待办登记／德育加减分／沟通家访留痕／单笔出勤补记／需关注清单查询／工作四项派生区查询'],
      ['写入规则','所有写入先生成回显卡，明确确认后才落库；含糊回复二次确认'],
      ['复杂操作','给出口：跳转工作台对应模块，不在对话里堆叠表单'],
      ['降级','任一数据域失败或口径异常标注「暂不可用」，不估算、不填旧值']]),
    '试点原型三项决策：教师数据可云端；学生数据仅脱敏汇总上云；图形化操作保留界面');
}
function deskComm(body){
  body.innerHTML=card('家校协同 · 人工通道边界',
    rowsHtml([
      ['不纳入系统','校园安全事件／舆情与负面传播／重大心理危机与自伤风险／涉法涉诉、师德师风、纪检线索'],
      ['处置方式','责任人电话直报或当面汇报；确需记录走线下纸质流程，不回流数字系统'],
      ['秘书行为','命中此类关键词统一回退到电话／当面话术，不生成、不转述、不留系统痕迹'],
      ['越级抄送','已取消越级上报／抄送入口；常规上行仍逐级自动推送'],
      ['敏感字段','家长电话／住址／请假事由／身份证／学籍号不进模型上下文（字段白名单）']]),
    '安全／舆情类拦截率 100%、零系统留痕；可在秘书对话输入「安全事故」查看固定话术');
}
async function deskBackup(body,qs){
  var [r,h]=await Promise.all([api('/api/v1/growth/readiness'+qs),api('/api/v1/health/readiness')]);
  body.innerHTML=card('数据分级与字段白名单',
    rowsHtml([
      ['教师业务数据','可云端，按职务行级隔离'],
      ['学生数据','仅脱敏汇总上云；姓名一律掩码'],
      ['字段白名单',r?r.data.field_whitelist.join('、'):''],
      ['字段黑名单',r?r.data.field_blacklist.join('、'):''],
      ['派生区','教师端物理不查 answers／scores，越权 HTTP 403 并写审计'],
      ['分享授权','学生主动发起 A／B／C；D 心理状态禁止；带水印只读可撤销留痕']]),
    '大模型不直连智慧校园平台，只访问成长导航数据服务 API')+
    card('部署基线与运行态',
      rowsHtml([
        ['代码基线',r?r.data.code_baseline:''],
        ['同步节奏','Campus-Fast 每15分钟（归寝／请假）＋ Campus-Daily 每日02:10（全量＋对账）'],
        ['运行状态',h?h.state+'（'+h.done+'/'+h.total+'）':''],
        ['形态','单机双库 growth_nav／growth_nav_psych ＋ 仅校内网 ＋ DOCS_ENABLED=false']]),
      '每日对账学生数／班级数／归寝条数／请假条数，差异=0；当前为校内试用态，九项前置未完成前不得作为正式数据源');
}

/* ---------------------------------------------------------------- 推送流 / 催办 */
async function loadFlow(){
  var [f,t,o,l]=await Promise.all([api('/api/v1/push/flow'),api('/api/v1/dun/targets?session_id='+encodeURIComponent(SID)),
    api('/api/v1/wecom/outbox'),api('/api/v1/dun/list')]);
  if(f){
    LEVELS=f.levels;
    $('chain').innerHTML=f.levels.map(function(L){
      var s=f.schedule.filter(function(x){return x.level===L.id})[0]||{};
      return '<div class="lv"><b>'+esc(L.id)+' '+esc(L.name)+'</b><div>'+esc(L.scope)+'</div>'+
        '<div class="f">'+esc(s.cron||L.freq)+' → '+esc(L.out)+'</div></div>'}).join('');
    $('flowRule').textContent=f.rule+'；'+f.committee_note;
    $('pushLevel').innerHTML=f.levels.map(function(L){return '<option value="'+L.id+'">'+L.id+' '+esc(L.name)+'</option>'}).join('');
  }
  if(t){DUN_TARGETS=t.targets;$('dunTarget').innerHTML=t.targets.length?
    t.targets.map(function(x){return '<option value="'+esc(x.user_id)+'">'+esc(x.name)+'（'+esc(x.user_id)+' · '+esc(x.level)+'）</option>'}).join(''):
    '<option value="">本级无直接下级</option>'}
  if(o)$('outbox').innerHTML='<table><tr><th>时间</th><th>接收人</th><th>类型</th><th>模式</th><th>结果</th><th>摘要</th></tr>'+
    o.messages.map(function(m){return '<tr><td>'+esc(m.ts)+'</td><td>'+esc(m.to_user)+'</td><td>'+esc(m.msg_type)+'</td><td>'+esc(m.mode)+'</td><td>'+esc(m.result)+'</td><td>'+esc((m.payload.textcard||{}).title||(m.payload.text||{}).content||'')+'</td></tr>'}).join('')+'</table>';
  if(l)$('dunList').innerHTML='<table><tr><th>ID</th><th>发起</th><th>对象</th><th>层级</th><th>状态</th><th>内容</th><th>时限</th></tr>'+
    l.duns.map(function(d){return '<tr><td>'+esc(d.id)+'</td><td>'+esc(d.from_user_id)+'</td><td>'+esc(d.to_user_id)+'</td><td>'+esc(d.from_level)+'→'+esc(d.to_level)+'</td><td>'+esc(d.status)+'</td><td>'+esc(d.content)+'</td><td>'+esc(d.deadline||'')+'</td></tr>'}).join('')+'</table>';
}
async function doPush(){
  var d=await api('/api/v1/push/run',{session_id:SID,push_level:$('pushLevel').value,trigger:'manual'});
  if(d)$('pushResult').innerHTML='已生成 <b>'+esc(d.level)+' '+esc(d.period)+'</b> 报告并自动推送至 '+
    esc(d.targets.join('、')||'（本级为最高层，无上行）')+'；'+esc(d.note);
  loadFlow();
}
async function dunEcho(){
  var d=await api('/api/v1/dun/create',{session_id:SID,to_userid:$('dunTarget').value,
    content:$('dunText').value||'请于今日17:00前反馈归寝异常处置结果'});
  if(d){LAST_DUN=d.id;$('dunResult').innerHTML='催办回显已生成：<b>'+esc(d.id)+'</b>（'+esc(d.from_level||CTX.level)+'→'+esc(d.to_level)+'）。'+esc(d.hint)}
}
async function dunConfirm(){
  var d=await api('/api/v1/dun/confirm',{session_id:SID,dun_id:LAST_DUN||''});
  if(d)$('dunResult').innerHTML='已确认下达并发送企微卡片至 '+esc(d.sent_to);
  loadFlow();
}
async function dunReply(){
  if(!LAST_DUN)return toast('请先生成催办回显');
  var d=await api('/api/v1/dun/reply',{session_id:SID,dun_id:LAST_DUN,text:'已核实并反馈处置结果'});
  if(d)$('dunResult').innerHTML='下级限时反馈完成（状态 '+esc(d.status)+'）';
  loadFlow();
}
async function escalate(){
  var d=await api('/api/v1/dun/escalate',{});
  toast('超时升级提醒：'+(d&&d.escalated?d.escalated.length:0)+' 条');loadFlow();
}

/* ---------------------------------------------------------------- 运行与验收 */
async function loadOps(){
  var [h,rd,g,ag,au,rl,cf]=await Promise.all([
    api('/api/v1/health'),api('/api/v1/health/readiness'),
    api('/api/v1/growth/readiness?session_id='+encodeURIComponent(SID)),
    api('/api/v1/agent/registry'),api('/api/v1/audit'),api('/api/v1/redline'),
    api('/api/v1/org/conflicts')]);
  if(h){
    $('healthStat').innerHTML=
      '<div><b>'+esc(h.settings.wecom_mode)+'</b>企业微信模式</div>'+
      '<div><b>'+esc(h.readiness.state)+'</b>运行状态</div>'+
      '<div><b>'+h.readiness.done+'/9</b>上线前置</div>'+
      '<div><b>'+esc(h.settings.token_scope)+'</b>Token 范围</div>'+
      '<div><b>'+esc(h.settings.growth_nav_mode)+'</b>数据源</div>'+
      '<div><b>'+esc(h.settings.docs_enabled)+'</b>DOCS_ENABLED</div>';
  }
  if(rd)$('readinessTbl').innerHTML='<table><tr><th>项</th><th>名称</th><th>状态</th></tr>'+
    rd.items.map(function(x){return '<tr><td>'+esc(x.key)+'</td><td>'+esc(x.name)+'</td><td class="'+(x.done?'good':'bad')+'">'+
      (x.done?'已完成':'待完成')+'</td></tr>'}).join('')+'</table>';
  if(cf){
    $('conflictTbl').innerHTML='<table><tr><th>编号</th><th>议题</th><th>当前处理</th><th>责任</th><th>状态</th></tr>'+
      cf.items.map(function(x){var done=/已确认/.test(x.status||'');
        return '<tr><td>'+esc(x.id)+'</td><td><b>'+esc(x.topic)+'</b><br><span style="font-size:11px;color:#6b7280">'+esc(x.detail)+'</span></td><td>'+esc(x.current)+'</td><td>'+esc(x.owner)+'</td><td class="'+(done?'good':'bad')+'">'+esc(x.status)+'</td></tr>'}).join('')+
      '</table><div style="margin-top:8px;font-size:12px;color:#6b7280">涉及职务（绑定表优先于自动判层）：</div>'+
      '<table><tr><th>post_id</th><th>职务</th><th>绑定层级</th><th>自动判层</th><th>层级来源</th><th>推送链</th></tr>'+
      cf.posts.map(function(p){return '<tr><td>'+esc(p.post_id)+'</td><td>'+esc(p.post_name)+'</td><td>'+esc(p.level)+
        (p.level_pending?' <span class="tag a">待确认</span>':'')+'</td><td>'+esc(p.auto_level)+'</td><td>'+esc(p.level_source)+
        '</td><td>'+(p.in_chain?'是':'否')+'</td></tr>'}).join('')+'</table>';
    $('conflictRule').textContent=cf.rule;
  }
  if(g)$('growthReadiness').textContent=
    'MCP 服务：'+g.data.mcp_service+'\n'+
    '已跑通只读工具：\n'+g.data.mcp_tools.map(function(t){return '  · '+t.name+' → '+t.returns}).join('\n')+'\n'+
    '画像覆盖：'+g.data.coverage_ready.join('／')+'\n'+
    '尚未接入：'+g.data.coverage_pending.join('／')+'\n'+
    g.data.no_full_profile+'\n'+
    '权限风险：'+g.data.permission_risk+'\n'+
    '数据就绪日：'+g.data.data_ready_note+'\n'+
    '口径：'+g.data.reconcile_note+'\n'+
    '字段白名单：'+g.data.field_whitelist.join('、')+'\n'+
    '字段黑名单：'+g.data.field_blacklist.join('、')+'\n'+
    '不直连平台：'+g.data.no_direct_platform_access+'\n'+
    '代码基线：'+g.data.code_baseline+'\n'+
    '拦截计数：'+JSON.stringify(rl?rl.counts:[]);
  if(ag)$('agentRegistry').innerHTML='<table><tr><th>agent_id</th><th>post_id</th><th>层级</th><th>名称</th><th>状态</th></tr>'+
    ag.agents.map(function(a){return '<tr><td>'+esc(a.agent_id)+'</td><td>'+esc(a.post_id)+'</td><td>'+esc(a.level)+'</td><td>'+esc(a.agent_name)+'</td><td>'+esc(a.status)+'</td></tr>'}).join('')+'</table>';
  if(au)$('auditTbl').innerHTML='<table><tr><th>时间</th><th>userid</th><th>post_id</th><th>agent_id</th><th>动作</th><th>结果</th></tr>'+
    au.logs.slice(0,30).map(function(a){return '<tr><td>'+esc(a.ts)+'</td><td>'+esc(a.user_id)+'</td><td>'+esc(a.post_id)+'</td><td>'+esc(a.agent_id)+'</td><td>'+esc(a.action)+'</td><td>'+esc(a.result)+'</td></tr>'}).join('')+'</table>';
}

/* ---------------------------------------------------------------- 2607 试点班 */
async function loadPilot(){
  var [sp,cl]=await Promise.all([
    api('/api/v1/pilot/snapshot?class_id=2607'),
    api('/api/v1/pilot/classes')]);
  if(!sp)return;
  var s=sp.snapshot, cf=sp.conflicts||[];
  $('pilotIntro').textContent='数据源：'+s.source_system+'（'+s.pulled_at+' 拉取）· '+
    '只读贴源聚合接口 '+s.source_api+' · 秘书不直连智慧校园平台。'+
    '仅落地聚合数字＋合成掩码名单，真实姓名／学号／宿舍／家长电话不进样本。';
  $('pilotStat').innerHTML=
    '<div><b>'+s.size+'</b>在读学生</div>'+
    '<div><b>'+s.boys+'／'+s.girls+'</b>男／女</div>'+
    '<div><b>'+s.boarding+'／'+s.day+'</b>住宿／走读</div>'+
    '<div><b>'+s.ready_date+'</b>唯一数据就绪日</div>'+
    '<div><b>'+s.warning.count+'</b>连续未归预警</div>'+
    '<div><b>'+s.leave_table_count+'</b>请假表记录</div>';
  $('pilotDorm').innerHTML='<table><tr><th>项</th><th>值</th><th>说明</th></tr>'+
    [['已归',s.dorm.returned,'数据就绪日 '+s.ready_date],
     ['晚归',s.dorm.late,'—'],['未归',s.dorm.unreturned,'异常名单 '+s.dorm.anomaly_count+' 人'],
     ['缺信息',s.dorm.missing,'—'],['归寝聚合 leave',s.dorm.leave,'与请假表口径比对']]
    .map(function(r){return '<tr><td>'+esc(r[0])+'</td><td><b>'+esc(r[1])+'</b></td><td>'+esc(r[2])+'</td></tr>'}).join('')+
    '</table>';
  $('pilotReadyNote').textContent=s.dorm_ready_note;
  $('pilotWarn').innerHTML='<table><tr><th>项</th><th>值</th><th>处置</th></tr>'+
    [['连续未归预警',s.warning.count,'需人工关注'],
     ['超期未返校',0,'无需处置'],['月请假频繁',0,'无需处置'],
     ['请假表（病假·已归校）',s.leave_table_count,'口径未对齐 → 暂停该数字'],
     ['归寝聚合 leave',s.dorm_leave_count,'—']]
    .map(function(r){return '<tr><td>'+esc(r[0])+'</td><td><b>'+esc(r[1])+'</b></td><td>'+esc(r[2])+'</td></tr>'}).join('')+
    '</table>';
  $('pilotReconcile').textContent=(s.reconcile_conflict?'【已命中红线】':'')+s.reconcile_note;
  if(cl){
    $('pilotClasses').innerHTML='<table><tr><th>班级</th><th>口径</th><th>人数</th><th>拉取/生成</th><th>就绪日</th><th>待确认</th></tr>'+
      cl.classes.map(function(c){return '<tr><td><b>'+esc(c.class_id)+'</b><br>'+esc(c.name)+'</td><td>'+esc(c.kind)+
        '</td><td>'+esc(c.size)+'</td><td>'+esc(c.pulled_at)+'</td><td>'+esc(c.ready_date||'—')+'</td><td>'+
        (c.reconcile_conflict?'口径未对齐 ':'')+(c.derived_pending?'派生区未绑定':'')+'</td></tr>'}).join('')+'</table>';
    $('pilotClassRule').textContent=cl.rule;
  }
  $('pilotConflicts').innerHTML='<table><tr><th>编号</th><th>议题</th><th>当前处理</th><th>责任</th><th>状态</th></tr>'+
    cf.map(function(x){var done=/已确认/.test(x.status||'');
      return '<tr><td>'+esc(x.id)+'</td><td><b>'+esc(x.topic)+'</b><br><span style="font-size:11px;color:#6b7280">'+esc(x.detail)+
      '</span></td><td>'+esc(x.current)+'</td><td>'+esc(x.owner)+'</td><td class="'+(done?'good':'bad')+'">'+esc(x.status)+'</td></tr>'}).join('')+'</table>';
  var p=await api('/api/v1/org/posts?userid=Tiao');
  if(p)$('pilotPosts').innerHTML='<table><tr><th>post_id</th><th>职务</th><th>层级</th><th>智能体</th><th>推送链</th><th>团线</th></tr>'+
    p.posts.map(function(x){return '<tr><td>'+esc(x.post_id)+'</td><td>'+esc(x.post_name)+'</td><td>'+esc(x.level)+
      (x.level_pending?' <span class="tag a">待确认</span>':'')+'</td><td>'+esc(x.agent_id)+'</td><td>'+
      (x.in_chain?'是':'否')+'</td><td>'+(x.committee_line?'单列':'—')+'</td></tr>'}).join('')+'</table>';
}
async function loginAsPilot(userid){await autoEnter(userid||'Tiao')}
async function switchPilotPost(postId){
  var m={'teacher':'p_xhc_teacher','headteacher':'p_xhc_bzr_2607','admin':'p_xhc_tw'};
  await switchRoleAs('Tiao',m[postId]||postId||'p_xhc_bzr_2607');
}

/* ---------------------------------------------------------------- 共建空间（PC015） */
function spaceBadge(){
  var b=$('spaceBadge');if(!b)return;
  b.textContent=SPACE&&SPACE.space_id?
    '空间：'+SPACE.post_name+' · '+SPACE.space_id:'空间：—';
  b.title=SPACE?SPACE.rule||'':'';
}
async function loadSpace(){
  if(!SID)return;
  var [v,all,cf]=await Promise.all([
    api('/api/v1/space?session_id='+encodeURIComponent(SID)),
    api('/api/v1/spaces?userid='+encodeURIComponent(CTX?CTX.user_id:'')),
    api('/api/v1/org/conflicts')]);
  if(!v)return;
  SPACE=v;SPACE_MODULES=v.workbench_modules||[];spaceBadge();
  $('spaceRule').textContent=v.rule||'';
  $('spaceNote').textContent=v.note||'';
  $('spaceIso').textContent=v.isolation||'';
  $('spaceStat').innerHTML=
    '<div><b>'+esc(v.post_name)+'</b>当前角色</div>'+
    '<div><b>'+esc(v.agent_id)+'</b>秘书智能体</div>'+
    '<div><b>'+esc(v.portal_name)+'</b>工作台端</div>'+
    '<div><b>'+Object.keys(v.shared||{}).length+'</b>共享上下文键</div>'+
    '<div><b>'+v.event_count+'</b>共建留痕</div>'+
    '<div><b>'+esc(v.level)+'</b>层级（服务端判定）</div>';
  $('spaceMembers').innerHTML='<table><tr><th>成员</th><th>标识</th><th>随角色的职责</th></tr>'+
    v.members.map(function(m){return '<tr><td><b>'+esc(m.role)+'</b></td><td>'+esc(m.name)+
      '<br><span style="font-size:11px;color:#6b7280">'+esc(m.id)+'</span></td><td>'+
      esc(m.duty)+'</td></tr>'}).join('')+'</table>';
  var sh=v.shared||{};
  var keys=Object.keys(sh);
  $('spaceShared').innerHTML=keys.length?
    '<table><tr><th>共享上下文键</th><th>值（结构化·脱敏）</th></tr>'+keys.map(function(k){
      return '<tr><td><b>'+esc(k)+'</b></td><td>'+esc(typeof sh[k]==='object'?JSON.stringify(sh[k]):sh[k])+'</td></tr>'
    }).join('')+'</table>':'<div class="hint">暂无共建记录：切一次工作台模块，或问秘书「共建空间」后即可看到共享上下文。</div>';
  $('spaceSharedFields').textContent='白名单字段：'+(v.shared_fields||[]).join('／')+
    '；身份／权限字段、自由文本、字段黑名单一律不入空间。';
  $('spaceModuleBtns').innerHTML=(v.workbench_modules||[]).map(function(m){
    return '<button class="btn mini gray" onclick="spaceFocus(\''+esc(m)+'\')">'+esc(m)+'</button>'}).join('')||'<span class="hint">本端无模块</span>';
  $('spaceEvents').innerHTML='<table><tr><th>时间</th><th>共建方</th><th>写入字段</th><th>结果</th></tr>'+
    (v.events||[]).map(function(e){return '<tr><td>'+esc(e.ts)+'</td><td>'+
      (e.source==='secretary'?'秘书智能体':'工作台')+'</td><td>'+esc(e.fields||'—')+
      '</td><td>'+esc(e.result)+'</td></tr>'}).join('')+'</table>';
  if(all){
    $('spaceList').innerHTML='<table><tr><th>角色／职务</th><th>端</th><th>空间状态</th><th>共享键</th></tr>'+
      all.spaces.map(function(x){return '<tr><td><b>'+esc(x.post_name)+'</b>'+
        (x.is_current?' <span class="tag c">当前</span>':'')+'<br><span style="font-size:11px;color:#6b7280">'+
        esc(x.agent_id)+' · '+esc(x.level)+(x.space_id?' · '+esc(x.space_id):'')+'</span></td><td>'+
        esc(x.portal_name)+'</td><td>'+esc(x.status)+'</td><td>'+
        esc((x.shared_keys||[]).join('、')||'—')+'</td></tr>'}).join('')+'</table>';
  }
  if(cf){
    var rows=(cf.items||[]).filter(function(x){return /^PC01[3-5]$/.test(x.id)});
    $('spaceConflicts').innerHTML='<table><tr><th>编号</th><th>议题</th><th>当前处理</th><th>状态</th></tr>'+
      rows.map(function(x){var done=/已确认/.test(x.status||'');
        return '<tr><td>'+esc(x.id)+'</td><td><b>'+esc(x.topic)+'</b><br>'+
          '<span style="font-size:11px;color:#6b7280">'+esc(x.detail)+'</span></td><td>'+
          esc(x.current)+'</td><td class="'+(done?'good':'bad')+'">'+esc(x.status)+'</td></tr>'}).join('')+'</table>';
  }
}
async function spaceFocus(module){
  var d=await api('/api/v1/space/focus',{session_id:SID,module:module,
    class_id:(CTX&&CTX.class_ids&&CTX.class_ids[0])||''});
  if(d)$('spaceWriteResult').innerHTML='工作台模块【'+esc(module)+'】已写入共享上下文 focus_module／focus_class／module_hits；'+
    '秘书智能体在同一空间内立即可见。当前 updated_by＝'+esc(d.updated_by||'workbench');
  loadSpace();
}
async function spaceWriteEvent(){
  var d=await api('/api/v1/space/event',{session_id:SID,
    patch:{ready_date:'2026-11-11',reconcile:'请假与归寝口径未对齐→暂停该数字',last_card:'watchlist_digest'}});
  if(d)$('spaceWriteResult').innerHTML='工作台已写结构化上下文：ready_date／reconcile／last_card（均属白名单）；'+
    '共 '+Object.keys(d.shared||{}).length+' 个共享键。';
  loadSpace();
}
async function spaceTryForbidden(){
  var d=await api('/api/v1/space/event',{session_id:SID,
    patch:{parent_phone:'13800000000',level:'L6',text:'学生家长电话原文'}});
  $('spaceWriteResult').innerHTML=d?'【未拦截，异常】':'【已拒绝】家长电话／level／自由文本均不属共享上下文白名单，服务端返回 403 并写审计；零留痕红线保持。';
  loadSpace();
}

/* ---------------------------------------------------------------- 同类横向协同（PC016） */
var FED_COLS={
  roster:['post_name','agent_id','level','in_chain','committee_line','level_pending','class_ids','data_scope','is_self'],
  overview:['post_name','class_id','size','attendance_rate','attention_count','balance_unbalanced','leave_count','leave_reconcile','available','reason'],
  dorm:['post_name','class_id','warning_count','dorm_anomaly','degraded','dorm_note','leave_note','available','reason'],
  readiness:['post_name','class_id','ready_date','reconcile_conflict','derived_pending','coverage_ready','no_full_profile','available','reason']
};
function fedCell(v){
  if(v==null)return '—';
  if(typeof v==='object')return JSON.stringify(v);
  if(typeof v==='boolean')return v?'是':'否';
  return String(v);
}
function renderFedRows(d){
  var cols=FED_COLS[d.metric]||Object.keys((d.rows||[])[0]||{});
  var h='<table><tr>'+cols.map(function(c){return '<th>'+esc(c)+'</th>'}).join('')+'</tr>';
  h+=(d.rows||[]).map(function(r){
    return '<tr>'+cols.map(function(c){return '<td>'+esc(fedCell(r[c]))+'</td>'}).join('')+'</tr>'
  }).join('');
  $('fedRows').innerHTML=h+'</table>'+(d.rows&&d.rows.length?'':'<div class="hint">无命中成员</div>');
}
function renderFedQueries(list){
  $('fedQueries').innerHTML='<table><tr><th>时间</th><th>同类池</th><th>指标</th><th>关键词长度</th><th>成员数</th><th>结果</th></tr>'+
    (list||[]).map(function(x){return '<tr><td>'+esc(x.ts)+'</td><td>'+esc(x.pool_id)+'</td><td>'+
      esc(x.metric)+'</td><td>'+x.keyword_len+'</td><td>'+x.member_count+'</td><td>'+
      esc(x.result)+'</td></tr>'}).join('')+'</table>';
}
async function loadFederation(){
  if(!SID)return;
  var keep=$('fedMetric')?$('fedMetric').value:'';
  var [v,p,cf]=await Promise.all([
    api('/api/v1/federation/pools?session_id='+encodeURIComponent(SID)),
    api('/api/v1/federation/peers?session_id='+encodeURIComponent(SID)),
    api('/api/v1/org/conflicts')]);
  if(!v||!p)return;
  FED=v;
  $('fedRule').textContent=v.rule||'';
  $('fedPoolNote').textContent=v.pool_note||'';
  $('fedNote').textContent=v.note||'';
  $('fedIso').textContent=v.isolation||'';
  var cp=v.current_pool||{};
  $('fedStat').innerHTML=
    '<div><b>'+esc(cp.pool_id||'—')+'</b>当前同类池</div>'+
    '<div><b>'+esc(cp.portal_name||'—')+'／'+esc(cp.level||'—')+'</b>同类维度</div>'+
    '<div><b>'+(cp.member_count||0)+'</b>池内智能体</div>'+
    '<div><b>'+v.pool_count+'</b>全员同类池</div>'+
    '<div><b>'+(v.metrics||[]).length+'</b>聚合指标</div>'+
    '<div><b>'+(v.queries||[]).length+'</b>聚合留痕</div>';
  $('fedMetric').innerHTML=(v.metrics||[]).map(function(m){
    return '<option value="'+esc(m.id)+'">'+esc(m.name)+'（'+esc(m.id)+'）</option>'}).join('');
  if(keep)$('fedMetric').value=keep;
  $('fedPeers').innerHTML='<table><tr><th>成员</th><th>职务</th><th>智能体</th><th>层级</th><th>绑定班级</th><th>状态</th></tr>'+
    (p.peers||[]).map(function(x){return '<tr><td><b>'+esc(x.name)+'</b>'+
      (x.is_self?' <span class="tag c">本人</span>':'')+'<br><span style="font-size:11px;color:#6b7280">'+
      esc(x.user_id)+'</span></td><td>'+esc(x.post_name)+'<br><span style="font-size:11px;color:#6b7280">'+
      esc(x.post_id)+'</span></td><td>'+esc(x.agent_id)+'</td><td>'+esc(x.level)+'</td><td>'+
      esc((x.class_ids||[]).join('、')||'未绑定')+'</td><td>'+esc(x.status)+'</td></tr>'}).join('')+'</table>';
  $('fedPools').innerHTML='<table><tr><th>同类池</th><th>端／层级</th><th>在链</th><th>团线</th><th>层级待确认</th><th>成员数</th><th>成员</th></tr>'+
    (v.pools||[]).map(function(g){return '<tr><td>'+esc(g.pool_id)+
      (g.pool_id===cp.pool_id?' <span class="tag c">当前</span>':'')+'</td><td>'+
      esc(g.portal_name)+'／'+esc(g.level)+'</td><td>'+(g.in_chain?'是':'否')+'</td><td>'+
      (g.committee_line?'单列':'—')+'</td><td>'+(g.level_pending?'待确认':'—')+'</td><td><b>'+
      g.member_count+'</b></td><td>'+esc((g.posts||[]).map(function(x){
        return x.name+'（'+x.post_name+'）'}).join('；'))+'</td></tr>'}).join('')+'</table>';
  renderFedQueries(v.queries||[]);
  if(cf){
    var rows=(cf.items||[]).filter(function(x){return /^PC01[4-6]$/.test(x.id)});
    $('fedConflicts').innerHTML='<table><tr><th>编号</th><th>议题</th><th>当前处理</th><th>状态</th></tr>'+
      rows.map(function(x){var done=/已确认/.test(x.status||'');
        return '<tr><td>'+esc(x.id)+'</td><td><b>'+esc(x.topic)+'</b><br>'+
          '<span style="font-size:11px;color:#6b7280">'+esc(x.detail)+'</span></td><td>'+
          esc(x.current)+'</td><td class="'+(done?'good':'bad')+'">'+esc(x.status)+'</td></tr>'}).join('')+'</table>';
  }
  if(FED_RESULT)renderFedRows(FED_RESULT);
}
async function fedSearch(){
  var metric=$('fedMetric').value||'roster', kw=$('fedKeyword').value.trim();
  var body={session_id:SID,metric:metric};
  if(kw)body.keyword=kw;                 // 空关键词不传，保持快照归一化键稳定
  var d=await api('/api/v1/federation/search',body);
  if(!d)return;
  FED_RESULT=d;renderFedRows(d);
  $('fedSearchResult').innerHTML='已完成【'+esc(d.metric_name)+'】同类池只读聚合：命中 '+d.row_count+
    ' 个成员，覆盖 '+d.aggregate.covered_members+'/'+d.aggregate.pool_members+
    '；聚合前后共享上下文'+(d.no_context_pollution?'<b>完全一致，未污染</b>':'<b>不一致（异常）</b>')+
    '。聚合结果只作为本次响应返回，未写入任何空间。';
  $('fedVerify').innerHTML=
    '<div><b>'+(d.no_context_pollution?'未污染':'异常')+'</b>上下文校验</div>'+
    '<div><b>'+(d.writes_to_space?'是':'否')+'</b>写入空间</div>'+
    '<div><b>'+(d.stateless?'是':'否')+'</b>无状态</div>'+
    '<div><b>'+d.row_count+'</b>命中成员</div>'+
    '<div><b>'+d.aggregate.covered_members+'/'+d.aggregate.pool_members+'</b>覆盖成员</div>'+
    '<div><b>'+esc((d.space_shared_before||[]).join('、')||'（空）')+'</b>聚合前共享键</div>'+
    '<div><b>'+esc((d.space_shared_after||[]).join('、')||'（空）')+'</b>聚合后共享键</div>';
  $('fedAggregate').textContent=JSON.stringify(d.aggregate,null,2);
  var v=await api('/api/v1/federation/pools?session_id='+encodeURIComponent(SID));
  if(v)renderFedQueries(v.queries||[]);
  if($('spaceShared'))loadSpace();
}
async function fedTryPollute(){
  var d=await api('/api/v1/space/event',{session_id:SID,
    patch:{sum_attention_count:99,aggregate:'池级汇总结果'}});
  $('fedSearchResult').innerHTML=d?'【未拦截，异常】':'【已拒绝】sum_attention_count／aggregate 不属共享上下文白名单，服务端返回 403 并写审计；同类聚合结果无法污染本空间上下文。';
  if($('spaceShared'))loadSpace();
}

/* ---------------------------------------------------------------- 协同教育推送（PC017） */
function renderCoeduRows(d){
  $('coeduRows').innerHTML='<table><tr><th>班级</th><th>科目</th><th>指标</th><th>收件班主任</th><th>状态</th><th>说明</th></tr>'+
    (d.rows||[]).map(function(x){
      return '<tr><td><b>'+esc(x.class_id||'—')+'</b></td><td>'+esc(x.subject||'—')+'</td><td>'+
        esc(x.metric_name||x.metric||'—')+'</td><td>'+esc(x.bzr_name||x.bzr_post_id||'未匹配')+
        (x.self_user?' <span class="tag c">同人不同职务</span>':'')+'</td><td>'+
        esc(x.status||'—')+(x.available===false?' <span class="tag">降级</span>':'')+'</td><td>'+
        esc(x.reason||x.rule||x.note||'—')+'</td></tr>';
    }).join('')+'</table>';
}
function renderCoeduLists(v){
  $('coeduLinks').innerHTML='<table><tr><th>班级</th><th>科目</th><th>教师职务</th><th>来源／状态</th></tr>'+
    (v.links||[]).map(function(x){
      return '<tr><td><b>'+esc(x.class_id)+'</b></td><td>'+esc(x.subject)+'</td><td>'+
        esc(x.teacher_post_id||'—')+'</td><td>'+esc(x.note||x.status||'—')+'</td></tr>';
    }).join('')+'</table>'+
    (v.links&&v.links.length?'':'<div class="hint">当前端不是教师端，或该教师职务尚未绑定任课班级（PC010 待教务处补录）。</div>');
  $('coeduInbox').innerHTML='<table><tr><th>班级</th><th>科目</th><th>指标</th><th>来自</th><th>状态</th><th>说明</th></tr>'+
    (v.inbox||[]).map(function(x){
      return '<tr><td><b>'+esc(x.class_id||'—')+'</b></td><td>'+esc(x.subject||'—')+'</td><td>'+
        esc(x.metric_name||x.metric||'—')+'</td><td>'+esc(x.teacher_name||x.teacher_post_id||'—')+'</td><td>'+
        esc(x.status||'—')+'</td><td>'+esc(x.reason||x.rule||x.note||'—')+'</td></tr>';
    }).join('')+'</table>'+
    (v.inbox&&v.inbox.length?'':'<div class="hint">当前端不是班主任端，或该班尚未收到协同教育推送。</div>');
  $('coeduPushes').innerHTML='<table><tr><th>时间</th><th>班级</th><th>科目</th><th>指标</th><th>收件职务</th><th>状态</th></tr>'+
    (v.pushes||[]).map(function(x){
      return '<tr><td>'+esc(x.ts||'—')+'</td><td>'+esc(x.class_id||'—')+'</td><td>'+esc(x.subject||'—')+
        '</td><td>'+esc(x.metric||'—')+'</td><td>'+esc(x.bzr_post_id||'—')+'</td><td>'+esc(x.status||'—')+'</td></tr>';
    }).join('')+'</table>';
  $('coeduPending').innerHTML='<table><tr><th>编号</th><th>口径</th><th>状态</th></tr>'+
    (v.pending||[]).map(function(x){
      return '<tr><td>'+esc(x.id)+'</td><td>'+esc(x.topic)+'</td><td>'+esc(x.status)+'</td></tr>';
    }).join('')+'</table>';
}
async function loadCoedu(){
  if(!SID)return;
  var keep=$('coeduMetric')?$('coeduMetric').value:'';
  var v=await api('/api/v1/coedu/view?session_id='+encodeURIComponent(SID));
  if(!v)return;
  COEDU=v;
  $('coeduRule').textContent=v.rule||'';
  $('coeduRelation').textContent=v.relation||'';
  $('coeduLinkNote').textContent=v.link_note||'';
  $('coeduNote').textContent=v.note||'';
  $('coeduIso').textContent=v.isolation||'';
  $('coeduStat').innerHTML=
    '<div><b>'+esc((CTX&&CTX.portal_name)||v.portal||'—')+'</b>当前端</div>'+
    '<div><b>'+v.link_count+'</b>我的任课绑定</div>'+
    '<div><b>'+v.inbox_count+'</b>本班协同收件</div>'+
    '<div><b>'+v.push_count+'</b>推送留痕</div>'+
    '<div><b>'+(v.metrics||[]).length+'</b>推送指标</div>'+
    '<div><b>'+(v.pending||[]).length+'</b>口径记录</div>';
  $('coeduMetric').innerHTML=(v.metrics||[]).map(function(m){
    return '<option value="'+esc(m.id)+'">'+esc(m.name)+'（'+esc(m.id)+'）</option>'}).join('');
  if(keep)$('coeduMetric').value=keep;
  renderCoeduLists(v);
}
function coeduMetric(){return $('coeduMetric')?($('coeduMetric').value||'status'):'status'}
function renderCoeduVerify(d){
  $('coeduVerify').innerHTML=
    '<div><b>'+(d.no_context_pollution?'未污染':'异常')+'</b>上下文校验</div>'+
    '<div><b>'+(d.writes_to_space?'是':'否')+'</b>写入空间</div>'+
    '<div><b>'+(d.stateless?'是':'否')+'</b>无状态</div>'+
    '<div><b>'+d.recipient_count+'</b>定向收件人</div>'+
    '<div><b>'+d.pushed_count+'</b>已投递</div>'+
    '<div><b>'+d.skipped_count+'</b>降级跳过</div>'+
    '<div><b>'+esc((d.space_shared_before||[]).join('、')||'（空）')+'</b>推送前共享键</div>'+
    '<div><b>'+esc((d.space_shared_after||[]).join('、')||'（空）')+'</b>推送后共享键</div>';
  $('coeduAggregate').textContent=JSON.stringify(
    {metric:d.metric,rows:d.rows.map(function(x){return {class_id:x.class_id,subject:x.subject,
      available:x.available,status:x.status,attention_count:x.attention_count,
      exam_numeric_available:x.exam_numeric_available,reason:x.reason}})},null,2);
}
async function coeduPreview(){
  var d=await api('/api/v1/coedu/preview',{session_id:SID,metric:coeduMetric()});
  if(!d)return;
  COEDU_RESULT=d;renderCoeduRows(d);renderCoeduVerify(d);
  $('coeduResult').innerHTML='已预览【'+esc(d.metric_name)+'】：定向收件人 '+d.recipient_count+
    ' 个、可投递 '+(d.row_count-d.skipped_count)+' 条；预览不落库、不写收件箱，仅用于推送前回显。';
}
async function coeduPush(){
  var d=await api('/api/v1/coedu/push',{session_id:SID,metric:coeduMetric()});
  if(!d)return;
  COEDU_RESULT=d;renderCoeduRows(d);renderCoeduVerify(d);
  $('coeduResult').innerHTML='已完成【'+esc(d.metric_name)+'】协同教育自动推送：定向收件人 '+
    d.recipient_count+' 个、已投递 '+d.pushed_count+' 条、降级跳过 '+d.skipped_count+
    ' 条；推送前后共享上下文'+(d.no_context_pollution?'<b>完全一致，未污染</b>':'<b>不一致（异常）</b>')+
    '。非隶属管理、不进六级链、不参与催办与考核。';
  var v=await api('/api/v1/coedu/view?session_id='+encodeURIComponent(SID));
  if(v)renderCoeduLists(v);
  if($('spaceShared'))loadSpace();
}
async function coeduTryPollute(){
  var d=await api('/api/v1/space/event',{session_id:SID,
    patch:{attention_count:99,aggregate:'协同教育推送结果'}});
  $('coeduResult').innerHTML=d?'【未拦截，异常】':'【已拒绝】attention_count／aggregate 不属共享上下文白名单，服务端返回 403 并写审计；协同教育推送结果无法污染本空间上下文。';
  if($('spaceShared'))loadSpace();
}

/* ---------------------------------------------------------------- 三端划分 */
async function loadPortals(){
  if(!CTX)return;
  var [all,mine,cf]=await Promise.all([
    api('/api/v1/portals'),
    api('/api/v1/portal/summary?userid='+encodeURIComponent(CTX.user_id)),
    api('/api/v1/org/conflicts')]);
  if(all){
    PORTALS_DEF=all.portals||PORTALS_DEF;
    $('portalEntryRule').textContent=all.auto_rule||all.entry_rule||'';
    $('portalRule').textContent=(all.manages_note||'')+' '+(all.note||'');
    $('portalIso').textContent=all.rule||'';
    $('portalCards').innerHTML=PORTALS_DEF.map(function(p){
      return '<div class="card" style="margin:0"><h3>'+esc(p.name)+
        '　<span style="font-weight:400;color:#6b7280;font-size:12px">'+esc(p.sub)+'</span></h3>'+
        '<div style="font-size:12px;line-height:1.8">'+
        '<b>谁用</b>：'+esc(p.who)+'<br>'+
        '<b>做什么</b>：'+esc(p.focus)+'<br>'+
        '<b>工作台</b>：'+esc((p.desk||[]).join('／'))+'<br>'+
        '<b>数据边界</b>：'+esc(p.data_scope)+'<br>'+
        '<b>可用工具</b>：'+esc((p.tools||[]).join('／'))+'<br>'+
        '<b>与六级链</b>：'+esc(p.chain)+'<br>'+
        '<b>红线</b>：'+esc(p.rule)+'</div></div>';
    }).join('');
    $('portalPeople').innerHTML='<table><tr><th>姓名</th><th>userid</th><th>端</th><th>端数</th><th>职务数</th></tr>'+
      (all.people||[]).map(function(x){
        return '<tr><td>'+esc(x.name)+'</td><td>'+esc(x.user_id)+'</td><td>'+
          (x.portals||[]).map(function(pid){
            var q=PORTALS_DEF.filter(function(y){return y.id===pid})[0];return q?q.name:pid
          }).join('＋')+'</td><td><b>'+x.portal_count+'</b></td><td>'+x.posts+'</td></tr>';
      }).join('')+'</table>';
  }
  if(mine){
    PORTAL_GROUPS=mine.portals||PORTAL_GROUPS;
    $('portalStat').innerHTML=mine.portals.map(function(p){
      return '<div><b>'+p.count+'</b>'+esc(p.name)+(p.has?' · 有职务':' · 无职务')+'</div>'
    }).join('')+'<div><b>'+mine.portal_count+'</b>当前账号跨端数</div>';
    $('portalSwitch').innerHTML=mine.portals.map(function(p){
      var cur=CTX&&p.portal===CTX.portal;
      var btn='<button class="btn '+(cur?'gray':'')+'" style="margin:4px 8px 4px 0" '+
        (p.has?'onclick="switchPortal(\''+esc(p.portal)+'\')"':'disabled')+'>'+
        (cur?'当前 · ':'')+esc(p.name)+(p.has?'（'+p.count+'职）':'（本账号无职务）')+'</button>';
      var detail=p.posts.length?'<div class="hint" style="margin:0 0 10px 0">'+p.posts.map(function(x){
        return esc(x.post_id)+' → '+esc(x.post_name)+' ／ '+esc(x.agent_id)+'（'+esc(x.level)+'）'+
          (x.in_chain?' · 进链':' · 不进链')+(x.committee_line?' · 团线单列':'')
      }).join('<br>')+'</div>':'';
      return btn+detail;
    }).join('');
    renderPortalSel();
  }
  if(cf){
    var rows=(cf.items||[]).filter(function(x){return /^PC01[0-4]$/.test(x.id)});
    $('portalConflicts').innerHTML='<table><tr><th>编号</th><th>议题</th><th>当前处理</th><th>责任</th><th>状态</th></tr>'+
      rows.map(function(x){var done=/已确认/.test(x.status||'');
        return '<tr><td>'+esc(x.id)+'</td><td><b>'+esc(x.topic)+'</b><br>'+
          '<span style="font-size:11px;color:#6b7280">'+esc(x.detail)+'</span></td><td>'+
          esc(x.current)+'</td><td>'+esc(x.owner)+'</td><td class="'+(done?'good':'bad')+'">'+
          esc(x.status)+'</td></tr>'}).join('')+'</table>';
  }
}
async function switchPortal(pid){
  if(!pid)return;
  var r=ENTRY&&ENTRY.roles?ENTRY.roles.filter(function(x){return x.portal===pid})[0]:null;
  if(r)return switchRole(r.post_id);
  return autoEnter(ENTRY_USER);
}

/* ---------------------------------------------------------------- 本周待确认红点（D2/D4-B/D3/D5） */
var TODO=null;
async function loadTodo(){
  if(!CTX){toast('请先进入一个职务');return}
  var [tl,rf,ws,sc]=await Promise.all([
    api('/api/v1/todo/list?session_id='+encodeURIComponent(SID)),
    api('/api/v1/todo/referrals?session_id='+encodeURIComponent(SID)),
    api('/api/v1/warning/state'),
    api('/api/v1/scheduler/status')]);
  if(!tl)return;
  TODO=tl;
  var cid=(CTX.class_ids&&CTX.class_ids[0])||'2611';
  $('todoStat').innerHTML='班级 <b>'+esc(cid)+'</b> · 周 <b>'+esc(tl.week)+'</b> · 待确认 '+
    '<b>'+tl.open_count+'</b> 项（含上周未销号）'+(tl.items.length?'':' · '+esc(tl.empty_text));
  $('todoList').innerHTML=!tl.items.length
    ?'<div class="hint">'+esc(tl.empty_text)+'（空态不摆示例数据）</div>'
    :'<table><tr><th>item_id</th><th>类型</th><th>学生</th><th>分类</th><th>事实（只写事实）</th><th>状态</th><th>操作</th></tr>'+
      tl.items.map(function(x){
        var mine=x.owner_post_id===CTX.post_id;
        return '<tr><td class="mono">'+esc(x.item_id)+'</td><td>'+esc(tl.kinds[x.kind]||x.kind)+
          '</td><td class="mono">'+esc(x.student_id||'—')+'</td><td>'+esc(x.category||'—')+
          '</td><td style="max-width:340px;font-size:11px">'+esc(x.fact||'')+'</td><td class="'+
          (x.status==='open'?'bad':'good')+'">'+(x.status==='open'?'待确认':'已销号')+'</td><td>'+
          (x.status==='open'&&mine
            ?'<button class="btn sm" onclick="todoClose(\''+esc(x.item_id)+'\')">销号</button>'
            :'<span class="hint">'+(x.status==='closed'?'handled_at '+esc(x.handled_at||''):'非本职务创建')+'</span>')+
          '</td></tr>'}).join('')+'</table>';
  // 转介单（L1 本班 / L2+ 全部）＋回执操作只属行政端
  var isAdmin=/^L[2-6]$/.test(CTX.level||'');
  $('todoSlips').innerHTML=!rf||!rf.slips.length
    ?'<div class="hint">暂无转介单（转介后 L2 劝返台账按三态回执）</div>'
    :'<table><tr><th>slip_id</th><th>学生</th><th>分类</th><th>状态</th><th>创建</th>'+
      (isAdmin?'<th>L2 回执</th>':'')+'</tr>'+
      rf.slips.map(function(s){
        return '<tr><td class="mono">'+esc(s.slip_id)+'</td><td class="mono">'+esc(s.student_id)+
          '</td><td>'+esc(s.category)+'</td><td>'+esc(s.status_text)+'</td>'+
          '<td style="font-size:11px">'+esc(s.created_at)+'<br>'+esc(s.class_id)+'</td><td>'+
          (isAdmin&&s.status!=='closed'
            ?s.l2_states.filter(function(t){return t!==s.status_text}).map(function(t){
              var st={'已接收':'received','处置中':'processing','已销号':'closed'}[t];
              return '<button class="btn sm" onclick="todoReceipt(\''+esc(s.slip_id)+'\',\''+st+'\')">'+t+'</button>'}).join(' ')
            :esc(s.status==='closed'?(s.closed_at||''):''))+
          '</td></tr>'}).join('')+'</table>';
  // 转介表单：学生只来自本班需关注（只读派生区），不能凭空转介
  var att=await api('/api/v1/growth/attention?session_id='+encodeURIComponent(SID)+'&class_id='+encodeURIComponent(cid));
  var items=att&&att.data&&att.data.items?att.data.items:[];
  $('todoStudent').innerHTML=items.length
    ?items.map(function(x){return '<option value="'+esc(x.student_id)+'">'+esc(x.student_id)+
      '｜'+esc(x.name_masked||'')+'｜'+esc(x.mark||'')+'</option>'}).join('')
    :'<option value="">（本班暂无已标记学生，不能凭空转介）</option>';
  // D3 六件套（如实报告，规则不由系统代写）
  $('warningState').innerHTML=Object.keys(ws||{}).map(function(k){
    return '<div class="row"><div class="k">'+esc(k)+'</div><div class="v">'+esc(ws[k])+'</div></div>'}).join('');
  $('todoSlipRule').innerHTML=esc((rf&&rf.rule)||'')+'<br>调度：ENABLE_SCHEDULER=<b>'+
    (sc&&sc.enabled)+'</b> · 周报周一 <b>'+esc(sc?fmtSched(sc.weekly_report_at):'')+'</b>'+
    '（草稿＋站内提醒，归档人审点保留）';
}
function fmtSched(w){if(!w)return '';var d=['一','二','三','四','五','六','日'][w.weekday||0];
  return '周'+d+' '+String(w.hour).padStart(2,'0')+':'+String(w.minute).padStart(2,'0')}
async function todoRefer(){
  var sid=$('todoStudent').value;
  if(!sid){toast('本班暂无已标记学生（只读派生区），不能凭空转介');return}
  var d=await api('/api/v1/todo/refer',{session_id:SID,student_id:sid,category:$('todoCategory').value});
  if(d){$('todoResult').innerHTML='已生成转介单 <b class="mono">'+esc(d.slip_id)+
    '</b>（'+esc(d.student_id)+' / '+esc(d.category)+'）<br>事实（只取派生区已有标记，不新增判断）：'+
    esc(d.fact)+'<br>L2 回执三态：已接收／处置中／已销号；'+esc(d.note);toast('转介单已生成，待 L2 接收');loadTodo()}
}
async function todoNote(){
  var d=await api('/api/v1/todo/note',{session_id:SID,category:$('todoCategory').value});
  if(d){$('todoResult').innerHTML='已登记家长告知事项 <b class="mono">'+esc(d.todo_id)+
    '</b>（人工签发，秘书不代发）；'+esc(d.rule);toast('已登记（人工签发）');loadTodo()}
}
async function todoClose(id){
  if(!confirm('销号前请确认已完成人审（三元组审计将留痕，销号后该项不再出现）。确认销号 '+id+'？'))return;
  var d=await api('/api/v1/todo/close',{session_id:SID,item_id:id});
  if(d){toast('已销号（留三元组审计）');loadTodo()}
}
async function todoReceipt(slipId,st){
  var d=await api('/api/v1/todo/receipt',{session_id:SID,slip_id:slipId,state:st});
  if(d){toast('回执：'+d.status_text+'（不回流学生明细）');loadTodo()}
}

/* ---------------------------------------------------------------- 绑定 */
document.querySelectorAll('.tabs button').forEach(function(b){b.onclick=function(){switchView(b.dataset.v)}});
$('btnSend').onclick=function(){send()};
$('inp').onkeydown=function(e){if(e.key==='Enter')send()};
$('btnConfirm').onclick=function(){confirmWrite('确认')};
$('btnCancel').onclick=function(){confirmWrite('取消')};
$('btnPost').onclick=function(){$('postModal').classList.add('on')};
$('btnCloseModal').onclick=function(){$('postModal').classList.remove('on')};
$('entryUser').onchange=function(){autoEnter(this.value)};
$('btnEntry').onclick=function(){openRoles()};
$('btnCloseRoles').onclick=function(){$('entryOverlay').classList.remove('on')};
$('entryOverlay').onclick=function(e){if(e.target===this)this.classList.remove('on')};
$('btnPush').onclick=doPush;
$('btnDunEcho').onclick=dunEcho;
$('btnDunConfirm').onclick=dunConfirm;
$('btnDunReply').onclick=dunReply;
$('btnEscalate').onclick=escalate;

(async function init(){
  await loadPersons();
  await autoEnter('zhangmin');   // 企微角色自动匹配加载：登录即自动进入主职务，无需手动选择
})();
