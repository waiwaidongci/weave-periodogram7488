import pytest
from sqlalchemy import select,func
from fastapi import HTTPException
from src.models import TraversePoint,SpectrumRun,WatchRevision,WatchTask
from src.schemas.watch import WatchSetInput
from src.schemas.point import PointPatch
from src.services.watch import create_set,set_state,on_run_finished,recompute,recover
from src.services.source import edit_point
from conftest import drain,make_study,make_plan,make_set

def test_register_dispatches_all_plans_and_publishes_group(db,dispatched):
 state,study,plans=make_set(db)
 assert state['revisions'][0]['status']=='running' and len(state['revisions'][0]['tasks'])==2
 assert len(dispatched)==2
 drain(dispatched)
 state=set_state(db,state['id']);revision=state['revisions'][0]
 assert revision['status']=='published' and state['published_revision_id']==revision['id']
 assert all(t['status']=='completed' for t in revision['tasks'])
 runs=db.scalars(select(SpectrumRun)).all()
 assert len(runs)==2 and all(r.status=='completed' for r in runs)
 assert {r.source_snapshot['points'][0]['thickness'] for r in runs}=={.5}

def test_point_revision_triggers_new_revision_with_shared_snapshot(db,dispatched):
 state,study,_=make_set(db);drain(dispatched)
 point=db.scalars(select(TraversePoint).where(TraversePoint.study_id==study.id)).first()
 edit_point(db,point.id,PointPatch(position=point.position,thickness=.77),'a@t')
 assert len(dispatched)==2
 drain(dispatched)
 state=set_state(db,state['id'])
 assert [r['revision'] for r in state['revisions']]==[1,2]
 assert state['revisions'][1]['status']=='published' and state['published_revision_id']==state['revisions'][1]['id']
 runs=db.scalars(select(SpectrumRun).where(SpectrumRun.name.like('集%'))).all()
 assert all(p['thickness']==.77 for r in runs[-2:] for p in r.source_snapshot['points'] if p['id']==point.id)

def test_partial_failure_keeps_previous_group_and_shows_reason(db,dispatched):
 state,study,_=make_set(db);drain(dispatched)
 point=db.scalars(select(TraversePoint).where(TraversePoint.study_id==study.id)).first()
 edit_point(db,point.id,PointPatch(position=point.position,thickness=.91),'a@t')
 drain(dispatched,1)
 failed_run=db.get(SpectrumRun,dispatched[0]);failed_run.status='failed';failed_run.error='模拟计算失败';db.commit()
 on_run_finished(db,failed_run.id)
 state=set_state(db,state['id'])
 assert state['revisions'][1]['status']=='failed' and '模拟计算失败' in (state['revisions'][1]['error'] or '')
 assert state['published_revision_id']==state['revisions'][0]['id']

def test_constant_thickness_revision_fails_without_replacing_group(db,dispatched):
 state,study,_=make_set(db);drain(dispatched)
 for p in db.scalars(select(TraversePoint).where(TraversePoint.study_id==study.id)).all():p.thickness=.5
 db.commit();recover(db)
 assert len(dispatched)==2
 drain(dispatched)
 state=set_state(db,state['id'])
 assert state['revisions'][1]['status']=='failed' and state['published_revision_id']==state['revisions'][0]['id']

def test_concurrent_revisions_only_latest_publishes(db,dispatched):
 state,study,_=make_set(db);drain(dispatched)
 points=db.scalars(select(TraversePoint).where(TraversePoint.study_id==study.id)).all()
 edit_point(db,points[0].id,PointPatch(position=points[0].position,thickness=.61),'a@t')
 edit_point(db,points[1].id,PointPatch(position=points[1].position,thickness=.62),'a@t')
 assert len(dispatched)==4
 rev2_runs,rev3_runs=dispatched[:2],dispatched[2:]
 drain(rev3_runs)
 state=set_state(db,state['id'])
 assert state['revisions'][2]['status']=='published' and state['published_revision_id']==state['revisions'][2]['id']
 drain(rev2_runs)
 state=set_state(db,state['id'])
 assert state['revisions'][1]['status']=='superseded'
 assert state['published_revision_id']==state['revisions'][2]['id']

def test_recovery_backfills_undispatched_without_second_group(db,dispatched,monkeypatch):
 import src.worker as worker
 study=make_study(db);p1=make_plan(db,study,'计划一');p2=make_plan(db,study,'计划二',seed=12)
 monkeypatch.setattr(worker.analyze_run,'delay',lambda run_id:(_ for _ in ()).throw(RuntimeError('redis down')))
 state=create_set(db,WatchSetInput(study_id=study.id,name='研究集一',plan_ids=[p1.id,p2.id]),'a@t')
 assert all(t['status']=='pending' for t in state['revisions'][0]['tasks'])
 monkeypatch.setattr(worker.analyze_run,'delay',lambda run_id:dispatched.append(run_id))
 recover(db);recover(db)
 assert db.scalar(select(func.count()).select_from(SpectrumRun))==2
 drain(dispatched)
 state=set_state(db,state['id'])
 assert state['revisions'][0]['status']=='published' and db.scalar(select(func.count()).select_from(SpectrumRun))==2

def test_recovery_syncs_finished_runs_and_finalizes(db,dispatched):
 state,study,_=make_set(db)
 drain(dispatched)
 db.execute(WatchTask.__table__.update().values(status='dispatched'))
 db.execute(WatchRevision.__table__.update().values(status='running'));db.commit();db.expire_all()
 recover(db)
 state=set_state(db,state['id'])
 assert state['revisions'][0]['status']=='published' and state['published_revision_id']==state['revisions'][0]['id']

def test_recovery_creates_revision_when_source_changed_without_one(db,dispatched):
 state,study,_=make_set(db);drain(dispatched)
 point=db.scalars(select(TraversePoint).where(TraversePoint.study_id==study.id)).first()
 point.thickness=.99;db.commit()
 recover(db)
 state=set_state(db,state['id'])
 assert len(state['revisions'])==2 and state['revisions'][1]['trigger']=='recovery'
 drain(dispatched)
 state=set_state(db,state['id'])
 assert state['revisions'][1]['status']=='published'
 recover(db)
 assert len(set_state(db,state['id'])['revisions'])==2

def test_duplicate_delivery_does_not_compute_twice(db,dispatched):
 from src.worker import analyze_run
 state,study,_=make_set(db)
 first=dispatched.pop(0)
 analyze_run(first);analyze_run(first)
 assert db.get(SpectrumRun,first).status=='completed'
 drain(dispatched)
 state=set_state(db,state['id'])
 assert state['revisions'][0]['status']=='published'
 assert db.scalar(select(func.count()).select_from(SpectrumRun))==2

def test_recompute_is_idempotent_while_same_source_running(db,dispatched):
 state,study,_=make_set(db)
 again=recompute(db,state['id'],'a@t')
 assert len(again['revisions'])==1 and len(dispatched)==2
 drain(dispatched)
 again=recompute(db,state['id'],'a@t')
 assert len(again['revisions'])==2 and len(dispatched)==2
 drain(dispatched)
 assert set_state(db,state['id'])['revisions'][1]['status']=='published'

def test_plan_of_other_study_and_duplicate_set_rejected(db,dispatched):
 study=make_study(db);other=make_study(db,name='T-另一条')
 p1=make_plan(db,study,'计划一');p2=make_plan(db,other,'计划二')
 with pytest.raises(HTTPException) as error:create_set(db,WatchSetInput(study_id=study.id,name='研究集一',plan_ids=[p1.id,p2.id]),'a@t')
 assert error.value.status_code==422
 create_set(db,WatchSetInput(study_id=study.id,name='研究集一',plan_ids=[p1.id]),'a@t')
 with pytest.raises(HTTPException) as error:create_set(db,WatchSetInput(study_id=study.id,name='研究集二',plan_ids=[p1.id]),'a@t')
 assert error.value.status_code==409

def test_single_runs_do_not_touch_watch_state(db,dispatched):
 from src.services.runs import create_run
 from src.schemas.run import RunInput
 state,study,plans=make_set(db);drain(dispatched)
 create_run(db,RunInput(study_id=study.id,plan_id=plans[0].id,name='独立单次研究'),'a@t')
 drain(dispatched)
 state=set_state(db,state['id'])
 assert len(state['revisions'])==1 and state['revisions'][0]['status']=='published'
