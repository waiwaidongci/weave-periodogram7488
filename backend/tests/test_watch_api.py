import pytest
from fastapi.testclient import TestClient
from src.main import app
from src.models import User
from src.utils.security import hash_password,issue_token
from conftest import drain,make_study,make_plan

@pytest.fixture
def client(monkeypatch,dispatched):
 class FakeRedis:
  def incr(self,key):return 1
  def expire(self,*args):pass
 monkeypatch.setattr('src.middlewares.rate_limit.Redis.from_url',lambda *a,**k:FakeRedis())
 return TestClient(app)
@pytest.fixture
def tokens(db):
 analyst=User(email='a@t',name='分析员',role='analyst',password_hash=hash_password('x'))
 viewer=User(email='v@t',name='观察员',role='viewer',password_hash=hash_password('x'))
 db.add_all([analyst,viewer]);db.commit()
 return {'Authorization':'Bearer '+issue_token(analyst)},{'Authorization':'Bearer '+issue_token(viewer)}

def test_watch_set_api_lifecycle(client,db,tokens,dispatched):
 analyst,viewer=tokens
 study=make_study(db);p1=make_plan(db,study,'计划一');p2=make_plan(db,study,'计划二',seed=12)
 assert client.post('/watch-sets',json={'study_id':study.id,'name':'研究集一','plan_ids':[p1.id,p2.id]}).status_code==401
 assert client.post('/watch-sets',json={'study_id':study.id,'name':'研究集一','plan_ids':[p1.id,p2.id]},headers=viewer).status_code==403
 bad=client.post('/watch-sets',json={'study_id':study.id,'name':'研究集一','plan_ids':[p1.id,9999]},headers=analyst)
 assert bad.status_code==422
 created=client.post('/watch-sets',json={'study_id':study.id,'name':'研究集一','plan_ids':[p1.id,p2.id]},headers=analyst)
 assert created.status_code==200 and created.json()['revisions'][0]['status']=='running'
 assert client.post('/watch-sets',json={'study_id':study.id,'name':'研究集二','plan_ids':[p1.id]},headers=analyst).status_code==409
 listed=client.get('/watch-sets',headers=viewer)
 assert listed.status_code==200 and len(listed.json())==1
 drain(dispatched)
 listed=client.get('/watch-sets',headers=viewer).json()
 assert listed[0]['revisions'][0]['status']=='published' and listed[0]['published_revision_id']==listed[0]['revisions'][0]['id']
 again=client.post(f"/watch-sets/{listed[0]['id']}/recompute",headers=analyst)
 assert again.status_code==200 and len(again.json()['revisions'])==2
 assert client.post('/watch-sets/9999/recompute',headers=analyst).status_code==404
