import React,{useState} from 'react';
import {History,clock} from './types';

export function RiskChart({rows,threshold}:{rows:History[];threshold:number}){
 const [hover,setHover]=useState<number|null>(null);
 const W=660,H=134,left=30,right=16,top=12,bottom=23;
 const start=rows[0]?.time??0,end=Math.max(start+60,rows.at(-1)?.time??0);
 const x=(t:number)=>left+(t-start)/(end-start)*(W-left-right),y=(r:number)=>top+(1-r)*(H-top-bottom);
 const path=(key:'collision_risk'|'risk_dcpa'|'risk_tcpa'|'risk_distance')=>rows.map((r,i)=>`${i&&r.time-rows[i-1].time<1.5?'L':'M'}${x(r.time).toFixed(1)},${y(r[key]).toFixed(1)}`).join(' ');
 const first=rows.find(r=>r.predicted_warning),r=hover==null?undefined:rows[hover];
 return <div className="risk-chart"><svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="综合风险与三项证据趋势图" onMouseLeave={()=>setHover(null)} onMouseMove={e=>{if(!rows.length)return;const rect=e.currentTarget.getBoundingClientRect();const p=(e.clientX-rect.left)/rect.width*W;const t=start+(p-left)/(W-left-right)*(end-start);setHover(rows.reduce((best,r,i)=>Math.abs(r.time-t)<Math.abs(rows[best].time-t)?i:best,0));}}>
  <defs><linearGradient id="riskFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#45c7d9" stopOpacity=".25"/><stop offset="100%" stopColor="#45c7d9" stopOpacity="0"/></linearGradient></defs>
  {[0,.5,1].map(n=><g key={n}><line x1={left} x2={W-right} y1={y(n)} y2={y(n)} stroke="#253341" strokeDasharray="3 5"/><text x="0" y={y(n)+3} fill="#7d91a6" fontSize="9">{n.toFixed(1)}</text></g>)}
  <line x1={left} x2={W-right} y1={y(threshold)} y2={y(threshold)} stroke="#eea261" strokeDasharray="5 4" opacity=".8"/><text x={W-right} y={y(threshold)-5} textAnchor="end" fill="#eea261" fontSize="9">预警阈值 {threshold}</text>
  {rows.length>0&&<path d={`${path('collision_risk')} L${x(rows.at(-1)!.time)},${y(0)} L${x(start)},${y(0)} Z`} fill="url(#riskFill)"/>}
  {(['risk_dcpa','risk_tcpa','risk_distance'] as const).map((key,i)=><path key={key} d={path(key)} stroke={['#7d9bce','#ae8acd','#c6a66a'][i]} strokeWidth="1" opacity=".55" fill="none"/>)}
  <path d={path('collision_risk')} stroke="#53d2de" strokeWidth="2.2" fill="none"/>
  {first&&<g><line x1={x(first.time)} x2={x(first.time)} y1={top} y2={y(0)} stroke="#f18577" strokeDasharray="2 4"/><circle cx={x(first.time)} cy={y(first.collision_risk)} r="3.5" fill="#f18577"/></g>}
  {[start,(start+end)/2,end].map((t,i)=><text key={i} x={x(t)} y={H-5} fill="#7d91a6" fontSize="9" textAnchor={i===0?'start':i===2?'end':'middle'}>{rows.length?clock(t):'—'}</text>)}
  {r&&<g><line x1={x(r.time)} x2={x(r.time)} y1={top} y2={y(0)} stroke="#b4ccda" opacity=".6"/><circle cx={x(r.time)} cy={y(r.collision_risk)} r="4" fill="#53d2de"/></g>}
 </svg>{r&&<div className="chart-hover">{clock(r.time)} · 综合风险 {r.collision_risk.toFixed(3)} · 距离 {r.actual_distance_m.toFixed(0)} m</div>}</div>;
}
