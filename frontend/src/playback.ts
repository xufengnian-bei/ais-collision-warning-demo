import type {RenderFrame,RenderPose,Snapshot} from './types';

const clamp=(n:number,min:number,max:number)=>Math.max(min,Math.min(n,max));
export function interpolateHeading(a:number,b:number,q:number){
 return (a+((b-a+540)%360-180)*q+360)%360;
}

/** All vessels share one clock. Interpolate executed frames, never extrapolate. */
export class MotionPlayback {
 private frames:RenderFrame[]=[];
 private runId='';
 private elapsed=-1;
 private speed=1;
 private held=new Set<string>();
 private from=0;
 private to=0;
 private started=0;
 private duration=0;

 private time(now:number){
  return this.from+(this.to-this.from)*(this.duration?clamp((now-this.started)/this.duration,0,1):1);
 }

 update(state:Snapshot,now:number){
  const incoming=state.render_frames?.length?state.render_frames:[{time:state.elapsed,poses:Object.fromEntries(state.vessels.map(v=>[v.mmsi,{x:v.x,y:v.y,sog:v.sog,cog:v.cog}]))}];
  const latest=incoming.at(-1)!;
  const held=new Set([...(state.motion_control?.own_held?[state.own_mmsi]:[]),...(state.motion_control?.contact_holds||[])]);
  const newlyHeld=[...held].some(mmsi=>!this.held.has(mmsi));
  const reset=!this.frames.length||this.runId!==state.run_id||!state.running||newlyHeld||this.speed!==state.speed||state.elapsed<this.elapsed||state.elapsed-this.elapsed>Math.max(3,state.speed*.35);
  this.held=held;
  this.runId=state.run_id;
  this.speed=state.speed;
  if(!reset&&state.elapsed===this.elapsed)return;
  const current=this.time(now);
  this.elapsed=state.elapsed;
  const merged=new Map((reset?[]:this.frames).map(frame=>[frame.time,frame]));
  incoming.forEach(frame=>merged.set(frame.time,frame));
  this.frames=[...merged.values()].sort((a,b)=>a.time-b.time);
  this.from=reset||current<this.frames[0].time?latest.time:Math.min(current,latest.time);
  this.to=latest.time;
  this.started=now;
  this.duration=reset?0:Math.min(1000,Math.max(0,(this.to-this.from)/Math.max(.01,state.speed)*1000));
  this.frames=this.frames.filter((frame,i,all)=>frame.time>=this.from||i===all.length-1||all[i+1].time>=this.from);
 }

 sample(now:number):RenderFrame {
  const time=this.time(now);
  if(!this.frames.length)return {time,poses:{}};
  let low=0,high=this.frames.length-1;
  while(low<high){const middle=Math.floor((low+high)/2);if(this.frames[middle].time<time)low=middle+1;else high=middle;}
  const b=this.frames[low],a=this.frames[Math.max(0,low-1)];
  const q=b.time>a.time?clamp((time-a.time)/(b.time-a.time),0,1):1;
  const poses:Record<string,RenderPose>={};
  for(const [mmsi,target] of Object.entries(b.poses)){
   const start=a.poses[mmsi]||target;
   poses[mmsi]={x:start.x+(target.x-start.x)*q,y:start.y+(target.y-start.y)*q,sog:start.sog+(target.sog-start.sog)*q,cog:interpolateHeading(start.cog,target.cog,q)};
  }
  return {time,poses};
 }
}

/** Limit the visible hull to 40% of the protection radius at any zoom. */
export const hullScale=(half:number,clearance:number)=>Math.min(1,Math.max(0,clearance)*.4*295/(half*27));
