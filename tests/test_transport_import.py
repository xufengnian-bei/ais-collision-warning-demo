from dataclasses import replace
import pytest
from backend.ais import AISDecoder, encode_position, encode_static
from backend.scenarios import SCENARIOS
from backend.importer import load_tracks, state_at


@pytest.mark.parametrize("ais_class",["A","B"])
def test_nmea_static_dynamic_timestamp_round_trip(ais_class):
    state=SCENARIOS["mixed"]["ships"][0].state(120)
    d=AISDecoder()
    for line in encode_static(state,ais_class): d.parse(line)
    raw=encode_position(state,ais_class,own=True)[0]
    r=d.parse(raw)
    assert "!AIVDO," in raw
    assert r["timestamp"]==state.timestamp
    assert r["latitude"]==pytest.approx(state.latitude,abs=2e-6)
    assert r["ship_type"]==70
    assert (r["nav_status"] is None)==(ais_class=="B")


def test_bad_checksum_and_missing_import_timestamp_rejected():
    state=SCENARIOS["mixed"]["ships"][0].state(0)
    raw=encode_position(state)[0]
    with pytest.raises(ValueError): AISDecoder().parse(raw[:-2]+"ZZ")
    without_tag=raw[raw.index('!'):]
    with pytest.raises(ValueError,match="完整时间戳"): AISDecoder().parse(without_tag,require_timestamp=True)


def test_sort_deduplicate_supplement_and_gap_limit():
    csv="""mmsi,timestamp,latitude,longitude,sog,cog
413000001,2026-11-05T02:00:10Z,31.1,122.201,,
413000002,2026-11-05T02:00:00Z,31.11,122.2,10,90
413000001,2026-11-05T02:00:00Z,31.1,122.2,,
413000001,2026-11-05T02:00:10Z,31.1,122.201,,
413000002,2026-11-05T02:01:00Z,31.11,122.203,10,90
"""
    tracks,report=load_tracks(csv.encode(),"test.csv")
    assert report["duplicates_removed"]==1
    assert report["motion_supplemented"]==2
    a=tracks['413000001']
    assert a[0].timestamp<a[1].timestamp
    assert 18<a[0].sog<19
    assert a[0].cog==pytest.approx(90,abs=.1)
    assert state_at(a,a[0].timestamp+5).quality=="interpolated"
    b=tracks['413000002']
    assert state_at(b,b[0].timestamp+10,max_gap=30) is None
    assert state_at(a,a[0].timestamp-1) is None


def test_nmea_import_round_trip():
    raw=[]
    for elapsed in (0,5,10):
        for ship in SCENARIOS["head_on"]["ships"]:
            raw.extend(encode_static(ship.state(elapsed),ship.ais_class))
            raw.extend(encode_position(ship.state(elapsed),ship.ais_class))
    tracks,report=load_tracks('\n'.join(raw).encode(),"test.nmea")
    assert report["valid_positions"]==6
    assert report["issues"]==[]
    assert len(tracks)==2
