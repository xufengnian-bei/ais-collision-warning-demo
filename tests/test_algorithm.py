import math
from dataclasses import replace
import pytest
from backend.algorithm import RiskConfig, VesselState, align_live, evaluate, interpolate_state, latlon, move, z_risk


def vessel(mmsi,x,y,speed,course,t=0):
    lat,lon=latlon(x,y)
    return VesselState(mmsi,t,lat,lon,speed,course)


def test_document_numeric_example():
    values=[z_risk(316.6,300,1000),z_risk(150.8,60,240),z_risk(577.2,300,1000)]
    assert sum(values)/3==pytest.approx(.72546462753)


@pytest.mark.parametrize("x,expected",[(0,1),(300,1),(650,.5),(1000,0),(2000,0)])
def test_z_boundaries(x,expected):
    assert z_risk(x,300,1000)==expected


def test_monitoring_range_does_not_mean_alert_at_two_miles():
    result=evaluate(vessel("413000001",0,0,12,90),vessel("413000002",1852,0,12,270),RiskConfig())
    assert result["in_scope"]
    assert result["collision_risk"]<=2/3
    assert not result["predicted_warning"]


def test_receding_time_risk_zero_but_distance_protection_still_active():
    own=vessel("413000001",0,0,12,90)
    for separation,warning in [(500,False),(300,True)]:
        r=evaluate(own,vessel("413000002",-separation,0,10,270),RiskConfig())
        assert r["tcpa_s"]<0
        assert r["risk_tcpa"]==0
        assert r["predicted_warning"] is warning


def test_zero_relative_velocity_is_not_zero_tcpa():
    r=evaluate(vessel("413000001",0,0,12,90),vessel("413000002",0,700,12,90),RiskConfig())
    assert r["tcpa_s"] is None
    assert r["risk_tcpa"]==0
    assert r["dcpa_m"]==pytest.approx(r["actual_distance_m"])
    assert not r["predicted_warning"]


def test_live_alignment_is_causal_and_bounded():
    s=vessel("413000001",0,0,12,90,t=100)
    assert align_live(s,99,30) is None
    assert align_live(s,131,30) is None
    aligned=align_live(s,110,30)
    assert aligned.quality=="extrapolated"
    assert aligned.longitude>s.longitude


def test_offline_course_wrap():
    a=vessel("413000001",0,0,12,359,t=0)
    b=vessel("413000001",0,60,12,1,t=10)
    r=interpolate_state(a,b,5)
    assert min(abs(r.cog),abs(r.cog-360))<.01
    assert r.sog>11.9


@pytest.mark.parametrize("latitude,longitude",[(31.1,122.2),(37.8,-122.4),(-33.8,151.2),(60,10)])
def test_imported_regions_use_true_local_distance(latitude,longitude):
    own=VesselState("413000001",0,latitude,longitude,10,90)
    lat,lon=move(latitude,longitude,500,0)
    target=VesselState("413000002",0,lat,lon,10,270)
    r=evaluate(own,target,RiskConfig())
    assert r["actual_distance_m"]==pytest.approx(500,abs=.01)
    assert r["dcpa_m"]<.01
    assert r["tcpa_s"]>0
