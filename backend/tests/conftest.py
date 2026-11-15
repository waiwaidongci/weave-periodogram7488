import os,tempfile
_tmp=tempfile.mkdtemp(prefix='watch-test-')
os.environ['DATABASE_URL']='sqlite:///'+_tmp+'/watch.db'
os.environ['JWT_SECRET']='watch-test-secret'
os.environ['ARTIFACT_DIR']=_tmp
os.environ['SEED_DEMO']='false'
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from sqlalchemy import delete
from src.config.database import Base,engine,SessionLocal
from src import models
Base.metadata.create_all(engine)
TABLES=[models.WatchTask,models.WatchRevision,models.WatchSetPlan,models.WatchSet,models.WeaveNote,models.SpectrumRun,models.FrequencyPlan,models.TraversePoint,models.TraverseStudy,models.AuditLog,models.User]
@pytest.fixture(autouse=True)
def clean_db():
 with SessionLocal() as db:
  for table in TABLES:db.execute(delete(table))
  db.commit()
 yield
@pytest.fixture
def db():
 with SessionLocal() as session:yield session
@pytest.fixture
def dispatched(monkeypatch):
 import src.worker as worker
 box=[]
 monkeypatch.setattr(worker.analyze_run,'delay',lambda run_id:box.append(run_id))
 return box
def drain(box,count=None):
 from src.worker import analyze_run
 n=0
 while box and(count is None or n<count):
  analyze_run(box.pop(0));n+=1
 return n
def make_study(db,name='T-测线',thicknesses=(.50,.58,.49,.55,.50,.53)):
 study=models.TraverseStudy(name=name,filename='t.csv',description='');db.add(study);db.flush()
 for i,(position,thickness) in enumerate(zip([0,1.25,2.75,4.25,6,7.5],thicknesses)):db.add(models.TraversePoint(study_id=study.id,reference=f'P{i+1}',position=position,thickness=thickness))
 db.commit();return study
def make_plan(db,study,name,seed=11):
 plan=models.FrequencyPlan(study_id=study.id,name=name,protocol='预先声明的网格',min_frequency=.05,max_frequency=.2,grid_size=4,frequencies=[.05,.1,.15,.2],permutations=199,seed=seed,created_by='a@t');db.add(plan);db.commit();return plan
def make_set(db,plans=2):
 from src.schemas.watch import WatchSetInput
 from src.services.watch import create_set
 study=make_study(db);ps=[make_plan(db,study,f'计划{i+1}',seed=11+i) for i in range(plans)]
 return create_set(db,WatchSetInput(study_id=study.id,name='研究集一',plan_ids=[p.id for p in ps]),'a@t'),study,ps
