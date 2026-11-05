import {expect,it} from 'vitest';
import {curvePoint,initialHeading,plannedPoints} from './routes';
import type {EditableShip} from './types';

it('fits through every waypoint and preserves line mode',()=>{
 const points:[number,number][]=[[0,0],[1000,0],[1000,1000],[2200,700]];
 for(let i=0;i<points.length-1;i++){
  expect(curvePoint(points,i,0)).toEqual(points[i]);
  const end=curvePoint(points,i,1);expect(end[0]).toBeCloseTo(points[i+1][0]);expect(end[1]).toBeCloseTo(points[i+1][1]);
 }
 expect(curvePoint(points,1,.5,false)).toEqual([1000,500]);
 const curved=curvePoint(points,1,.5);expect(curved[0]).not.toBe(1000);
});

it('draws a finite planned curve and derives heading from the curve',()=>{
 const ship:EditableShip={mmsi:'413000001',name:'test',x:0,y:0,sog:10,cog:180,ship_type:70,ais_class:'A',nav_status:0,waypoints:[{x:1000,y:0},{x:1000,y:1000}]};
 const route=plannedPoints(ship);
 expect(route[0]).toEqual([0,0]);expect(route.at(-1)).toEqual([1000,1000]);
 expect(route.every(p=>p.every(Number.isFinite))).toBe(true);
 expect(initialHeading(ship)).toBeGreaterThan(80);expect(initialHeading(ship)).toBeLessThan(100);
});
