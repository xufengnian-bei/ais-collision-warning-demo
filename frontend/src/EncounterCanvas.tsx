import React,{useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {Focus,Hand,LocateFixed,Minus,MousePointer2,Plus,Route} from 'lucide-react';
import type {EditableShip,Snapshot} from './types';
import {plannedPoints,initialHeading} from './routes';
import {hullScale,MotionPlayback} from './playback';
import type {RenderFrame} from './types';

const COLORS=['#61d5ed','#f0bb70'];
export const boatPath='M0 -24 L13 4 L10 23 L-10 23 L-13 4 Z';
const knots=.5144444444;

function drawFleet(svg:SVGSVGElement|null,frame:RenderFrame,half:number){
 if(!svg)return;
 svg.querySelectorAll<SVGGElement>('[data-vessel-position]').forEach(node=>{
  const pose=frame.poses[node.dataset.vesselPosition!];if(!pose)return;
  node.setAttribute('transform',`translate(${500+pose.x/half*295},${350-pose.y/half*295})`);
  node.querySelector('[data-vessel-heading]')?.setAttribute('transform',`rotate(${pose.cog})`);
  const vector=node.querySelector('[data-vessel-vector]'),theta=pose.cog*Math.PI/180;
  vector?.setAttribute('x2',String(Math.sin(theta)*82));vector?.setAttribute('y2',String(-Math.cos(theta)*82));
  const label=node.querySelector('[data-vessel-motion]');
  if(label)label.textContent=`${Number(pose.sog.toFixed(1))} kn / ${Number(pose.cog.toFixed(1))}°`;
 });
}

export function CaseSketch({ships}:{ships:EditableShip[]}){
 const extent=Math.max(1200,...ships.flatMap(s=>[Math.abs(s.x),Math.abs(s.y),...(s.waypoints||[]).flatMap(p=>[Math.abs(p.x),Math.abs(p.y)])]))*1.3;
 return <svg viewBox="0 0 110 74" aria-hidden="true"><path d="M0 37H110 M55 0V74" stroke="#284758" strokeWidth=".6" strokeDasharray="2 3"/>{ships.map((s,i)=>{const x=55+s.x/extent*35,y=37-s.y/extent*28,cog=initialHeading(s),route=plannedPoints(s);return <g key={i}>{route.length?<polyline points={route.map(p=>`${55+p[0]/extent*35},${37-p[1]/extent*28}`).join(' ')} fill="none" stroke={COLORS[i]} opacity=".6" strokeWidth="1"/>:<path d={`M${x} ${y}l${Math.sin(cog*Math.PI/180)*30} ${-Math.cos(cog*Math.PI/180)*30}`} stroke={COLORS[i]} strokeWidth="1" strokeDasharray="3 3" opacity=".5"/>}<g transform={`translate(${x},${y}) rotate(${cog}) scale(.25)`}><path d={boatPath} fill={COLORS[i]} fillOpacity=".25" stroke={COLORS[i]} strokeWidth="4"/></g></g>;})}</svg>;
}

export function EncounterCanvas({ships,selected,onSelect,onChange,editing,tcpa,live,resetKey,plannedShips=ships,waypointMode=false,onWaypointMode}:{ships:EditableShip[];selected:number;onSelect:(n:number)=>void;onChange:(n:number,patch:Partial<EditableShip>)=>void;editing:boolean;tcpa:number|null|undefined;live:Snapshot|null;resetKey?:string;plannedShips?:EditableShip[];waypointMode?:boolean;onWaypointMode?:(enabled:boolean)=>void}){
 const svg=useRef<SVGSVGElement>(null),drag=useRef<{index:number;kind:'position'|'heading'|'waypoint';pointerId:number;waypoint?:number}|null>(null);
 const [half,setHalf]=useState(2500),[placing,setPlacing]=useState(false),[pointer,setPointer]=useState<[number,number]|null>(null);
 const playback=useRef(new MotionPlayback());
 const routes=useMemo(()=>plannedShips.map(plannedPoints),[plannedShips]);
 const protection=live?.motion_control?.settings?.stop_distance_m||live?.config.emergency_distance_m||350;
 const bodyClearance=Math.min(protection,...Object.values(live?.motion_control?.protected_distances_m||{}));
 const bodyScale=editing?1:hullScale(half,bodyClearance);
 // Only SVG transforms and the two labels change at display refresh rate.
 // Routes, risk charts and the editor continue updating at snapshot frequency.
 useLayoutEffect(()=>{
  if(editing||!live)return;
  const now=performance.now();playback.current.update(live,now);drawFleet(svg.current,playback.current.sample(now),half);
 },[live,editing,half]);
 const animated=!editing&&Boolean(live?.running);
 useEffect(()=>{
  if(!animated)return;
  let handle=0;
  const frame=(now:number)=>{drawFleet(svg.current,playback.current.sample(now),half);handle=requestAnimationFrame(frame);};
  handle=requestAnimationFrame(frame);
  return()=>cancelAnimationFrame(handle);
 },[animated,half]);
 const project=(x:number,y:number):[number,number]=>[500+x/half*295,350-y/half*295];
 const unproject=(p:DOMPoint):[number,number]=>[(p.x-500)/295*half,(350-p.y)/295*half];
 const point=(e:React.PointerEvent)=>{const matrix=svg.current?.getScreenCTM();return matrix?new DOMPoint(e.clientX,e.clientY).matrixTransform(matrix.inverse()):null;};
 const fit=()=>setHalf(Math.max(1500,Math.ceil(Math.max(...plannedShips.flatMap(s=>[Math.abs(s.x),Math.abs(s.y),...(s.waypoints||[]).flatMap(p=>[Math.abs(p.x),Math.abs(p.y)])]))*1.35/500)*500));
 const identity=ships.map(s=>s.mmsi).join(',');
 useEffect(()=>{if(!drag.current){const extent=Math.max(...ships.flatMap(s=>[Math.abs(s.x),Math.abs(s.y)]));if(extent>half*.9)setHalf(Math.ceil(extent*1.25/500)*500);}},[ships,editing,half]);
 useEffect(()=>{if(resetKey&&!drag.current)fit();},[resetKey]);
 useEffect(()=>{setPlacing(false);},[editing,identity]);
 const begin=(e:React.PointerEvent,index:number,kind:'position'|'heading'|'waypoint',waypoint?:number)=>{onSelect(index);if(!editing)return;e.stopPropagation();e.preventDefault();setPlacing(false);drag.current={index,kind,pointerId:e.pointerId,waypoint};svg.current?.setPointerCapture(e.pointerId);};
 const move=(e:React.PointerEvent)=>{
  const p=point(e);if(!p)return;const xy=unproject(p);setPointer(xy);
  const d=drag.current;if(!d||!editing)return;
  if(d.kind==='position')onChange(d.index,{x:Math.max(-10000,Math.min(10000,Math.round(xy[0]))),y:Math.max(-10000,Math.min(10000,Math.round(xy[1])))});
  else if(d.kind==='waypoint')onChange(d.index,{waypoints:(plannedShips[d.index].waypoints||[]).map((p,i)=>i===d.waypoint?{x:Math.max(-10000,Math.min(10000,Math.round(xy[0]))),y:Math.max(-10000,Math.min(10000,Math.round(xy[1])))}:p)});
  else{const s=ships[d.index],[sx,sy]=project(s.x,s.y);const angle=(Math.atan2(p.x-sx,sy-p.y)*180/Math.PI+360)%360;onChange(d.index,{cog:Math.round(angle)%360});}
 };
 const end=(e:React.PointerEvent)=>{if(drag.current){if(svg.current?.hasPointerCapture(e.pointerId))svg.current.releasePointerCapture(e.pointerId);drag.current=null;}};
 const gridStep=half<=2000?250:half<=5000?500:half<=10000?1000:Math.ceil(half/5000)*1000;
 const ticks=[];for(let n=-Math.floor(half/gridStep)*gridStep;n<=half;n+=gridStep)ticks.push(n);
 const active=ships[selected],liveTarget=live?.vessels.find(v=>!v.is_own),warning=liveTarget?.risk?.predicted_warning;
 return <div className={`encounter-canvas ${placing||waypointMode?'placing':''}`}>
  <div className="canvas-title"><span className={live?.running?'live-dot':'paused-dot'}/><strong>{editing?'摆放船舶，构建会遇场景':live?.running?'会遇仿真进行中':'会遇仿真已暂停'}</strong><span>局部东 / 北坐标 · m</span></div>
  <div className="canvas-north"><span>N</span><svg width="22" height="35" viewBox="0 0 22 35"><path d="M11 2L20 29L11 23L2 29Z" fill="#91b6c9" fillOpacity=".3" stroke="#91b6c9"/></svg></div>
  <svg ref={svg} className="encounter-svg" viewBox="0 0 1000 700" aria-label={editing?'双船场景编辑画布':'双船会遇仿真画布'} onPointerMove={move} onPointerUp={end} onPointerCancel={end} onPointerLeave={()=>{if(!drag.current)setPointer(null);}} onPointerDown={e=>{if((!placing&&!waypointMode)||!editing)return;const p=point(e);if(!p)return;const [x,y]=unproject(p);const position={x:Math.max(-10000,Math.min(10000,Math.round(x))),y:Math.max(-10000,Math.min(10000,Math.round(y)))};if(waypointMode){if((plannedShips[selected].waypoints||[]).length<32)onChange(selected,{waypoints:[...(plannedShips[selected].waypoints||[]),position]});}else{onChange(selected,position);setPlacing(false);}}}>
   <defs><radialGradient id="encounter-ocean"><stop offset="0" stopColor="#17394a" stopOpacity=".6"/><stop offset="1" stopColor="#0d2231" stopOpacity="0"/></radialGradient></defs><rect width="1000" height="700" fill="url(#encounter-ocean)"/>
   {ticks.map(n=>{const [x,y]=project(n,n);return <g key={n}><line x1={x} x2={x} y1="45" y2="655" stroke={n===0?'#406478':'#274454'} strokeWidth={n===0?1:.6} strokeDasharray={n===0?'5 7':'2 6'}/><line x1="45" x2="955" y1={y} y2={y} stroke={n===0?'#406478':'#274454'} strokeWidth={n===0?1:.6} strokeDasharray={n===0?'5 7':'2 6'}/><text x={x+4} y="646" fontSize="11" fill="#63899f">{n}</text><text x="54" y={y-5} fontSize="11" fill="#63899f">{n}</text></g>;})}
   <text x="927" y="681" textAnchor="end" fill="#7fa0b4" fontSize="12">东 X / m</text><text x="53" y="34" fill="#7fa0b4" fontSize="12">北 Y / m</text>
   {plannedShips.map((s,i)=>{const route=routes[i];return route.length>0&&<g key={`plan-${s.mmsi}`}><polyline points={route.map(p=>project(...p).join(',')).join(' ')} fill="none" stroke={COLORS[i]} strokeWidth="2" strokeDasharray="7 6" opacity=".5"/>{(s.waypoints||[]).map((p,j)=>{const [x,y]=project(p.x,p.y);return <g key={j} transform={`translate(${x},${y})`} className="waypoint-node" role={editing?'button':undefined} aria-label={editing?`拖动${i===0?'本船':'目标船'}航点 ${j+1}`:undefined} tabIndex={editing?0:-1} onPointerDown={e=>{if(editing)begin(e,i,'waypoint',j);}} onKeyDown={e=>{if(editing&&e.key==='Delete')onChange(i,{waypoints:s.waypoints!.filter((_,n)=>n!==j)});}}><circle r="16" fill={COLORS[i]} fillOpacity=".06"/><circle r="9" fill="#112637" stroke={COLORS[i]} strokeWidth="1.5"/><text textAnchor="middle" dy="4" fill={COLORS[i]} fontSize="10">{j+1}</text></g>;})}</g>;})}
   {!editing&&live?.vessels.map((v,i)=><polyline key={v.mmsi} points={v.trajectory_xy.map(p=>project(...p).join(',')).join(' ')} fill="none" stroke={COLORS[i%2]} strokeWidth="2.5" opacity=".65"/>)}
   {ships.map((original,i)=>{const s=editing?{...original,cog:initialHeading(original)}:original;const [x,y]=project(s.x,s.y),theta=s.cog*Math.PI/180,dx=Math.sin(theta),dy=-Math.cos(theta);const future=editing&&!s.waypoints?.length&&tcpa!=null&&tcpa>=0&&tcpa<=1800?project(s.x+s.sog*knots*dx*tcpa,s.y-s.sog*knots*dy*tcpa):null;return <g key={s.mmsi}>
    {future&&<><line x1={x} y1={y} x2={future[0]} y2={future[1]} stroke={COLORS[i]} strokeWidth="1.4" strokeDasharray="7 8" opacity=".45"/><circle cx={future[0]} cy={future[1]} r="5" fill="none" stroke={COLORS[i]} opacity=".6"/></>}
    <g data-vessel-position={s.mmsi} transform={`translate(${x},${y})`}>
    {!editing&&i===0&&<circle r={protection/half*295} fill="#ebac5b" fillOpacity=".04" stroke="#d49b56" strokeOpacity=".4" strokeDasharray="5 7"/>}
    <line data-vessel-vector x1="0" y1="0" x2={dx*82} y2={dy*82} stroke={COLORS[i]} strokeWidth="1.5" opacity=".8"/>
    <g className={`canvas-ship ${i===selected?'selected':''} ${!editing&&i===1&&warning?'alert':''}`}>
     <circle r="37" fill={COLORS[i]} fillOpacity={i===selected ? .045 : 0} stroke={COLORS[i]} strokeOpacity={i===selected ? .5 : .15} strokeDasharray="4 5"/>
     <g data-vessel-heading transform={`rotate(${s.cog})`} role="button" aria-label={`拖动${i===0?'本船':'目标船'}位置`} tabIndex={editing?0:-1} onPointerDown={e=>begin(e,i,'position')} onKeyDown={e=>{if(!editing)return;const delta=e.shiftKey?100:10;const patch:Partial<EditableShip>={};if(e.key==='ArrowLeft')patch.x=s.x-delta;if(e.key==='ArrowRight')patch.x=s.x+delta;if(e.key==='ArrowUp')patch.y=s.y+delta;if(e.key==='ArrowDown')patch.y=s.y-delta;if(Object.keys(patch).length){e.preventDefault();onSelect(i);onChange(i,patch);}}}>
      <circle r="30" fill="transparent"/><g data-vessel-hull transform={`scale(${bodyScale})`}><path d={boatPath} fill={COLORS[i]} fillOpacity=".22" stroke={COLORS[i]} strokeWidth="2"/><path d="M0 -12V11M-5 -1L0 -7L5 -1" fill="none" stroke={COLORS[i]} strokeWidth="2"/></g>
     </g>
     <text y="55" textAnchor="middle" fill={COLORS[i]} fontSize="14" fontWeight="500">{s.name===(i===0?'本船':'目标船')?s.name:`${i===0?'本船':'目标船'} · ${s.name}`}</text><text data-vessel-motion y="73" textAnchor="middle" fill="#90aebe" fontSize="11">{s.sog} kn / {s.cog}°</text>
    </g>
    </g>
    {editing&&!s.waypoints?.length&&<g className="heading-handle" role="button" aria-label={`旋转${i===0?'本船':'目标船'}航向`} tabIndex={0} transform={`translate(${x+dx*82},${y+dy*82})`} onPointerDown={e=>begin(e,i,'heading')} onKeyDown={e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();onChange(i,{cog:(s.cog+(e.key==='ArrowLeft'?-5:5)+360)%360});}}}><circle r="15" fill={COLORS[i]} fillOpacity=".06"/><circle r="7" fill="#122c3b" stroke={COLORS[i]} strokeWidth="1.8"/><circle r="2" fill={COLORS[i]}/></g>}
   </g>;})}
  </svg>
  <div className="canvas-tools"><button onClick={()=>setHalf(Math.max(500,half/1.5))} title="放大画布" aria-label="放大场景"><Plus size={16}/></button><button onClick={()=>setHalf(Math.min(100000,half*1.5))} title="缩小画布" aria-label="缩小场景"><Minus size={16}/></button><button onClick={fit} title="适合画布" aria-label="适合画布"><Focus size={16}/></button></div>
  {editing&&<div className="canvas-selection"><button className={selected===0?'own-selected':''} onClick={()=>onSelect(0)}><i/>本船</button><button className={selected===1?'target-selected':''} onClick={()=>onSelect(1)}><i/>目标船</button><span/><button className={placing?'active':''} onClick={()=>{setPlacing(!placing);onWaypointMode?.(false);}}><LocateFixed size={13}/>{placing?'点击画布放置':'点击摆放'}</button>{onWaypointMode&&<button className={waypointMode?'active':''} onClick={()=>{setPlacing(false);onWaypointMode(!waypointMode);}}><Route size={13}/>{waypointMode?'完成航点':'添加航点'}</button>}</div>}
  {(live?.motion_control?.own_held||!!live?.motion_control?.contact_holds?.length)&&<div className="canvas-stop-badge"><strong>{live?.motion_control?.contact_holds?.length?'双方停车 · 航路受阻':'主船停车等待'}</strong><span>{live?.motion_control?.reason}</span></div>}
  <div className="canvas-instructions">{editing?<><MousePointer2 size={12}/>{waypointMode?`点击画布依次添加${selected===0?'本船':'目标船'}航点，可拖动编号点修改`:placing?`点击画布设置${selected===0?'本船':'目标船'}初始位置`:'拖动船体摆放 · 圆点转向 · 编号航点可拖动'}</>:<><Hand size={12}/>虚线为原航迹 · 实线为实际航迹 · 停车后从原处续航</>}</div>
  <div className="canvas-coords">{pointer?`X ${Math.round(pointer[0])} m  /  Y ${Math.round(pointer[1])} m`:`已选${selected===0?'本船':'目标船'} · X ${Math.round(active.x)} / Y ${Math.round(active.y)} m`}</div>
 </div>;
}
