import json,hashlib,logging
from datetime import datetime,timezone
from sqlalchemy import select,func
from fastapi import HTTPException
from src.models import TraverseStudy,FrequencyPlan,SpectrumRun,WatchSet,WatchSetPlan,WatchRevision,WatchTask
from src.utils.serialize import row
from src.constants.enums import WatchRevisionStatus as RS,WatchTaskStatus as TS
from .validation import validate_points
from .audit import record

def points_fingerprint(points):
 payload=[{'reference':p['reference'],'position':p['position'],'thickness':p['thickness']} for p in sorted(points,key=lambda p:p['position'])]
 return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def set_state(db,set_id):
 set_=db.get(WatchSet,set_id)
 if not set_:raise HTTPException(404,'跟踪研究集不存在')
 plans=[row(p) for p in (db.get(FrequencyPlan,pid) for pid in db.scalars(select(WatchSetPlan.plan_id).where(WatchSetPlan.set_id==set_id).order_by(WatchSetPlan.id)).all()) if p]
 revisions=[]
 for r in db.scalars(select(WatchRevision).where(WatchRevision.set_id==set_id).order_by(WatchRevision.revision)).all():
  tasks=[{'id':t.id,'revision_id':t.revision_id,'plan_id':t.plan_id,'plan_name':t.plan_snapshot.get('name',''),'run_id':t.run_id,'status':t.status,'error':t.error} for t in db.scalars(select(WatchTask).where(WatchTask.revision_id==r.id).order_by(WatchTask.id)).all()]
  revisions.append({'id':r.id,'set_id':r.set_id,'revision':r.revision,'status':r.status,'trigger':r.trigger,'error':r.error,'points':len(r.source_snapshot['points']),'source_fingerprint':r.source_fingerprint,'created_by':r.created_by,'created_at':r.created_at.isoformat() if r.created_at else None,'published_at':r.published_at.isoformat() if r.published_at else None,'tasks':tasks})
 return {'id':set_.id,'study_id':set_.study_id,'name':set_.name,'published_revision_id':set_.published_revision_id,'created_by':set_.created_by,'created_at':set_.created_at.isoformat() if set_.created_at else None,'plans':[{'id':p['id'],'name':p['name'],'grid_size':p['grid_size'],'permutations':p['permutations'],'seed':p['seed']} for p in plans],'revisions':revisions}

def create_set(db,data,actor):
 study=db.get(TraverseStudy,data.study_id)
 if not study:raise HTTPException(404,'测线研究不存在')
 if db.scalar(select(WatchSet).where(WatchSet.name==data.name)):raise HTTPException(409,'研究集名已存在')
 if db.scalar(select(WatchSet).where(WatchSet.study_id==study.id)):raise HTTPException(409,'该测线已登记跟踪研究集')
 ids=list(dict.fromkeys(data.plan_ids));plans=[db.get(FrequencyPlan,i) for i in ids]
 if any(p is None for p in plans):raise HTTPException(422,'频率计划不存在')
 if any(p.study_id!=study.id for p in plans):raise HTTPException(422,'频率计划不属于该测线')
 set_=WatchSet(study_id=study.id,name=data.name,created_by=actor);db.add(set_);db.flush()
 for plan in plans:db.add(WatchSetPlan(set_id=set_.id,plan_id=plan.id))
 db.commit();record(db,actor,'watch.registered',{'set_id':set_.id,'plans':len(plans)})
 start_revision(db,set_,'register',actor)
 return set_state(db,set_.id)

def start_revision(db,set_,trigger,actor):
 from .source import source_data
 study,points=source_data(db,set_.study_id)
 try:validate_points(points)
 except ValueError as error:raise HTTPException(422,str(error))
 number=(db.scalar(select(func.max(WatchRevision.revision)).where(WatchRevision.set_id==set_.id)) or 0)+1
 revision=WatchRevision(set_id=set_.id,revision=number,source_snapshot={'study':study,'points':points},source_fingerprint=points_fingerprint(points),trigger=trigger,created_by=actor)
 db.add(revision);db.flush()
 for plan_id in db.scalars(select(WatchSetPlan.plan_id).where(WatchSetPlan.set_id==set_.id).order_by(WatchSetPlan.id)).all():
  db.add(WatchTask(revision_id=revision.id,plan_id=plan_id,plan_snapshot=row(db.get(FrequencyPlan,plan_id))))
 db.commit();record(db,actor,'watch.revision_started',{'set_id':set_.id,'revision':number,'trigger':trigger})
 for task in db.scalars(select(WatchTask).where(WatchTask.revision_id==revision.id)).all():dispatch_task(db,task)
 return revision

def dispatch_task(db,task):
 revision=db.get(WatchRevision,task.revision_id);set_=db.get(WatchSet,revision.set_id)
 run=db.get(SpectrumRun,task.run_id) if task.run_id else None
 if run is None:
  name=f"集{set_.id}·第{revision.revision}版·计划{task.plan_id}·{task.plan_snapshot.get('name','')}"[:180]
  run=SpectrumRun(study_id=set_.study_id,plan_id=task.plan_id,name=name,source_snapshot=revision.source_snapshot,plan_snapshot=task.plan_snapshot,created_by=revision.created_by)
  db.add(run);db.flush();task.run_id=run.id;db.commit()
 try:
  from src.worker import analyze_run
  analyze_run.delay(run.id)
 except Exception:
  task.status=TS.PENDING;task.error='队列不可用，待恢复补齐';db.commit();return
 task.status=TS.DISPATCHED;task.error=None;db.commit()

def on_source_revised(db,study_id,actor):
 set_=db.scalar(select(WatchSet).where(WatchSet.study_id==study_id))
 if set_:start_revision(db,set_,'point-revise',actor)

def on_run_finished(db,run_id):
 run=db.get(SpectrumRun,run_id)
 if not run:return
 task=db.scalar(select(WatchTask).where(WatchTask.run_id==run.id))
 if not task:return
 if run.status=='completed':task.status=TS.COMPLETED;task.error=None
 elif run.status=='failed':task.status=TS.FAILED;task.error=run.error
 else:return
 db.commit();maybe_finalize(db,task.revision_id)

def maybe_finalize(db,revision_id):
 revision=db.scalar(select(WatchRevision).where(WatchRevision.id==revision_id).with_for_update())
 if not revision or revision.status!=RS.RUNNING:return
 tasks=db.scalars(select(WatchTask).where(WatchTask.revision_id==revision_id)).all()
 if any(t.status in (TS.PENDING,TS.DISPATCHED) for t in tasks):return
 set_=db.get(WatchSet,revision.set_id)
 failed=[t for t in tasks if t.status==TS.FAILED]
 if failed:
  revision.status=RS.FAILED;revision.error='；'.join(f"{t.plan_snapshot.get('name','计划'+str(t.plan_id))}：{t.error}" for t in failed)[:1000]
  db.commit();record(db,'system','watch.revision_failed',{'set_id':set_.id,'revision':revision.revision,'error':revision.error});return
 latest_id=db.scalar(select(func.max(WatchRevision.id)).where(WatchRevision.set_id==set_.id))
 if revision.id!=latest_id:
  revision.status=RS.SUPERSEDED;db.commit();record(db,'system','watch.revision_superseded',{'set_id':set_.id,'revision':revision.revision});return
 revision.status=RS.PUBLISHED;revision.published_at=datetime.now(timezone.utc);set_.published_revision_id=revision.id
 db.commit();record(db,'system','watch.published',{'set_id':set_.id,'revision':revision.revision,'points':len(revision.source_snapshot['points'])})

def recompute(db,set_id,actor):
 set_=db.get(WatchSet,set_id)
 if not set_:raise HTTPException(404,'跟踪研究集不存在')
 from .source import source_data
 _,points=source_data(db,set_.study_id);fingerprint=points_fingerprint(points)
 latest=db.scalar(select(WatchRevision).where(WatchRevision.set_id==set_id).order_by(WatchRevision.revision.desc()).limit(1))
 if not latest or latest.source_fingerprint!=fingerprint or latest.status!=RS.RUNNING:start_revision(db,set_,'manual',actor)
 return set_state(db,set_id)

def recover(db):
 from .source import source_data
 running=db.scalars(select(WatchRevision).where(WatchRevision.status==RS.RUNNING).order_by(WatchRevision.id)).all()
 for set_ in db.scalars(select(WatchSet)).all():
  try:
   _,points=source_data(db,set_.study_id);fingerprint=points_fingerprint(points)
   latest=db.scalar(select(WatchRevision).where(WatchRevision.set_id==set_.id).order_by(WatchRevision.revision.desc()).limit(1))
   if latest is None or latest.source_fingerprint!=fingerprint:start_revision(db,set_,'recovery','system')
  except Exception:logging.exception('watch recovery skip set %s',set_.id)
 for revision in running:
  for task in db.scalars(select(WatchTask).where(WatchTask.revision_id==revision.id)).all():
   run=db.get(SpectrumRun,task.run_id) if task.run_id else None
   if run and run.status=='completed':task.status=TS.COMPLETED;task.error=None;db.commit()
   elif run and run.status=='failed':task.status=TS.FAILED;task.error=run.error;db.commit()
   elif run and run.status=='running':pass
   else:dispatch_task(db,task)
  maybe_finalize(db,revision.id)
