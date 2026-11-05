import asyncio
import copy
import math
import pytest
from backend.algorithm import KNOT_TO_MPS, RiskConfig
from backend.engine import Engine
from backend.motion_control import MotionController
from backend.routes import FittedRoute, curve_point
from backend.scene_editor import SceneDefinition, cases, preview


def case(name):
    return SceneDefinition(**next(c['scene'] for c in cases() if c['id']==name))


def test_curve_interpolates_waypoints_and_travels_at_constant_speed():
    points=[(0,0),(1000,0),(1000,1000),(2200,700)]
    route=FittedRoute(points)
    for i,p in enumerate(points[:-1]):
        assert curve_point(points,i,0)==pytest.approx(p)
        assert curve_point(points,i,1)==pytest.approx(points[i+1])
    assert route.at_distance(0)[:2]==pytest.approx(points[0])
    assert route.at_distance(route.length+100)[:2]==pytest.approx(points[-1])
    previous=route.at_distance(0)
    for d in range(5,int(route.length)-5,5):
        current=route.at_distance(d)
        assert math.hypot(current[0]-previous[0],current[1]-previous[1])==pytest.approx(5,abs=.06)
        previous=current
    linear=FittedRoute(points,smooth=False)
    assert linear.length==pytest.approx(sum(math.dist(a,b) for a,b in zip(points,points[1:])))
    assert route.length>linear.length


@pytest.mark.parametrize('name',['angle_90','curved_crossing'])
def test_stop_hold_resume_preserves_route_progress(name):
    scene=case(name).runtime_scene()
    own=scene['ships'][0]
    controller=MotionController(scene['ships'],own.mmsi,scene['auto_stop'])
    held_samples=0
    previous=None
    minimum=float('inf')
    for elapsed in range(scene['duration']+1):
        states=controller.advance(elapsed,1793844000+elapsed)
        current=own.motion_at(controller.progress[own.mmsi])
        target=scene['ships'][1].motion_at(controller.progress[scene['ships'][1].mmsi])
        minimum=min(minimum,math.dist(current[:2],target[:2]))
        if previous:
            assert math.dist(current[:2],previous[:2])<=own.sog*KNOT_TO_MPS+.03
        if controller.held:
            held_samples+=1
            assert states[own.mmsi].sog==0
            if previous: assert current[:2]==pytest.approx(previous[:2])
        previous=current
    assert held_samples>5
    assert minimum>=scene['auto_stop']['stop_distance_m']-1e-6
    assert [e['kind'] for e in controller.events]==['stop','resume']
    assert controller.progress[own.mmsi]<scene['duration']
    assert controller.progress[scene['ships'][1].mmsi]==scene['duration']
    assert not controller.held


@pytest.mark.parametrize('name',['angle_150','angle_180','s_curve'])
def test_obstructed_routes_stop_both_ships_at_configured_clearance(name):
    scene=case(name).runtime_scene()
    own,target=scene['ships']
    controller=MotionController(scene['ships'],own.mmsi,scene['auto_stop'])
    for elapsed in range(scene['duration']+1):
        states=controller.advance(elapsed,1793844000+elapsed)
        a=own.motion_at(controller.progress[own.mmsi]);b=target.motion_at(controller.progress[target.mmsi])
        assert math.dist(a[:2],b[:2])>=scene['auto_stop']['stop_distance_m']-1e-6
        if target.mmsi in controller.contact_holds:
            assert states[own.mmsi].sog==states[target.mmsi].sog==0
    assert controller.held
    assert target.mmsi in controller.contact_holds
    assert not any(e['kind']=='resume' for e in controller.events)
    assert sum(e['kind']=='target_stop' for e in controller.events)==1
    assert '双方停车' in controller.reason


def test_swept_guard_blocks_a_fast_target_even_when_both_endpoints_are_safe():
    scene=case('angle_180').runtime_scene()
    own,target=scene['ships']
    own.x=own.y=own.sog=0
    target.x=-700;target.y=0;target.sog=60;target.cog=90
    controller=MotionController(scene['ships'],own.mmsi,scene['auto_stop'])
    controller.advance(0,1793844000)
    # A 60 s step would move the target from -700 m to +1152 m through own ship.
    states=controller.advance(60,1793844060)
    assert target.mmsi in controller.contact_holds
    assert controller.progress[target.mmsi]==0
    assert states[target.mmsi].sog==0


def test_an_initially_close_pair_can_separate_but_cannot_get_closer():
    scene=case('angle_180').runtime_scene()
    own,target=scene['ships']
    own.x=own.y=own.sog=0
    target.x=250;target.y=0;target.sog=10;target.cog=90
    controller=MotionController(scene['ships'],own.mmsi,scene['auto_stop'])
    for t in range(80): controller.advance(t,1793844000+t)
    assert controller.progress[target.mmsi]==79
    assert not controller.contact_holds
    target.cog=270
    controller=MotionController(scene['ships'],own.mmsi,scene['auto_stop'])
    for t in range(80): controller.advance(t,1793844000+t)
    assert controller.progress[target.mmsi]==0
    assert target.mmsi in controller.contact_holds
    assert controller.public()['protected_distances_m'][target.mmsi]==250


def test_waypoint_endpoint_stops_and_old_scene_defaults_are_supported():
    raw=copy.deepcopy(case('angle_90').model_dump())
    raw.pop('auto_stop')
    raw['ships'][0]['waypoints']=[{'x':-500,'y':300},{'x':200,'y':0}]
    definition=SceneDefinition(**raw)
    ship=definition.runtime_scene()['ships'][0]
    assert definition.auto_stop.enabled
    last=ship.motion_at(10000)
    assert last[:2]==pytest.approx((200,0))
    assert last[2]==0
    assert preview(definition,RiskConfig())['routes'][0]['length_m']>0
    raw['ships'][0]['waypoints']=[{'x':raw['ships'][0]['x'],'y':raw['ships'][0]['y']}]
    with pytest.raises(ValueError,match='至少相距'): SceneDefinition(**raw)


def test_controlled_ais_is_stationary_and_replay_is_deterministic(tmp_path):
    async def run():
        e=Engine(tmp_path/'motion.db',0)
        await e.start()
        try:
            e.persist_report()
            e.scenario_id='custom'
            e.custom_scene=case('angle_90').runtime_scene()
            e.chosen_own=e.custom_scene['ships'][0].mmsi
            await e.reset(save_previous=False)
            for t in range(1,451):
                await e.tick(t)
                snapshot=e.snapshot()
                frames=snapshot['render_frames']
                assert 1<=len(frames)<=65
                assert frames[-1]['time']==t
                for vessel in snapshot['vessels']:
                    pose=frames[-1]['poses'][vessel['mmsi']]
                    assert (pose['x'],pose['y'])==pytest.approx((vessel['x'],vessel['y']),abs=1e-5)
                    assert pose['sog']==vessel['sog']
                if e.controller.held:
                    held_poses=[f['poses'][e.own_mmsi] for f in frames[-4:]]
                    assert len({(p['x'],p['y']) for p in held_poses})==1 or math.dist((held_poses[0]['x'],held_poses[0]['y']),(held_poses[-1]['x'],held_poses[-1]['y']))<.2
            rows=copy.deepcopy(e.rows)
            events=copy.deepcopy(e.controller.events)
            held=[r for r in rows if r['own_held']]
            assert held
            assert all(r['own_sog']==0 for r in held)
            assert len({(r['own_latitude'],r['own_longitude']) for r in held})==1
            assert e.stats['errors']==0
            assert e.stats['received']==e.stats['sent']
            await e.reset()
            for t in range(1,451): await e.tick(t)
            assert e.rows==rows
            assert e.controller.events==events
            assert e.snapshot()['motion_control']['own_held'] is False
        finally: await e.close()
    asyncio.run(run())
