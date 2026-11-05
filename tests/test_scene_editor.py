import asyncio
import copy
import io
import json
import zipfile
import pytest
from fastapi.testclient import TestClient
from backend import app as module
from backend.algorithm import RiskConfig, velocity
from backend.engine import Engine
from backend.scene_editor import SceneDefinition, cases, preview


@pytest.mark.parametrize("case",cases(),ids=lambda c:c['id'])
def test_angle_cases_and_full_custom_simulation(case,tmp_path):
    scene=SceneDefinition(**case['scene'])
    result=preview(scene,RiskConfig())
    if 'angle' in case: assert result['heading_angle_deg']==pytest.approx(case['angle'])
    assert result['scene']['ships'][0]['x']==case['scene']['ships'][0]['x']
    async def run():
        engine=Engine(tmp_path/'case.db',0)
        await engine.start()
        try:
            engine.persist_report()
            engine.scenario_id='custom'
            engine.custom_scene=scene.runtime_scene()
            # Reference risk regressions use unmodified motion; controlled motion is tested separately.
            engine.custom_scene['auto_stop']['enabled']=False
            engine.chosen_own=scene.ships[0].mmsi
            await engine.reset(save_previous=False)
            for elapsed in range(1,scene.duration+1): await engine.tick(elapsed)
            assert len(engine.rows)==scene.duration+1
            assert engine.stats['sent']==engine.stats['received']
            assert engine.stats['errors']==0
            if case['id'] in ('parallel','safe_crossing','curved_safe'):
                assert not engine.events
            elif case.get('category')!='曲线':
                assert engine.events
                assert engine.report()['targets'][0]['warning_lead_time_to_observed_closest_s']>0
            assert engine.report()['metadata']['scene_definition']['name']==scene.name
        finally: await engine.close()
    asyncio.run(run())


def test_edit_save_run_export_restore_scene(tmp_path,monkeypatch):
    db=tmp_path/'scenes.db'
    monkeypatch.setattr(module,'engine',Engine(db,0))
    scene=copy.deepcopy(cases()[3]['scene'])
    scene['name']='我的双船场景'
    scene['ships'][0].update(x=-950,y=125,sog=12.5,cog=75)
    scene['ships'][1].update(x=200,y=-1100,sog=8,cog=340)
    scene['duration']=180
    with TestClient(module.app) as client:
        assert len(client.get('/api/cases').json())==14
        response=client.post('/api/scene/preview',json=scene)
        assert response.status_code==200
        assert response.json()['heading_angle_deg']==pytest.approx(95)
        saved=client.post('/api/custom-scenarios',json=scene)
        assert saved.status_code==200
        saved_id=saved.json()['id']
        assert client.get('/api/custom-scenarios').json()[0]['scene']==scene
        initial=client.post('/api/simulation',json={'scene':scene,'autoplay':False,'speed':5}).json()
        assert initial['scenario']=='custom'
        assert initial['scenario_name']==scene['name']
        assert not initial['running']
        assert initial['speed']==5
        assert initial['duration']==180
        for state,expected in zip(initial['vessels'],scene['ships']):
            assert state['x']==pytest.approx(expected['x'],abs=.3)
            assert state['y']==pytest.approx(expected['y'],abs=.3)
            assert state['sog']==expected['sog']
            assert state['cog']==expected['cog']
        stepped=client.post('/api/control',json={'action':'step'}).json()
        vx,vy=velocity(12.5,75)
        assert stepped['vessels'][0]['x']-initial['vessels'][0]['x']==pytest.approx(vx,abs=.3)
        assert stepped['vessels'][0]['y']-initial['vessels'][0]['y']==pytest.approx(vy,abs=.3)
        old_id=initial['run_id']
        client.post('/api/control',json={'action':'complete'})
        exported=client.get('/api/export/zip')
        with zipfile.ZipFile(io.BytesIO(exported.content)) as z:
            restored=json.loads(z.read('scene.json'))
            assert client.post('/api/scene/preview',json=restored).json()['scene']==scene
        reset=client.post('/api/control',json={'action':'seek','elapsed':20}).json()
        assert reset['run_id']!=old_id
        assert reset['elapsed']==20
        assert reset['scene_definition']['ships'][0]['x']==-950
        invalid=copy.deepcopy(scene)
        invalid['ships'][1]['mmsi']=invalid['ships'][0]['mmsi']
        assert client.post('/api/simulation',json={'scene':invalid}).status_code==422
        invalid=copy.deepcopy(scene)
        invalid['ships'][0]['sog']=-1
        assert client.post('/api/scene/preview',json=invalid).status_code==422
        invalid=copy.deepcopy(scene)
        invalid['ships'][0]['cog']=360
        assert client.post('/api/scene/preview',json=invalid).status_code==422
        assert client.get('/api/state').json()['run_id']==reset['run_id']
    # Saved scenes survive a backend restart.
    monkeypatch.setattr(module,'engine',Engine(db,0))
    with TestClient(module.app) as client:
        assert client.get('/api/custom-scenarios').json()[0]['id']==saved_id
        assert client.delete('/api/custom-scenarios/'+saved_id).status_code==200
        assert client.get('/api/custom-scenarios').json()==[]
        assert client.delete('/api/custom-scenarios/'+saved_id).status_code==404
