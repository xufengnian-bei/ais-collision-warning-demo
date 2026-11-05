import io
import json
import zipfile
from fastapi.testclient import TestClient
from backend import app as module
from backend.engine import Engine


def test_controls_websocket_exports_import_and_validation(tmp_path,monkeypatch):
    monkeypatch.setattr(module,"engine",Engine(tmp_path/'api.db',0,auto_stop_default=False))
    with TestClient(module.app) as client:
        assert client.get('/api/health').json()['ok']
        initial=client.get('/api/state').json()
        assert len(initial['vessels'])==6
        assert not initial['running']
        with client.websocket_connect('/ws') as websocket:
            state=websocket.receive_json()
            assert state['time_iso'].endswith('Z')
            assert state['stats']['received']>0
        assert client.post('/api/scenario',json={'id':'missing'}).status_code==400
        assert client.post('/api/control',json={'action':'seek','elapsed':-1}).status_code==422
        assert client.put('/api/settings',json={'distance_high_m':1000,'distance_low_m':300}).status_code==422
        scene=client.post('/api/scenario',json={'id':'head_on'}).json()
        warning=client.post('/api/control',json={'action':'next_warning'}).json()
        assert warning['elapsed']>0
        assert len(warning['events'])>=1
        assert not warning['running']
        assert any(v.get('risk',{}).get('predicted_warning') for v in warning['vessels'] if not v['is_own'])
        complete=client.post('/api/control',json={'action':'complete'}).json()
        assert complete['elapsed']==complete['duration']
        report=client.get('/api/report').json()
        assert report['complete']
        assert report['targets'][0]['warning_lead_time_to_observed_closest_s']>0
        archive=client.get('/api/export/zip')
        assert archive.status_code==200
        assert 'attachment' in archive.headers['content-disposition']
        with zipfile.ZipFile(io.BytesIO(archive.content)) as z:
            assert json.loads(z.read('report.json'))['complete']
            r=client.post('/api/import',files={'file':('positions.csv',z.read('positions.csv'),'text/csv')},data={'own_mmsi':'413000001'})
        assert r.status_code==200,r.text
        assert r.json()['source']=='import'
        assert r.json()['import_report']['valid_positions']==1202
        assert client.post('/api/control',json={'action':'complete'}).status_code==200
        imported=client.get('/api/report').json()
        assert imported['targets'][0]['first_warning']['time']==report['targets'][0]['first_warning']['time']
        assert abs(imported['targets'][0]['peak_risk']['collision_risk']-report['targets'][0]['peak_risk']['collision_risk'])<1e-6
        invalid=client.post('/api/import',files={'file':('wrong.csv',b'wrong,file\n1,2','text/csv')})
        assert invalid.status_code==400
        assert client.post('/api/own/000000000').status_code==400
        assert client.get('/api/runs').status_code==200
        assert client.get('/api/runs/'+scene['run_id']+'/report').status_code==200
