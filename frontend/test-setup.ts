import {afterEach,vi} from 'vitest';
import {cleanup} from '@testing-library/react';
afterEach(()=>{cleanup();vi.unstubAllGlobals();localStorage.clear();});

// JSDOM supplies DOM event dispatch; SVG hit testing and visual layout remain browser QA.
class TestPointerEvent extends MouseEvent {
 pointerId:number;
 constructor(type:string,init:PointerEventInit={}){super(type,init);this.pointerId=init.pointerId??1;}
}
class TestPoint {
 x:number;y:number;
 constructor(x=0,y=0){this.x=x;this.y=y;}
 matrixTransform(){return this;}
}
Object.defineProperty(window,'PointerEvent',{value:TestPointerEvent,configurable:true});
Object.defineProperty(globalThis,'PointerEvent',{value:TestPointerEvent,configurable:true});
Object.defineProperty(globalThis,'DOMPoint',{value:TestPoint,configurable:true});
Object.defineProperty(SVGElement.prototype,'getScreenCTM',{value:()=>({inverse:()=>({})}),configurable:true});
Object.defineProperty(SVGElement.prototype,'setPointerCapture',{value:()=>{},configurable:true});
Object.defineProperty(SVGElement.prototype,'hasPointerCapture',{value:()=>true,configurable:true});
Object.defineProperty(SVGElement.prototype,'releasePointerCapture',{value:()=>{},configurable:true});
