import asyncio
import io
import json
import zipfile
import pytest
from backend.algorithm import iso
from backend.engine import Engine
from backend.exporter import bundle
from backend.importer import load_tracks
from backend.scenarios import SCENARIOS


def test_all_scenarios_over_real_udp(tmp_path):
    async def run():
        e=Engine(tmp_path/'udp.db',0,auto_stop_default=False)
        await e.start()
        summary={}
        try:
            for key in SCENARIOS:
                e.persist_report()
                e.scenario_id=key
                await e.reset(save_previous=False)
                for elapsed in range(1,e.duration+1): await e.tick(elapsed)
                report=e.report()
                summary[key]={"events":report['event_count'],"targets":report['targets']}
                assert e.stats['errors']==0
                assert e.stats['sent']==e.stats['received']
                assert len(e.rows)==(e.duration+1)*(len(e.definitions())-1)
                assert report['complete']
                if key in ('parallel','safe','receding'): assert not e.events,key
                else: assert e.events,key
                if key=='emergency':
                    assert e.events[0]['start_time']==e.start_time
                    assert e.events[0]['reason']=='距离阈值'
                if key in ('head_on','crossing','overtaking'):
                    assert report['targets'][0]['warning_lead_time_to_observed_closest_s']>0
            # Export to a self-contained zip; both raw NMEA and normalized CSV are importable.
            payload=bundle(e)
            with zipfile.ZipFile(io.BytesIO(payload)) as z:
                assert set(z.namelist())=={'evaluation.csv','report.json','tracks.png','transmitted.nmea','positions.csv','说明.txt'}
                for name in ('transmitted.nmea','positions.csv'):
                    tracks,info=load_tracks(z.read(name),name)
                    assert len(tracks)==2
                    assert info['valid_positions']==(e.duration+1)*2
                assert len(z.read('tracks.png'))>10000
        finally: await e.close()
        return summary
    summary=asyncio.run(run())
    (tmp_path/'scenario-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))


def test_duplicate_async_dropout_and_persisted_report(tmp_path):
    async def run():
        e=Engine(tmp_path/'fault.db',0,auto_stop_default=False)
        await e.start()
        try:
            e.faults={'asynchronous':True,'duplicate':True,'dropout':True}
            await e.reset()
            for elapsed in range(1,116): await e.tick(elapsed)
            assert e.stats['duplicates']>0
            assert e.stats['errors']==0
            assert e.metrics['413000101']['data_quality']=='stale'
            assert not e.metrics['413000101']['predicted_warning']
            assert any(v['stale'] for v in e.snapshot()['vessels'])
            old_id=e.run_id
            e.persist_report()
            e.config.risk_threshold=.8
            await e.reset(save_previous=False)
            old=json.loads(e.db.execute('SELECT report FROM runs WHERE id=?',(old_id,)).fetchone()[0])
            assert old['metadata']['config']['risk_threshold']==.72
            # Out-of-order packets do not move the vessel backwards in event time.
            from backend.ais import encode_position
            ship=SCENARIOS['mixed']['ships'][0]
            e.receive(encode_position(ship.state(10),'A',True)[0],('127.0.0.1',1))
            e.receive(encode_position(ship.state(5),'A',True)[0],('127.0.0.1',1))
            assert e.stats['out_of_order']==1
            assert e.latest[ship.mmsi].timestamp==e.start_time+10
        finally: await e.close()
    asyncio.run(run())
