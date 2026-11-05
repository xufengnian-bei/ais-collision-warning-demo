"""Centripetal Catmull–Rom interpolation with arc-length based travel."""
from bisect import bisect_left
from math import atan2, ceil, degrees, hypot, sqrt


def blend(a,b,ta,tb,t):
    q=(t-ta)/(tb-ta)
    return (a[0]+(b[0]-a[0])*q,a[1]+(b[1]-a[1])*q)


def curve_point(points,segment,u,smooth=True):
    p1,p2=points[segment],points[segment+1]
    if not smooth or len(points)==2: return blend(p1,p2,0,1,u)
    p0=points[segment-1] if segment else (2*p1[0]-p2[0],2*p1[1]-p2[1])
    p3=points[segment+2] if segment+2<len(points) else (2*p2[0]-p1[0],2*p2[1]-p1[1])
    t0=0.
    t1=t0+sqrt(max(hypot(p1[0]-p0[0],p1[1]-p0[1]),1e-8))
    t2=t1+sqrt(max(hypot(p2[0]-p1[0],p2[1]-p1[1]),1e-8))
    t3=t2+sqrt(max(hypot(p3[0]-p2[0],p3[1]-p2[1]),1e-8))
    t=t1+u*(t2-t1)
    a1,a2,a3=blend(p0,p1,t0,t1,t),blend(p1,p2,t1,t2,t),blend(p2,p3,t2,t3,t)
    return blend(blend(a1,a2,t0,t2,t),blend(a2,a3,t1,t3,t),t1,t2,t)


class FittedRoute:
    def __init__(self,points,smooth=True):
        self.points=[]
        for point in points:
            p=tuple(point)
            if not self.points or hypot(p[0]-self.points[-1][0],p[1]-self.points[-1][1])>1e-6:
                self.points.append(p)
        self.smooth=smooth
        self.samples=[self.points[0]]
        self.locations=[(0,0.)]
        self.lengths=[0.]
        for segment in range(len(self.points)-1):
            a,b=self.points[segment:segment+2]
            steps=max(32,min(256,ceil(hypot(b[0]-a[0],b[1]-a[1])/8)))
            for j in range(1,steps+1):
                p=curve_point(self.points,segment,j/steps,smooth)
                previous=self.samples[-1]
                self.lengths.append(self.lengths[-1]+hypot(p[0]-previous[0],p[1]-previous[1]))
                self.samples.append(p)
                self.locations.append((segment,j/steps))
        self.length=self.lengths[-1]

    def at_distance(self,distance):
        d=max(0,min(distance,self.length))
        i=min(max(1,bisect_left(self.lengths,d)),len(self.samples)-1)
        segment,u1=self.locations[i]
        previous_segment,u0=self.locations[i-1]
        if previous_segment!=segment: u0=0.
        span=self.lengths[i]-self.lengths[i-1]
        q=(d-self.lengths[i-1])/span if span>1e-12 else 0.
        u=u0+(u1-u0)*q
        p=curve_point(self.points,segment,u,self.smooth)
        a=curve_point(self.points,segment,max(0,u-1e-4),self.smooth)
        b=curve_point(self.points,segment,min(1,u+1e-4),self.smooth)
        cog=degrees(atan2(b[0]-a[0],b[1]-a[1]))%360
        return p[0],p[1],cog

    def public_points(self,limit=300):
        stride=max(1,ceil(len(self.samples)/limit))
        result=self.samples[::stride]
        if result[-1]!=self.samples[-1]: result.append(self.samples[-1])
        return result
