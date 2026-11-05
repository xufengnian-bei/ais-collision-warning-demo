import React,{useEffect,useRef,useState} from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {Focus, Layers, Minus, Plus, Compass, Navigation} from 'lucide-react';
import type {Snapshot,Vessel} from './types';

const color = (v:Vessel) => v.is_own?'#54d7f1':v.stale?'#7890a3':v.risk?.predicted_warning?'#ff796c':v.risk?.in_scope===false?'#7a8ba0':'#f3c16b';
function icon(v:Vessel,selected:boolean){
 const c=color(v);
 return L.divIcon({className:'vessel-icon',iconSize:[32,42],iconAnchor:[16,21],html:`<div class="boat ${v.risk?.predicted_warning?'danger':''} ${selected?'selected':''}" style="--boat:${c};transform:rotate(${v.cog}deg)"><svg width="32" height="42" viewBox="0 0 32 42"><path d="M16 3 L27 25 L24 37 L8 37 L5 25 Z" fill="${c}" fill-opacity=".25" stroke="${c}" stroke-width="2"/><path d="M16 10 L16 28 M11 23 L16 18 L21 23" stroke="${c}" stroke-width="2" fill="none"/></svg></div>`});
}

export function MaritimeMap({state,selected,onSelect}:{state:Snapshot;selected:string;onSelect:(m:string)=>void}){
 const host=useRef<HTMLDivElement>(null),map=useRef<L.Map|null>(null),group=useRef<L.LayerGroup|null>(null),tile=useRef<L.TileLayer|null>(null);
 const [online,setOnline]=useState(false),[tileError,setTileError]=useState(false),[coords,setCoords]=useState('31.1000° N  /  122.2000° E');
 const lastRun=useRef('');
 useEffect(()=>{
  if(!host.current)return;
  const m=L.map(host.current,{zoomControl:false,attributionControl:false,minZoom:5,maxZoom:19}).setView([31.1,122.2],14);
  map.current=m;group.current=L.layerGroup().addTo(m);
  L.control.scale({imperial:false,position:'bottomleft'}).addTo(m);
  m.on('mousemove',(e:L.LeafletMouseEvent)=>setCoords(`${Math.abs(e.latlng.lat).toFixed(4)}° ${e.latlng.lat>=0?'N':'S'}  /  ${Math.abs(e.latlng.lng).toFixed(4)}° ${e.latlng.lng>=0?'E':'W'}`));
  const obs=new ResizeObserver(()=>m.invalidateSize());obs.observe(host.current);
  return ()=>{obs.disconnect();m.remove();map.current=null;};
 },[]);
 useEffect(()=>{
  if(!map.current)return;
  if(online){
   setTileError(false);
   tile.current=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19}).addTo(map.current);
   tile.current.on('tileerror',()=>setTileError(true));
  }else if(tile.current){tile.current.remove();tile.current=null;}
 },[online]);
 useEffect(()=>{
  const m=map.current,g=group.current;if(!m||!g)return;g.clearLayers();
  const own=state.vessels.find(v=>v.is_own);
  if(own){
   L.circle([own.latitude,own.longitude],{radius:state.config.monitor_radius_nm*1852,color:'#4789a4',weight:1,dashArray:'7 8',fillColor:'#55bfd6',fillOpacity:.025}).addTo(g);
   L.circle([own.latitude,own.longitude],{radius:state.config.monitor_radius_nm*1852/2,color:'#365366',weight:1,dashArray:'2 8',fill:false}).addTo(g);
   L.circle([own.latitude,own.longitude],{radius:state.config.emergency_distance_m,color:'#efb358',weight:1,fillColor:'#efb358',fillOpacity:.065}).addTo(g);
  }
  for(const v of state.vessels){
   const c=color(v);
   if(v.trail.length>1)L.polyline(v.trail,{color:c,weight:v.is_own?2.5:1.8,opacity:.6}).addTo(g);
   const marker=L.marker([v.latitude,v.longitude],{icon:icon(v,v.mmsi===selected),zIndexOffset:v.is_own?1000:v.mmsi===selected?900:500}).addTo(g);
   marker.bindTooltip(`<span class="map-ship-label">${v.is_own?'本船 · ':''}${v.mmsi}</span>`,{permanent:true,direction:'bottom',offset:[0,20],className:`ship-tooltip ${v.mmsi===selected?'active':''}`});
   marker.on('click',()=>onSelect(v.mmsi));
   if(v.mmsi===selected&&v.risk?.cpa&&own&&!v.stale){
    const cpa=v.risk.cpa;
    L.polyline([[own.latitude,own.longitude],cpa.own],{color:'#54d7f1',weight:1.5,dashArray:'6 6',opacity:.8}).addTo(g);
    L.polyline([[v.latitude,v.longitude],cpa.target],{color:c,weight:1.5,dashArray:'6 6',opacity:.8}).addTo(g);
    L.polyline([cpa.own,cpa.target],{color:'#ce9ffe',weight:2,dashArray:'3 4'}).addTo(g);
    for(const point of [cpa.own,cpa.target])L.circleMarker(point,{radius:4,color:'#ce9ffe',weight:1,fillOpacity:.8}).addTo(g);
   }
  }
  if(lastRun.current!==state.run_id&&state.vessels.length){
   m.fitBounds(L.latLngBounds(state.vessels.map(v=>[v.latitude,v.longitude] as [number,number])).pad(.4),{maxZoom:14,animate:false});lastRun.current=state.run_id;
  }
 },[state,selected,onSelect]);
 const focus=()=>{const own=state.vessels.find(v=>v.is_own);if(own)map.current?.setView([own.latitude,own.longitude],14);};
 return <div className="map-panel">
  <div className="map-surface" ref={host} role="region" aria-label="船舶态势地图"/>
  <div className="map-heading"><span className="live-dot"/>实时船舶态势 <small>{online?'在线地理底图':'离线地理坐标视图'}</small></div>
  <div className="map-mode"><Navigation size={12}/> 北向上 <span>WGS 84</span></div>
  <div className="map-watermark"><Compass size={46} strokeWidth={.65}/><span>AIS SITUATIONAL AWARENESS</span></div>
  <div className="map-tools"><button onClick={()=>map.current?.zoomIn()} title="放大" aria-label="放大"><Plus size={17}/></button><button onClick={()=>map.current?.zoomOut()} title="缩小" aria-label="缩小"><Minus size={17}/></button><i/><button onClick={focus} title="定位本船" aria-label="定位本船"><Focus size={17}/></button><button className={online?'active':''} onClick={()=>setOnline(!online)} title="切换在线底图" aria-label="切换在线底图"><Layers size={17}/></button></div>
  <div className="map-legend"><span><i className="cyan"/>本船</span><span><i className="amber"/>目标船</span><span><i className="red"/>预警目标</span><span className="legend-line">CPA 预测</span></div>
  <div className="map-coordinates">{coords}</div>
  {online&&<div className="osm-credit">© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors</div>}
  {tileError&&<button className="tile-error" onClick={()=>setOnline(false)}>底图加载失败 · 切回离线态势</button>}
  <div className="range-label">监测半径 {state.config.monitor_radius_nm} nm <span> / </span> 距离保护 {state.config.emergency_distance_m} m</div>
 </div>;
}
