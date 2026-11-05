import React,{useState} from 'react';
import {beforeEach,describe,expect,it,vi} from 'vitest';
import {fireEvent,render,screen,waitFor} from '@testing-library/react';
import {ScenarioLab} from './ScenarioLab';
import {EncounterCanvas} from './EncounterCanvas';
import type {EditableScene,EditableShip,Snapshot} from './types';

const scene:EditableScene={name:'测试双船',description:'',duration:600,ships:[{mmsi:'413000001',name:'本船',x:-1000,y:0,sog:12,cog:90,ship_type:70,ais_class:'A',nav_status:0},{mmsi:'413000101',name:'目标船',x:1000,y:0,sog:10,cog:270,ship_type:30,ais_class:'B',nav_status:0}]};
const config={distance_high_m:300,distance_low_m:1000,time_high_s:60,time_low_s:240,risk_threshold:.72,emergency_distance_m:350,monitor_radius_nm:2,max_age_s:30};
const snapshot:Snapshot={run_id:'initial',running:false,elapsed:0,duration:600,time:1793844000,time_iso:'2026-11-05T02:00:00Z',scenario:'mixed',scenario_name:'多船',scene_definition:null,source:'simulation',speed:10,config,faults:{asynchronous:false,duplicate:false,dropout:false},own_mmsi:'413000001',vessels:[],definitions:[],events:[],stats:{},udp:'127.0.0.1:10110',messages:[],histories:{},error:null};
let saved:unknown[]=[];
beforeEach(()=>{
 saved=[];
 vi.stubGlobal('fetch',vi.fn(async(url:string,options?:RequestInit)=>{
  let data:unknown={};
  if(url==='/api/cases')data=[{id:'head-on-test',category:'对遇',angle:180,scene:{...structuredClone(scene),name:'正面对遇 · 180°'}}];
  else if(url==='/api/scene/preview')data={scene:JSON.parse(options!.body as string),metrics:{actual_distance_m:2000,dcpa_m:0,tcpa_s:200,collision_risk:.33,predicted_warning:false},heading_angle_deg:180};
  else if(url==='/api/custom-scenarios'&&options?.method==='POST'){const definition=JSON.parse(options.body as string);saved.push({id:'saved-1',scene:definition});data=saved[0];}
  else if(url==='/api/custom-scenarios')data=saved;
  return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
 }));
});
const props=()=>({state:snapshot,busy:false,onRun:vi.fn(async(_scene:EditableScene,_speed:number):Promise<Snapshot|null>=>null),onControl:vi.fn(async(_action:string,_extra?:object):Promise<Snapshot|null>=>null),onMonitor:vi.fn(),onNotify:vi.fn(),onExport:vi.fn(),onSettings:vi.fn()});

describe('scene editing workflow',()=>{
 it('loads a case, edits both vessels and starts with the entered values',async()=>{
  const p=props();render(<ScenarioLab {...p}/>);
  fireEvent.click(await screen.findByRole('button',{name:/正面对遇 · 180°/}));
  fireEvent.change(screen.getByLabelText('本船东向位置'),{target:{value:'-850'}});
  fireEvent.change(screen.getByLabelText('本船航速'),{target:{value:'14.5'}});
  fireEvent.change(screen.getByLabelText('本船航向'),{target:{value:'75'}});
  fireEvent.click(screen.getAllByRole('button',{name:'目标船'})[0]);
  fireEvent.change(screen.getByLabelText('目标船北向位置'),{target:{value:'-640'}});
  fireEvent.change(screen.getByLabelText('目标船航速'),{target:{value:'8'}});
  fireEvent.change(screen.getByLabelText('目标船航向'),{target:{value:'320'}});
  await waitFor(()=>expect((screen.getByRole('button',{name:'开始仿真'}) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:'开始仿真'}));
  await waitFor(()=>expect(p.onRun).toHaveBeenCalledOnce());
  const definition=p.onRun.mock.calls[0][0] as EditableScene;
  expect(definition.ships[0]).toMatchObject({x:-850,sog:14.5,cog:75});
  expect(definition.ships[1]).toMatchObject({y:-640,sog:8,cog:320});
 });

 it('saves a named custom scene and displays it in the saved library',async()=>{
  const p=props();render(<ScenarioLab {...p}/>);
  fireEvent.change(screen.getByLabelText('自定义场景名称'),{target:{value:'我的 60 度场景'}});
  await waitFor(()=>expect((screen.getByRole('button',{name:'保存场景'}) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:'保存场景'}));
  expect(await screen.findByRole('button',{name:/^我的 60 度场景/})).toBeTruthy();
  expect(saved).toHaveLength(1);
  expect(p.onNotify).toHaveBeenCalledWith('场景已保存，可在“我的场景”重复使用');
 });

 it('keeps replay mode when seeking backwards creates a new backend run',async()=>{
  function Harness(){
   const [state,setState]=useState(snapshot);
   return <ScenarioLab {...props()} state={state} onRun={async definition=>{const next={...snapshot,run_id:'run-one',scenario:'custom',scene_definition:definition,elapsed:100};setState(next);return next;}} onControl={async()=>{const next={...snapshot,run_id:'run-two',scenario:'custom',scene_definition:scene,elapsed:20};setState(next);return next;}}/>;
  }
  render(<Harness/>);
  await waitFor(()=>expect((screen.getByRole('button',{name:'开始仿真'}) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:'开始仿真'}));
  const timeline=await screen.findByLabelText('会遇过程时间轴');
  fireEvent.change(timeline,{target:{value:'20'}});fireEvent.keyUp(timeline,{key:'ArrowLeft'});
  await waitFor(()=>expect(screen.getByText('仿真回放')).toBeTruthy());
  expect(screen.queryByRole('button',{name:'开始仿真'})).toBeNull();
  expect((screen.getByLabelText('本船东向位置') as HTMLInputElement).disabled||screen.getByLabelText('本船东向位置').closest('fieldset')?.disabled).toBe(true);
  fireEvent.click(screen.getByRole('button',{name:'返回编辑'}));
  expect(await screen.findByRole('button',{name:'开始仿真'})).toBeTruthy();
  expect(screen.getByLabelText('本船东向位置').closest('fieldset')?.disabled).toBe(false);
 });
});

it('changes position with a drag and heading with the direction handle',()=>{
 const change=vi.fn();
 function Harness(){const [ships,setShips]=useState<EditableShip[]>(structuredClone(scene.ships));return <EncounterCanvas ships={ships} selected={0} onSelect={()=>{}} editing tcpa={null} live={null} onChange={(index,patch)=>{change(index,patch);setShips(current=>current.map((s,i)=>i===index?{...s,...patch}:s));}}/>;}
 render(<Harness/>);
 const canvas=screen.getByLabelText('双船场景编辑画布');
 fireEvent.pointerDown(screen.getByRole('button',{name:'拖动本船位置'}),{pointerId:1,clientX:382,clientY:350});
 fireEvent.pointerMove(canvas,{pointerId:1,clientX:550,clientY:320});fireEvent.pointerUp(canvas,{pointerId:1});
 expect(change).toHaveBeenCalledWith(0,{x:424,y:254});
 fireEvent.pointerDown(screen.getByRole('button',{name:'旋转本船航向'}),{pointerId:2,clientX:600,clientY:320});
 fireEvent.pointerMove(canvas,{pointerId:2,clientX:550,clientY:220});fireEvent.pointerUp(canvas,{pointerId:2});
 expect(change).toHaveBeenCalledWith(0,{cog:0});
 fireEvent.keyDown(screen.getByRole('button',{name:'旋转本船航向'}),{key:'ArrowLeft'});
 expect(change).toHaveBeenCalledWith(0,{cog:355});
});

it('adds and drags waypoints for one vessel without changing the other',()=>{
 let latest:EditableShip[]=[];
 function Harness(){const [ships,setShips]=useState<EditableShip[]>(structuredClone(scene.ships));latest=ships;return <EncounterCanvas ships={ships} plannedShips={ships} selected={0} onSelect={()=>{}} editing tcpa={null} live={null} waypointMode onWaypointMode={()=>{}} onChange={(index,patch)=>setShips(current=>current.map((s,i)=>i===index?{...s,...patch}:s))}/>;}
 render(<Harness/>);
 const canvas=screen.getByLabelText('双船场景编辑画布');
 fireEvent.pointerDown(canvas,{pointerId:1,clientX:600,clientY:250});
 fireEvent.pointerDown(canvas,{pointerId:2,clientX:700,clientY:350});
 expect(latest[0].waypoints).toHaveLength(2);expect(latest[1].waypoints).toBeUndefined();
 expect(screen.queryByRole('button',{name:'旋转本船航向'})).toBeNull();
 fireEvent.pointerDown(screen.getByRole('button',{name:'拖动本船航点 1'}),{pointerId:3,clientX:600,clientY:250});
 fireEvent.pointerMove(canvas,{pointerId:3,clientX:550,clientY:320});fireEvent.pointerUp(canvas,{pointerId:3});
 expect(latest[0].waypoints).toHaveLength(2);expect(latest[0].waypoints![0]).toEqual({x:424,y:254});
});

it('edits a smooth route and stop/resume thresholds before running',async()=>{
 const p=props();render(<ScenarioLab {...p}/>);
 fireEvent.click(screen.getByRole('tab',{name:'航点轨迹'}));
 fireEvent.change(screen.getByLabelText('本船轨迹方式'),{target:{value:'smooth'}});
 fireEvent.change(screen.getByLabelText('本船航点 1 X'),{target:{value:'-500'}});
 fireEvent.click(screen.getByRole('tab',{name:'停车保护'}));
 fireEvent.change(screen.getByLabelText('停车保护距离'),{target:{value:'300'}});
 fireEvent.change(screen.getByLabelText('恢复安全距离'),{target:{value:'650'}});
 await waitFor(()=>expect((screen.getByRole('button',{name:'开始仿真'}) as HTMLButtonElement).disabled).toBe(false));
 fireEvent.click(screen.getByRole('button',{name:'开始仿真'}));
 await waitFor(()=>expect(p.onRun).toHaveBeenCalledOnce());
 const sent=p.onRun.mock.calls[0][0];expect(sent.ships[0].interpolation).toBe('smooth');expect(sent.ships[0].waypoints![0].x).toBe(-500);expect(sent.auto_stop).toMatchObject({enabled:true,stop_distance_m:300,resume_distance_m:650});
});
