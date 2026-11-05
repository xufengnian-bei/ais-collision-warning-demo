import React,{useEffect,useState} from 'react';
import {ArrowDown,ArrowUp,Download,Flag,Navigation,Plus,RotateCcw,Route,Save,ShieldCheck,Ship,Trash2} from 'lucide-react';
import {clock,defaultStop,fmt,type EditableScene,type EditableShip,type Event,type Risk,type ScenePreview,type Snapshot,type StopSettings} from './types';
import {initialHeading} from './routes';

export function NumericInput({value,onValue,...props}:Omit<React.InputHTMLAttributes<HTMLInputElement>,'value'|'onChange'> & {value:number;onValue:(value:number)=>void}){
 const [text,setText]=useState(String(value));
 useEffect(()=>setText(String(value)),[value]);
 return <input {...props} type="number" value={text} onChange={e=>{setText(e.target.value);if(e.target.value!==''&&Number.isFinite(Number(e.target.value)))onValue(Number(e.target.value));}} onBlur={()=>setText(String(value))}/>;
}

type Props={draft:EditableScene;selected:number;editing:boolean;locked:boolean;state:Snapshot;preview:ScenePreview|null;previewError:string;metrics:Risk|undefined;first:Event|null|undefined;waypointMode:boolean;onWaypointMode:(value:boolean)=>void;onSelect:(n:number)=>void;onChangeShip:(index:number,patch:Partial<EditableShip>)=>void;onChangeScene:(patch:Partial<EditableScene>)=>void;onSave:()=>void;onRestore:()=>void;onBack:()=>void;onExport:()=>void};

export function SceneProperties(p:Props){
 const {draft,selected,editing,locked,state,preview,previewError,metrics,first}=p;
 const [tab,setTab]=useState<'motion'|'route'|'safety'>('motion'),[page,setPage]=useState(0);
 const own=draft.ships[selected],role=selected===0?'本船':'目标船',waypoints=own.waypoints||[],safety=draft.auto_stop||defaultStop;
 const change=(patch:Partial<EditableShip>)=>p.onChangeShip(selected,patch);
 const changeSafety=(patch:Partial<StopSettings>)=>p.onChangeScene({auto_stop:{...safety,...patch}});
 useEffect(()=>setPage(0),[selected]);
 useEffect(()=>{if(p.waypointMode)setTab('route');},[p.waypointMode]);
 const startRoute=(interpolation:'smooth'|'linear')=>{
  if(waypoints.length){change({interpolation});return;}
  const angle=own.cog*Math.PI/180,dx=Math.sin(angle),dy=Math.cos(angle);
  const bound=(n:number)=>Math.max(-10000,Math.min(10000,n));
  change({interpolation,waypoints:[{x:bound(Math.round(own.x+dx*550+dy*220)),y:bound(Math.round(own.y+dy*550-dx*220))},{x:bound(Math.round(own.x+dx*1300)),y:bound(Math.round(own.y+dy*1300))}]});
 };
 const movePoint=(index:number,offset:number)=>{const next=[...waypoints],target=index+offset;if(target<0||target>=next.length)return;[next[index],next[target]]=[next[target],next[index]];change({waypoints:next});};
 const blocked=Boolean(state.motion_control?.contact_holds?.length),held=state.motion_control?.own_held||blocked;
 return <aside className="scene-properties"><div className="properties-heading"><Navigation size={16}/><h3>{editing?'场景参数':'起始参数'}</h3>{editing?<span>可编辑</span>:<button disabled={locked} onClick={p.onBack}>修改参数</button>}</div>
  <div className="property-tabs" role="tablist" aria-label="场景参数分类">{([['motion','运动参数'],['route','航点轨迹'],['safety','停车保护']] as const).map(([value,label])=><button key={value} role="tab" aria-selected={tab===value} className={tab===value?'active':''} onClick={()=>setTab(value)}>{label}</button>)}</div>
  <div className="vessel-selector">{draft.ships.map((s,i)=><button type="button" className={`${i===selected?'selected':''} ${i===0?'own':'target'}`} key={s.mmsi} onClick={()=>p.onSelect(i)}><Ship size={15}/>{i===0?'本船':'目标船'}{s.waypoints?.length?<small>曲线</small>:null}</button>)}</div>
  <fieldset className="property-fields" disabled={!editing||locked}>
   <div className="property-tabpanel" hidden={tab!=='motion'}>
    <label className="scene-name-field">场景名称<input aria-label="自定义场景名称" maxLength={60} value={draft.name} onChange={e=>p.onChangeScene({name:e.target.value})}/></label>
    <div className={`selected-vessel-title ${selected===0?'own':'target'}`}><i/><strong>{role}参数</strong><span>{own.mmsi}</span></div>
    <label className="lab-text-field">船舶名称<input aria-label={`${role}名称`} value={own.name} maxLength={40} onChange={e=>change({name:e.target.value})}/></label>
    <div className="position-fields"><label>东向 X <span>m</span><NumericInput min={-10000} max={10000} step={10} aria-label={`${role}东向位置`} value={own.x} onValue={x=>change({x})}/></label><label>北向 Y <span>m</span><NumericInput min={-10000} max={10000} step={10} aria-label={`${role}北向位置`} value={own.y} onValue={y=>change({y})}/></label></div>
    <label className="slider-field"><div><span>航速 SOG</span><NumericInput aria-label={`${role}航速`} min={0} max={60} step={.5} value={own.sog} onValue={sog=>change({sog})}/><small>kn</small></div><input type="range" min={0} max={60} step={.5} aria-label={`${role}航速滑块`} value={own.sog} onChange={e=>change({sog:Number(e.target.value)})}/><span><em>0</em><em>30</em><em>60 kn</em></span></label>
    <label className="slider-field"><div><span>{waypoints.length?'起始航向 · 随轨迹变化':'航向 COG'}</span><NumericInput aria-label={`${role}航向`} disabled={!!waypoints.length} min={0} max={359} step={1} value={waypoints.length?Math.round(initialHeading(own)):own.cog} onValue={cog=>change({cog})}/><small>°</small></div><input disabled={!!waypoints.length} type="range" min={0} max={359} step={1} aria-label={`${role}航向滑块`} value={waypoints.length?Math.round(initialHeading(own)):own.cog} onChange={e=>change({cog:Number(e.target.value)})}/><span><em>0° 北</em><em>90° 东</em><em>180° 南</em><em>270° 西</em></span></label>
    <div className="direction-presets">{[['北',0],['东',90],['南',180],['西',270]].map(([label,cog])=><button key={label} disabled={!!waypoints.length} type="button" className={own.cog===cog?'active':''} onClick={()=>change({cog:cog as number})}><Navigation size={12} style={{transform:`rotate(${Number(cog)-45}deg)`}}/>{label}</button>)}</div>
   </div>
   <div className="property-tabpanel route-editor" hidden={tab!=='route'}>
    <label className="route-mode">{role}运动方式<select aria-label={`${role}轨迹方式`} value={waypoints.length?(own.interpolation||'smooth'):'heading'} onChange={e=>{if(e.target.value==='heading'){change({waypoints:[]});p.onWaypointMode(false);}else startRoute(e.target.value as 'smooth'|'linear');}}><option value="heading">按航向直线运动</option><option value="smooth">航点平滑曲线</option><option value="linear">航点折线</option></select></label>
    <p className="route-help">在画布依次添加航点，拖动编号点可修改。平滑曲线穿过航点，航向沿曲线自动变化。</p>
    <div className="route-actions"><button className={p.waypointMode?'active':''} type="button" disabled={waypoints.length>=32} onClick={()=>p.onWaypointMode(!p.waypointMode)}><Plus size={13}/>{p.waypointMode?'完成添加':'画布添加航点'}</button><button type="button" disabled={!waypoints.length} onClick={()=>change({waypoints:[]})}><Trash2 size={12}/>清空</button></div>
    <div className="waypoint-list-title"><span>{waypoints.length} 个航点 <small>起点由船位设置</small></span><span>{preview?.routes?.[selected]?.length_m?`${fmt(preview.routes[selected].length_m,0)} m`:''}</span></div>
    <div className="waypoint-list">{waypoints.slice(page*2,page*2+2).map((point,j)=>{const index=page*2+j;return <div className="waypoint-row" key={index}><div><b>{index+1}</b><span>航点 {index+1}</span><button type="button" aria-label={`上移航点 ${index+1}`} disabled={index===0} onClick={()=>movePoint(index,-1)}><ArrowUp size={11}/></button><button type="button" aria-label={`下移航点 ${index+1}`} disabled={index===waypoints.length-1} onClick={()=>movePoint(index,1)}><ArrowDown size={11}/></button><button type="button" aria-label={`删除航点 ${index+1}`} onClick={()=>{change({waypoints:waypoints.filter((_,i)=>i!==index)});setPage(Math.max(0,Math.min(page,Math.ceil((waypoints.length-1)/2)-1)));}}><Trash2 size={11}/></button></div><label>X <NumericInput aria-label={`${role}航点 ${index+1} X`} value={point.x} min={-10000} max={10000} onValue={x=>change({waypoints:waypoints.map((v,i)=>i===index?{...v,x}:v)})}/></label><label>Y <NumericInput aria-label={`${role}航点 ${index+1} Y`} value={point.y} min={-10000} max={10000} onValue={y=>change({waypoints:waypoints.map((v,i)=>i===index?{...v,y}:v)})}/></label></div>;})}{!waypoints.length&&<div className="empty-route"><Route size={25}/><span>为这艘船添加一条航迹</span><small>可以只给其中一艘船设置航点</small></div>}</div>
    {waypoints.length>2&&<div className="waypoint-pagination"><button type="button" disabled={page===0} onClick={()=>setPage(page-1)}>上一页</button><span>{page+1} / {Math.ceil(waypoints.length/2)}</span><button type="button" disabled={(page+1)*2>=waypoints.length} onClick={()=>setPage(page+1)}>下一页</button></div>}
    <p className="route-help endpoint-note">以设定航速沿航迹推进，到达最后一个航点后停船。</p>
   </div>
   <div className="property-tabpanel safety-editor" hidden={tab!=='safety'}>
    <label className="safety-switch"><ShieldCheck size={17}/><span>主船自动停车保护</span><input type="checkbox" aria-label="启用主船自动停车" checked={safety.enabled} onChange={e=>changeSafety({enabled:e.target.checked})}/></label>
    <p className="route-help">主船提前检查停车位置是否占道。目标船能安全通过时继续航行；无法留出保护距离时双方停车。航路清空后沿原轨迹续航。</p>
    {([['stop_distance_m','停车保护距离','m'],['resume_distance_m','恢复安全距离','m'],['lookahead_s','提前检查时间','s'],['safe_duration_s','连续安全确认','s']] as const).map(([key,label,unit])=><label className="safety-value" key={key}>{label}<NumericInput aria-label={label} value={safety[key]} min={1} onValue={v=>changeSafety({[key]:v})}/><small>{unit}</small></label>)}
    <p className="route-help safety-note">双船均遵守保护距离。正面同线等无法通行的场景会持续等待，可修改航点留出通道。恢复距离应大于停车距离。</p>
   </div>
   <label className="duration-field">仿真时长<select aria-label="场景仿真时长" value={draft.duration} onChange={e=>p.onChangeScene({duration:Number(e.target.value)})}>{[...new Set([draft.duration,60,120,300,600,900,1200,1800,3600])].sort((a,b)=>a-b).map(n=><option value={n} key={n}>{n/60} 分钟</option>)}</select></label>
  </fieldset>
  {previewError&&<div className="scene-validation" role="alert">{previewError}</div>}
  {editing?<div className="properties-actions"><button className="button" disabled={locked||!!previewError||!preview} onClick={p.onSave}><Save size={14}/>保存场景</button><button className="text-button" disabled={locked} onClick={p.onRestore}><RotateCcw size={12}/>恢复示例</button></div>:<div className={`live-result ${held||metrics?.predicted_warning?'alert':''}`}><div><span className={held||metrics?.predicted_warning?'warning-indicator':'live-dot'}/><strong>{blocked?'双方停车 · 航路受阻':held?'主船停车等待':metrics?.predicted_warning?'碰撞风险预警':state.elapsed>=state.duration?'仿真完成':'沿原航迹航行'}</strong></div><p>{held?state.motion_control?.reason:state.motion_control?.reason||metrics?.warning_reason||'等待有效状态'}</p><span><Flag size={12}/>首次预警 <b>{first?clock(first.start_time):'尚未触发'}</b></span><button className="button" disabled={locked} onClick={p.onExport}><Download size={13}/>导出仿真结果</button></div>}
 </aside>;
}
