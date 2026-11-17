/* 本地规划查看器：不请求服务器，不执行战役条件。 */
'use strict';
const $ = id => document.getElementById(id);
const NS = 'http://www.w3.org/2000/svg';
const DIRS = [[1,0,'东'],[1,-1,'东北'],[0,-1,'西北'],[-1,0,'西'],[-1,1,'西南'],[0,1,'东南']];
const SIZE = 43;
const COLORS = {desert:'#8a7853',grassland:'#61755a',mountain:'#5a6467',water:'#285f73',ruins:'#786e65'};
const TERRAIN = {desert:'荒漠',grassland:'草原',mountain:'山地',water:'水体',ruins:'城市废墟'};
const TYPES = {town:'城镇',landmark:'地标',task:'任务点',portal:'通路入口'};
const state = {world:null, worldFile:'', maps:new Map(), current:null, selected:null, issues:[], loadIssues:[], invalid:new Set(), view:{x:0,y:0,k:1}, layers:{terrain:true,borders:true,edges:true,objects:true,labels:true}, busy:false};
function el(tag, text, cls) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n; }
function svg(tag, attrs={}, text) {const n=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;return n;}
function button(text, action, cls) {const b=el('button',text,cls);b.type='button';b.addEventListener('click',action);return b;}
const tileID = (q,r) => `${q},${r}`;
const edgeID = (a,b) => [a,b].sort().join('|');
const point = t => ({x:SIZE*Math.sqrt(3)*(t.q+t.r/2),y:SIZE*1.5*t.r});
const corners = t => {const p=point(t);return Array.from({length:6},(_,i)=>{const a=(i*60-30)*Math.PI/180;return {x:p.x+SIZE*Math.cos(a),y:p.y+SIZE*Math.sin(a)};});};
function segment(t,d) {const c=corners(t), i=(6-d)%6;return [c[i],c[(i+1)%6]];}
function line(parent,a,b,attrs={}) {parent.append(svg('line',{x1:a.x,y1:a.y,x2:b.x,y2:b.y,...attrs}));}
function mapNow(){return state.maps.get(state.current)?.data;}
function tilesOf(m){return new Map(m.tiles.map(t=>[tileID(t.q,t.r),t]));}
function group(t){const w=state.world;const town=w?.groups?.towns?.[t.jurisdiction];return {town,province:w?.groups?.provinces?.[town?.province],region:w?.groups?.regions?.[w?.groups?.provinces?.[town?.province]?.region],faction:w?.groups?.factions?.[town?.faction]};}
function objectsAt(m,id){return m.objects.filter(o=>o.tile===id);}
// 城镇名称只从公共辖区读取；其他对象保留各自的名称。
function objectName(o){return o?(o.type==='town'?state.world?.groups?.towns?.[o.id]?.name:o.name)||'名称错误':'';}
function effectiveEdge(m,a,b){return m.edges.find(e=>edgeID(e.a,e.b)===edgeID(a,b)) || {a,b,state:'open',landform:'land',facility:'none',cost:1,effects:[],derived:true};}
function issue(level,where,message){state.issues.push({level,where,message});}
const dict = v => v && typeof v==='object' && !Array.isArray(v);
const number = v => typeof v==='number' && Number.isFinite(v);
const text = v => typeof v==='string' && v.trim().length>0;
function adjacent(a,b){return DIRS.some(([q,r])=>a.q+q===b.q&&a.r+r===b.r);}

// 结构错误保留为诊断；禁止把错误区域绘制成可通行地图。
function validate() {
  state.issues=[...state.loadIssues];state.invalid.clear();
  const w=state.world;
  if(!w){issue('info','世界索引','请补选世界索引.json；已读取区域会保留。');return;}
  let worldBad=false;
  const failWorld=msg=>{issue('error',state.worldFile,msg);worldBad=true;};
  if(!dict(w.groups)||!['towns','provinces','regions','factions'].every(k=>dict(w.groups[k])))failWorld('缺少公共分组 towns / provinces / regions / factions。');
  if(!Array.isArray(w.maps)||!Array.isArray(w.routes))failWorld('maps 和 routes 必须为数组。');
  if(worldBad){for(const id of state.maps.keys())state.invalid.add(id);return;}
  for(const category of ['regions','factions'])for(const [id,item] of Object.entries(w.groups[category])){if(!dict(item)||!text(item.name))failWorld(`公共分组 ${category}/${id} 需要对象及非空name。`);}
  const mapIds=new Set();
  for(const m of w.maps){if(!dict(m)||!text(m.id)||!text(m.name)||!text(m.file)||!text(m.status)||mapIds.has(m.id)){failWorld('区域清单字段缺失或地图ID重复。');continue;}mapIds.add(m.id);if(!state.maps.has(m.id))issue('info',m.id,m.status==='unexpanded'?'区域未展开':'区域未加载 · '+m.file);}
  for(const [id,t] of Object.entries(w.groups.towns)){if(!dict(t)||!text(t.name)||!w.groups.provinces[t.province]||!w.groups.factions[t.faction])failWorld(`辖区 ${id} 的名称、行省或归属引用无效。`);}
  for(const [id,p] of Object.entries(w.groups.provinces)){if(!dict(p)||!text(p.name)||!w.groups.regions[p.region])failWorld(`行省 ${id} 的名称或规划区引用无效。`);}
  const globalObjects=new Map();
  for(const [id,entry] of state.maps){
    const m=entry.data;const where=`${entry.file} / ${id}`;
    const fail=msg=>{issue('error',where,msg);state.invalid.add(id);};
    if(!mapIds.has(id))fail('地图未登记于世界索引。');
    if(!text(m.name)||!text(m.status)||!text(m.source)||!Array.isArray(m.tiles)||!Array.isArray(m.edges)||!Array.isArray(m.objects)){fail('缺少名称、状态、来源或 tiles / edges / objects 数组。');continue;}
    const ts=new Map();
    for(const t of m.tiles){
      if(!dict(t)||!Number.isInteger(t.q)||!Number.isInteger(t.r)){fail('地块坐标必须为整数q/r。');continue;}
      const key=tileID(t.q,t.r);if(t.id!==key)fail(`地块 ${key} 的id须等于坐标。`);if(ts.has(key))fail(`重复坐标 ${key}`);ts.set(key,t);
      if(!Object.hasOwn(COLORS,t.terrain))fail(`地块 ${key} 地形无效。`);
      if(t.jurisdiction!==null&&!w.groups.towns[t.jurisdiction])fail(`地块 ${key} 悬空辖区 ${t.jurisdiction}`);
      if(t.radiation!==null&&(!number(t.radiation)||t.radiation<0))fail(`地块 ${key} 辐射须为非负数或null。`);
      if(t.radiation===null)issue('pending',`${id}/${key}`,'辐射初值待定。');
    }
    const es=new Set();
    for(const e of m.edges){
      if(!dict(e)||!text(e.a)||!text(e.b)){fail('接边两端必须是地块ID。');continue;}
      const key=edgeID(e.a,e.b);if(es.has(key))fail(`重复接边 ${key}`);es.add(key);
      if(!ts.has(e.a)||!ts.has(e.b)||!adjacent(ts.get(e.a),ts.get(e.b)))fail(`接边 ${key} 两端缺失或不相邻。`);
      if(!['open','closed'].includes(e.state)||!['land','water','mountain'].includes(e.landform)||!['none','road','bridge','ford'].includes(e.facility)||!number(e.cost)||e.cost<0||!Array.isArray(e.effects)||!e.effects.every(text))fail(`接边 ${key} 属性无效。`);
    }
    for(const [key,t] of ts){if(t.terrain==='water')for(const [q,r] of DIRS){const neighbor=tileID(t.q+q,t.r+r);if(ts.has(neighbor)&&!es.has(edgeID(key,neighbor)))fail(`水体 ${key} 缺少朝 ${neighbor} 的显式接边。`);}}
    for(const o of m.objects){
      if(!dict(o)||!text(o.id)||(o.type==='town'?!w.groups.towns[o.id]:!text(o.name))||!Object.hasOwn(TYPES,o.type)||!ts.has(o.tile)){fail('对象身份、类型或地块引用无效：'+String(o?.id));continue;}
      if(globalObjects.has(o.id)){fail(`跨区域对象ID重复 ${o.id}`);state.invalid.add(globalObjects.get(o.id));}globalObjects.set(o.id,id);
      if(o.type==='town'&&ts.get(o.tile).jurisdiction!==o.id)fail(`城镇 ${o.id} 与所在辖区不一致。`);
      if(o.type==='portal'&&!w.routes.some(r=>r?.id===o.route))fail(`入口 ${o.id} 未引用合法通路。`);
      if(o.type==='portal'){const r=w.routes.find(r=>r?.id===o.route);if(r&&![r.a,r.b].some(e=>e?.map===id&&e.tile===o.tile))fail(`入口 ${o.id} 的位置不是通路端点。`);}
    }
  }
  const routeIds=new Set();
  for(const r of w.routes){
    const fail=msg=>{issue('error',`通路 ${r?.id||'无ID'}`,msg);for(const e of [r?.a,r?.b])if(e?.map)state.invalid.add(e.map);};
    if(!dict(r)||!text(r.id)||routeIds.has(r.id)||!text(r.name)||!['ordinary','special'].includes(r.type)||!['both','a_to_b','b_to_a'].includes(r.direction)||(r.cost!==null&&(!number(r.cost)||r.cost<0))||!Array.isArray(r.effects)||!r.effects.every(text)||!Array.isArray(r.conditions)||!r.conditions.every(text)||!text(r.source)||!['complete','pending','unexpanded'].includes(r.status)){fail('ID、类型、方向、代价、效果、条件、来源或状态无效。');continue;}
    routeIds.add(r.id);if(r.cost===null)issue('pending',r.id,'跨区代价待定；查看器不执行移动。');
    for(const side of ['a','b']){
      const e=r[side];if(e===null){if(r.status==='complete')fail(`${side}端为空但标为完整。`);else issue('pending',r.id,`${side}端点待定。`);continue;}
      if(!dict(e)||!mapIds.has(e.map)||!text(e.tile)){fail(`${side}端地图身份或地块引用无效。`);continue;}
      const m=state.maps.get(e.map)?.data;
      if(!m){issue('info',r.id,`${e.map} 区域未加载／未展开。`);continue;}
      if(!Array.isArray(m.tiles)||!m.tiles.some(t=>t?.id===e.tile)){fail(`${e.map}/${e.tile} 已加载但地块不存在。`);continue;}
      if(!Array.isArray(m.objects)||!m.objects.some(o=>o?.type==='portal'&&o.route===r.id&&o.tile===e.tile))fail(`${e.map}/${e.tile} 缺少对应入口对象。`);
    }
  }
  if(worldBad)for(const id of state.maps.keys())state.invalid.add(id);
}

async function loadFiles(files){
  if(state.busy)return;state.busy=true;$('files').disabled=true;state.loadIssues=[];
  try{
    // 先读完一批，再提交替换；同批次世界索引不会因文件选择顺序丢失。
    const parsed=[];
    for(const f of files){try{const d=JSON.parse((await f.text()).replace(/^\uFEFF/,''));if(!dict(d)||d.schema_version!==1||!['world','region'].includes(d.kind)||!text(d.id))throw new Error('需为格式版本1的world或region，且有字符串id。');parsed.push({data:d,file:f.name});}catch(e){state.loadIssues.push({level:'error',where:f.name,message:String(e.message)});}}
    for(const entry of parsed){const d=entry.data;if(d.kind==='world'){if(state.world&&!window.confirm(`重复世界索引 ${d.id}。替换当前索引 ${state.world.id}？区域文件会保留并重新检查。`))continue;state.world=d;state.worldFile=entry.file;}else{if(state.maps.has(d.id)&&!window.confirm(`地图ID ${d.id} 已加载。用 ${entry.file} 明确替换当前版本？`))continue;state.maps.set(d.id,entry);}}
    validate();const first=[...state.maps.keys()].find(id=>!state.invalid.has(id));if(!state.current||!state.maps.has(state.current))state.current=first||state.maps.keys().next().value||null;
    state.selected=null;refresh();fit();
  }finally{state.busy=false;$('files').disabled=false;$('files').value='';}
}

function refresh(){
  const w=state.world;$('maps').replaceChildren();
  const listed=w&&Array.isArray(w.maps)?w.maps:[];
  for(const m of listed){if(!m?.id)continue;const loaded=state.maps.has(m.id);const b=button(m.name||m.id,()=>switchMap(m.id),`map-choice${state.current===m.id?' active':''}`);b.append(el('small',`${m.id} · ${state.invalid.has(m.id)?'配置错误':loaded?'已加载':m.status==='unexpanded'?'未展开':'未加载'}`));b.disabled=!loaded;$('maps').append(b);}
  if(!listed.length)$('maps').append(el('p','加载世界索引后显示区域清单。','muted'));
  const old=$('province').value;$('province').replaceChildren(el('option','全部行省'));$('province').firstChild.value='';
  for(const [id,p] of Object.entries(w?.groups?.provinces||{})){const opt=el('option',`${id} ${p?.name||'名称错误'}`);opt.value=id;$('province').append(opt);}if([...$('province').options].some(o=>o.value===old))$('province').value=old;
  $('issues').replaceChildren();for(const x of state.issues){$('issues').append(el('p',`${x.level==='error'?'错误':x.level==='pending'?'待定':'提示'} · ${x.where}：${x.message}`,`issue ${x.level}`));}
  if(!state.issues.length)$('issues').append(el('p','当前已加载内容未发现引用错误。','muted'));
  const errors=state.issues.filter(x=>x.level==='error').length;$('issueSummary').textContent=`加载与配置 · ${errors} 个错误`;
  $('status').textContent=`${state.maps.size} 个区域文件 · ${errors} 个错误 · ${state.issues.filter(x=>x.level==='pending').length} 项待定`;
  render();details();search();
}
function switchMap(id,tile=null){if(!state.maps.has(id))return;state.current=id;state.selected=tile;refresh();fit();if(tile)focusTile(tile);}
function render(){
  const m=mapNow();const scene=$('scene');scene.replaceChildren();
  const valid=m&&state.world&&!state.invalid.has(m.id);$('empty').hidden=Boolean(valid);
  if(!valid){if(state.world&&m&&state.invalid.has(m.id)){$('mapTitle').textContent='当前区域配置错误 · 请查看右侧诊断';$('empty').replaceChildren(el('h2','该区域暂不可查看'),el('p','修正右侧错误后重新加载；同ID文件可明确替换。'));}else{$('mapTitle').textContent='尚未就绪';$('empty').replaceChildren(el('h2','从世界索引开始'),el('p','多选加载 content/world 中的世界索引.json 与区域JSON，可随时补选。'));}return;}
  $('mapTitle').textContent=`${m.name} · ${m.id}`;
  const ts=tilesOf(m);const selected=ts.get(state.selected);const neighbors=new Set(selected?DIRS.map(([q,r])=>tileID(selected.q+q,selected.r+r)):[]);
  for(const [id,t] of ts){const p=point(t), g=svg('g',{class:'tile',tabindex:0,role:'button','aria-label':`${id} ${group(t).town?.name||'无辖区'} ${TERRAIN[t.terrain]}`});
    const objs=objectsAt(m,id);const town=state.world.groups.towns[t.jurisdiction];const match=(!$('kind').value||objs.some(o=>o.type===$('kind').value))&&(!$('province').value||town?.province===$('province').value);if(!match)g.classList.add('dim');
    g.append(svg('polygon',{points:corners(t).map(p=>`${p.x},${p.y}`).join(' '),fill:state.layers.terrain?COLORS[t.terrain]:'#344448',class:`hex${id===state.selected?' selected':neighbors.has(id)?' neighbor':''}`}));
    g.append(svg('title',{},`${id} · ${TERRAIN[t.terrain]} · ${town?.name||'无辖区'}`));
    g.addEventListener('click',()=>{if(dragMoved)return;select(id);});g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();e.stopPropagation();select(id);}});scene.append(g);
  }
  if(state.layers.borders)for(const [id,t] of ts)for(let d=0;d<6;d++){const [q,r]=DIRS[d], b=ts.get(tileID(t.q+q,t.r+r));if(b&&id<b.id&&t.jurisdiction!==b.jurisdiction)line(scene,...segment(t,d),{class:'boundary'});}
  if(state.layers.edges){
    for(const e of m.edges){const a=ts.get(e.a),b=ts.get(e.b);const d=DIRS.findIndex(([q,r])=>a.q+q===b.q&&a.r+r===b.r);const ends=segment(a,d);
      if(e.landform==='water')line(scene,...ends,{class:'edge',stroke:'#70bed4','stroke-width':6});
      if(e.landform==='mountain')line(scene,...ends,{class:'edge',stroke:'#202b30','stroke-width':7});
      if(e.state==='closed')line(scene,...ends,{class:'edge',stroke:'#efaaa0','stroke-width':2.5,'stroke-dasharray':'5 5'});
      if(e.state==='open'&&['road','bridge'].includes(e.facility)){
        const ap=point(a),bp=point(b);line(scene,ap,bp,{class:'road'});
        if(e.facility==='bridge'&&a.terrain!=='water'&&b.terrain!=='water'){const mid={x:(ap.x+bp.x)/2,y:(ap.y+bp.y)/2};const u={x:(bp.x-ap.x)*.16,y:(bp.y-ap.y)*.16};line(scene,{x:mid.x-u.x,y:mid.y-u.y},{x:mid.x+u.x,y:mid.y+u.y},{class:'bridge-deck'});}
      }
    }
    // 水格桥面按开放设施边逐侧连接中心，支持任意六方向旋转。
    for(const t of m.tiles.filter(t=>t.terrain==='water')){const center=point(t);for(let d=0;d<6;d++){const [q,r]=DIRS[d],b=ts.get(tileID(t.q+q,t.r+r));if(!b)continue;const e=effectiveEdge(m,t.id,b.id);if(e.state==='open'&&['bridge','road'].includes(e.facility)){const ends=segment(t,d),mid={x:(ends[0].x+ends[1].x)/2,y:(ends[0].y+ends[1].y)/2};line(scene,center,mid,{class:'bridge-deck'});line(scene,center,mid,{class:'bridge-rail'});}}}
  }
  for(const [id,t] of ts){const p=point(t),objs=objectsAt(m,id);
    if(state.layers.objects&&objs.length){for(let i=0;i<objs.length;i++){const o=objs[i],x=p.x+(i-(objs.length-1)/2)*16;scene.append(svg(o.type==='portal'?'rect':'circle',o.type==='portal'?{x:x-5,y:p.y-7,width:10,height:10,class:'obj-icon'}:{cx:x,cy:p.y-2,r:o.type==='town'?7:4,class:'obj-icon'}));}}
    if(state.layers.labels){scene.append(svg('text',{x:p.x,y:p.y+24,class:'obj-label'},objectName(objs.find(o=>o.type==='town')||objs[0])));scene.append(svg('text',{x:p.x,y:p.y-20,class:'tile-id'},id));}
  }
  scene.append(svg('g',{id:'edgeHover'}));transform();
}
function select(id){state.selected=id;render();details();}
function showEdge(t,d){const g=$('edgeHover');if(!g)return;g.replaceChildren();if(t&&d!==null)line(g,...segment(t,d),{class:'edge-highlight'});}
function fact(parent,label,value){parent.append(el('dt',label),el('dd',value??'待定'));}
function details(){
  const host=$('details');host.replaceChildren();const m=mapNow();if(!m||!state.world||state.invalid.has(m.id)||!state.selected){host.append(el('p','选择一个地块，查看辖区、对象与六个方向。','muted'));return;}
  const ts=tilesOf(m),t=ts.get(state.selected);if(!t)return;const info=group(t);host.append(el('h3',`${t.id} · ${TERRAIN[t.terrain]}`));const dl=el('dl');fact(dl,'辖区',t.jurisdiction?`${t.jurisdiction} ${info.town.name}`:'无辖区');fact(dl,'行省',info.town?`${info.town.province} ${info.province.name}`:'无');fact(dl,'规划区',info.province?`${info.province.region} ${info.region.name}`:'无');fact(dl,'初始归属',info.town?`${info.town.faction} ${info.faction.name}`:'无');fact(dl,'辐射初值',t.radiation===null?'待定':String(t.radiation));host.append(dl);
  host.append(el('h3','地表对象'));for(const o of objectsAt(m,t.id)){const box=el('div',undefined,'edge-row');box.append(el('strong',`${o.id} · ${objectName(o)}`),el('p',TYPES[o.type],'muted'));if(o.route)routeDetails(box,o);host.append(box);}
  host.append(el('h3','六方向接边'));
  DIRS.forEach(([q,r,name],d)=>{const b=ts.get(tileID(t.q+q,t.r+r));const row=el('div',undefined,'edge-row');row.tabIndex=0;row.append(el('strong',`${name} · ${b?b.id:'地图外'}`));if(b){const e=effectiveEdge(m,t.id,b.id);row.append(el('p',`${e.state==='open'?'开放':'关闭'} · ${e.derived?'默认陆地边':({land:'陆地',water:'水体',mountain:'山体'}[e.landform])} · ${({none:'无设施',road:'道路',bridge:'桥梁',ford:'涉水'}[e.facility])}`),el('p',`跨边总代价 ${e.cost} · ${e.effects.length?e.effects.join('；'):'无额外效果'}`));row.append(button('查看邻格',()=>select(b.id)));}else row.append(el('p','无相邻地块 · 不可达','muted'));
    row.addEventListener('mouseenter',()=>showEdge(t,d));row.addEventListener('mouseleave',()=>showEdge(null,null));row.addEventListener('focus',()=>showEdge(t,d));row.addEventListener('blur',()=>showEdge(null,null));host.append(row);});
}
function routeDetails(box,o){
  const r=state.world.routes.find(r=>r?.id===o.route);if(!r)return;
  box.append(el('p',`${r.name} · ${r.type==='special'?'特殊入口':'普通跨区'} · ${r.direction==='both'?'双向':r.direction==='a_to_b'?'A→B':'B→A'} · 代价 ${r.cost===null?'待定':r.cost}`));
  box.append(el('p',`A：${r.a?`${r.a.map}/${r.a.tile}`:'端点待定'}；B：${r.b?`${r.b.map}/${r.b.tile}`:'端点待定'}`));
  for(const c of r.conditions)box.append(el('p',c));if(r.effects.length)box.append(el('p','效果：'+r.effects.join('；')));
  const isA=r.a?.map===state.current&&r.a.tile===o.tile,isB=r.b?.map===state.current&&r.b.tile===o.tile;
  if(!isA&&!isB){box.append(el('p','错误：对象位置不是通路端点。','issue error'));return;}
  const target=isA?r.b:r.a;const directionAllowed=r.direction==='both'||(isA&&r.direction==='a_to_b')||(isB&&r.direction==='b_to_a');
  if(!target){box.append(el('p','端点待定 · 暂不可跳转','issue'));return;}
  if(!directionAllowed){box.append(el('p','单向反侧 · 无此方向通路','muted'));return;}
  if(!state.maps.has(target.map)){box.append(el('p','区域未加载 · 请补选目标文件','issue info'));return;}
  if(state.invalid.has(target.map)){box.append(el('p','目标区域配置错误 · 暂不可跳转','issue error'));return;}
  const b=button('跳转查看另一端',()=>switchMap(target.map,target.tile));box.append(b);
}
function search(){
  const host=$('results');host.replaceChildren();const query=$('search').value.trim().toLowerCase();if(!query||!state.world)return;let count=0;
  for(const [id,{data:m}] of state.maps){if(state.invalid.has(id))continue;for(const t of m.tiles){const g=group(t),os=objectsAt(m,t.id);const hay=[id,m.name,t.id,t.jurisdiction,g.town?.name,g.town?.province,g.province?.name,g.province?.region,g.region?.name,g.town?.faction,g.faction?.name,...os.flatMap(o=>[o.id,objectName(o),o.route])].filter(Boolean).join(' ').toLowerCase();if(!hay.includes(query))continue;if(count++>=40)continue;const b=button(`${objectName(os[0])||g.town?.name||t.id}`,()=>switchMap(id,t.id),'result');b.append(el('small',`${m.name} / ${t.id}`));host.append(b);}}
  host.append(el('p',count?`${count} 个位置${count>40?'，显示前40项，请缩小搜索范围':''}`:'已加载区域中无匹配位置。','muted'));
}
function transform(){const v=state.view;$('scene').setAttribute('transform',`translate(${v.x} ${v.y}) scale(${v.k})`);$('zoom').textContent=`${Math.round(v.k*100)}%`;}
function fit(){const m=mapNow();if(!m||!state.world||state.invalid.has(m.id)||!m.tiles.length)return;const pts=m.tiles.map(point);const xmin=Math.min(...pts.map(p=>p.x))-SIZE-25,xmax=Math.max(...pts.map(p=>p.x))+SIZE+25,ymin=Math.min(...pts.map(p=>p.y))-SIZE-25,ymax=Math.max(...pts.map(p=>p.y))+SIZE+25;const rect=$('map').getBoundingClientRect();const k=Math.max(.05,Math.min(2,(rect.width-50)/(xmax-xmin),(rect.height-135)/(ymax-ymin)));state.view={k,x:rect.width/2-(xmin+xmax)/2*k,y:rect.height/2-(ymin+ymax)/2*k};transform();}
function focusTile(id){const m=mapNow(),t=m&&tilesOf(m).get(id);if(!t||state.invalid.has(m.id))return;const p=point(t),rect=$('map').getBoundingClientRect();state.view.x=rect.width/2-p.x*state.view.k;state.view.y=rect.height/2-p.y*state.view.k;transform();}
function zoom(factor,x,y){const rect=$('map').getBoundingClientRect();x=x??rect.width/2;y=y??rect.height/2;const v=state.view,k=Math.min(5,Math.max(.05,v.k*factor));v.x=x-(x-v.x)*k/v.k;v.y=y-(y-v.y)*k/v.k;v.k=k;transform();}
let drag=null,dragMoved=false;
$('map').addEventListener('pointerdown',e=>{if(e.button!==0)return;drag={x:e.clientX,y:e.clientY,vx:state.view.x,vy:state.view.y};dragMoved=false;});
window.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;if(Math.hypot(dx,dy)>4)dragMoved=true;if(dragMoved){state.view.x=drag.vx+dx;state.view.y=drag.vy+dy;transform();}});
window.addEventListener('pointerup',()=>{drag=null;});window.addEventListener('pointercancel',()=>{drag=null;});
$('map').addEventListener('wheel',e=>{e.preventDefault();const r=$('map').getBoundingClientRect();zoom(Math.exp(-e.deltaY*.001),e.clientX-r.left,e.clientY-r.top);},{passive:false});
$('map').addEventListener('keydown',e=>{if(e.target!==$('map'))return;const moves={ArrowLeft:[45,0],ArrowRight:[-45,0],ArrowUp:[0,45],ArrowDown:[0,-45]};if(moves[e.key]){e.preventDefault();state.view.x+=moves[e.key][0];state.view.y+=moves[e.key][1];transform();}else if(['+','=','-'].includes(e.key)){e.preventDefault();zoom(e.key==='-'?.8:1.25);}else if(e.key==='Home'){e.preventDefault();fit();}});
$('files').addEventListener('change',()=>loadFiles([...$('files').files]));$('fit').addEventListener('click',fit);$('in').addEventListener('click',()=>zoom(1.25));$('out').addEventListener('click',()=>zoom(.8));$('search').addEventListener('input',search);for(const id of ['kind','province'])$(id).addEventListener('change',render);
for(const [key,name] of Object.entries({terrain:'地形底色',borders:'城镇辖区边界',edges:'接边、河流与桥梁',objects:'地表对象',labels:'名称与坐标'})){const label=el('label',undefined,'layer');const input=el('input');input.type='checkbox';input.checked=true;input.addEventListener('change',()=>{state.layers[key]=input.checked;render();});label.append(input,document.createTextNode(name));$('layers').append(label);}
new ResizeObserver(()=>fit()).observe($('map'));
