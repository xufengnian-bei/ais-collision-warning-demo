import React from 'react';
import {afterEach,describe,expect,it,vi} from 'vitest';
import {act,render} from '@testing-library/react';
import {EncounterCanvas} from './EncounterCanvas';
import {hullScale,interpolateHeading,MotionPlayback} from './playback';
import type {EditableShip,RenderFrame,Snapshot} from './types';

const own='413000001',target='413000101';
const frame=(time:number,x=time*100,y=0):RenderFrame=>({time,poses:{[own]:{x,y,sog:10,cog:90},[target]:{x:x+500,y:100,sog:10,cog:90}}});
function state(elapsed:number,frames:RenderFrame[],patch:Partial<Snapshot>={}):Snapshot{
 return {run_id:'run',elapsed,running:true,speed:10,own_mmsi:own,render_frames:frames,vessels:[],motion_control:{enabled:true,own_held:false,contact_holds:[]},...patch} as Snapshot;
}
afterEach(()=>vi.restoreAllMocks());

describe('verified-frame playback',()=>{
 it('follows curve keyframes with one shared clock and never extrapolates',()=>{
  const playback=new MotionPlayback();playback.update(state(0,[frame(0)]),0);
  playback.update(state(1,[frame(0),frame(.25,25,6.25),frame(.5,50,25),frame(.75,75,56.25),frame(1,100,100)]),100);
  const sample=playback.sample(150);
  expect(sample.time).toBeCloseTo(.5);
  expect(sample.poses[own]).toMatchObject({x:50,y:25});
  expect(sample.poses[target].x).toBe(550);
  expect(playback.sample(10000)).toEqual(frame(1,100,100));
 });

 it('immediately freezes on a stop, then smoothly draws the passing target',()=>{
  const playback=new MotionPlayback();playback.update(state(0,[frame(0)]),0);
  playback.update(state(1,[frame(0),frame(1)]),100);
  expect(playback.sample(150).poses[own].x).toBe(50);
  const held=(t:number)=>{const f=frame(t);f.poses[own]={x:100,y:0,sog:0,cog:90};return f;};
  const motion_control={enabled:true,own_held:true,contact_holds:[]};
  playback.update(state(2,[frame(1),held(2)],{motion_control}),160);
  expect(playback.sample(160).poses[own]).toMatchObject({x:100,sog:0});
  playback.update(state(3,[held(2),held(3)],{motion_control}),260);
  expect(playback.sample(310).poses[own]).toMatchObject({x:100,sog:0});
  expect(playback.sample(310).poses[target].x).toBe(750);
  playback.update(state(3,[held(3)],{motion_control,running:false}),315);
  expect(playback.sample(10000)).toEqual(held(3));
 });

 it('freezes both poses immediately when the target is blocked',()=>{
  const playback=new MotionPlayback();playback.update(state(0,[frame(0)]),0);
  playback.update(state(1,[frame(0),frame(1)]),100);
  playback.update(state(2,[frame(1),frame(2)],{motion_control:{enabled:true,own_held:true,contact_holds:[target]}}),150);
  expect(playback.sample(150)).toEqual(frame(2));
 });

 it('snaps to seeks, new runs, speed changes and paused steps',()=>{
  const playback=new MotionPlayback();playback.update(state(0,[frame(0)]),0);
  playback.update(state(100,[frame(100)]),100);
  expect(playback.sample(100).time).toBe(100);
  playback.update(state(20,[frame(20)],{run_id:'new'}),200);
  expect(playback.sample(200).time).toBe(20);
  playback.update(state(21,[frame(20),frame(21)],{run_id:'new',speed:20}),300);
  expect(playback.sample(300).time).toBe(21);
  playback.update(state(22,[frame(22)],{run_id:'new',running:false,speed:20}),310);
  expect(playback.sample(10000).time).toBe(22);
 });

 it('does not restart animation when an identical snapshot arrives',()=>{
  const playback=new MotionPlayback();playback.update(state(0,[frame(0)]),0);
  const next=state(1,[frame(0),frame(1)]);
  playback.update(next,100);playback.update(next,140);
  expect(playback.sample(150).time).toBeCloseTo(.5);
  expect(playback.sample(200).time).toBe(1);
 });

 it('takes the short turn across north and keeps hulls within their clearance',()=>{
  expect(interpolateHeading(359,1,.5)).toBe(0);
  expect(interpolateHeading(1,359,.5)).toBe(0);
  for(const half of [500,2500,10000,100000]){
   const hullRadiusM=hullScale(half,350)*27*half/295;
   expect(hullRadiusM*2).toBeLessThanOrEqual(350*.8+.001);
  }
 });
});

it('draws intermediate SVG positions via RAF and cancels animation on unmount',()=>{
 let now=0,id=0;
 const callbacks=new Map<number,FrameRequestCallback>();
 vi.spyOn(performance,'now').mockImplementation(()=>now);
 vi.stubGlobal('requestAnimationFrame',(callback:FrameRequestCallback)=>{callbacks.set(++id,callback);return id;});
 const cancel=vi.fn((handle:number)=>callbacks.delete(handle));vi.stubGlobal('cancelAnimationFrame',cancel);
 const ships:EditableShip[]=[{mmsi:own,name:'本船',x:0,y:0,sog:10,cog:90,ship_type:70,ais_class:'A',nav_status:0},{mmsi:target,name:'目标船',x:500,y:100,sog:10,cog:90,ship_type:30,ais_class:'B',nav_status:0}];
 const initial=state(0,[frame(0)],{config:{emergency_distance_m:350} as Snapshot['config']});
 const props={ships,selected:0,onSelect:()=>{},onChange:()=>{},editing:false,tcpa:null,live:initial};
 const {container,rerender,unmount}=render(<EncounterCanvas {...props}/>);
 now=100;const next={...initial,elapsed:1,render_frames:[frame(0),frame(1)]};
 rerender(<EncounterCanvas {...props} live={next}/>);
 now=150;
 act(()=>{const current=[...callbacks.values()];callbacks.clear();current.forEach(callback=>callback(now));});
 const marker=container.querySelector(`[data-vessel-position="${own}"]`)!;
 expect(marker.getAttribute('transform')).toBe(`translate(${500+50/2500*295},350)`);
 now=160;rerender(<EncounterCanvas {...props} live={{...next,running:false}}/>);
 const paused=marker.getAttribute('transform');
 act(()=>{const current=[...callbacks.values()];callbacks.clear();current.forEach(callback=>callback(5000));});
 expect(marker.getAttribute('transform')).toBe(paused);
 unmount();expect(cancel).toHaveBeenCalled();expect(callbacks.size).toBe(0);
});
