import type {EditableShip,Waypoint} from './types';
type P=[number,number];
const lerp=(a:P,b:P,ta:number,tb:number,t:number):P=>{const q=(t-ta)/(tb-ta);return [a[0]+(b[0]-a[0])*q,a[1]+(b[1]-a[1])*q];};
export function curvePoint(points:P[],segment:number,u:number,smooth=true):P{
 const p1=points[segment],p2=points[segment+1];
 if(!smooth||points.length===2)return lerp(p1,p2,0,1,u);
 const p0=points[segment-1]||[2*p1[0]-p2[0],2*p1[1]-p2[1]] as P;
 const p3=points[segment+2]||[2*p2[0]-p1[0],2*p2[1]-p1[1]] as P;
 const delta=(a:P,b:P)=>Math.sqrt(Math.max(Math.hypot(a[0]-b[0],a[1]-b[1]),1e-8));
 const t0=0,t1=delta(p0,p1),t2=t1+delta(p1,p2),t3=t2+delta(p2,p3),t=t1+u*(t2-t1);
 const a1=lerp(p0,p1,t0,t1,t),a2=lerp(p1,p2,t1,t2,t),a3=lerp(p2,p3,t2,t3,t);
 return lerp(lerp(a1,a2,t0,t2,t),lerp(a2,a3,t1,t3,t),t1,t2,t);
}
export function plannedPoints(ship:EditableShip):P[]{
 const points:P[]=[[ship.x,ship.y]];
 for(const p of ship.waypoints||[])if(Math.hypot(p.x-points.at(-1)![0],p.y-points.at(-1)![1])>.001)points.push([p.x,p.y]);
 if(points.length<2)return [];
 const result:P[]=[points[0]];
 for(let i=0;i<points.length-1;i++)for(let j=1;j<=48;j++)result.push(curvePoint(points,i,j/48,ship.interpolation!=='linear'));
 return result;
}
export function initialHeading(ship:EditableShip):number{
 const route=plannedPoints(ship);
 return route.length>1?(Math.atan2(route[1][0]-route[0][0],route[1][1]-route[0][1])*180/Math.PI+360)%360:ship.cog;
}
