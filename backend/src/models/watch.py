from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import ForeignKey,String,Text,JSON,DateTime,UniqueConstraint
from datetime import datetime,timezone
from src.config.database import Base
class WatchSet(Base):
 __tablename__='watch_sets'
 id:Mapped[int]=mapped_column(primary_key=True)
 study_id:Mapped[int]=mapped_column(ForeignKey('traverse_studies.id'),unique=True)
 name:Mapped[str]=mapped_column(String(180),unique=True)
 published_revision_id:Mapped[int|None]=mapped_column(nullable=True)
 created_by:Mapped[str]=mapped_column(String(120))
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
class WatchSetPlan(Base):
 __tablename__='watch_set_plans'
 __table_args__=(UniqueConstraint('set_id','plan_id'),)
 id:Mapped[int]=mapped_column(primary_key=True)
 set_id:Mapped[int]=mapped_column(ForeignKey('watch_sets.id'))
 plan_id:Mapped[int]=mapped_column(ForeignKey('frequency_plans.id'))
class WatchRevision(Base):
 __tablename__='watch_revisions'
 __table_args__=(UniqueConstraint('set_id','revision'),)
 id:Mapped[int]=mapped_column(primary_key=True)
 set_id:Mapped[int]=mapped_column(ForeignKey('watch_sets.id'))
 revision:Mapped[int]=mapped_column()
 source_snapshot:Mapped[dict]=mapped_column(JSON)
 source_fingerprint:Mapped[str]=mapped_column(String(64))
 status:Mapped[str]=mapped_column(String(24),default='running')
 trigger:Mapped[str]=mapped_column(String(24))
 error:Mapped[str|None]=mapped_column(Text,nullable=True)
 created_by:Mapped[str]=mapped_column(String(120))
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))
 published_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
class WatchTask(Base):
 __tablename__='watch_tasks'
 __table_args__=(UniqueConstraint('revision_id','plan_id'),)
 id:Mapped[int]=mapped_column(primary_key=True)
 revision_id:Mapped[int]=mapped_column(ForeignKey('watch_revisions.id'))
 plan_id:Mapped[int]=mapped_column(ForeignKey('frequency_plans.id'))
 plan_snapshot:Mapped[dict]=mapped_column(JSON)
 run_id:Mapped[int|None]=mapped_column(ForeignKey('spectrum_runs.id'),nullable=True)
 status:Mapped[str]=mapped_column(String(24),default='pending')
 error:Mapped[str|None]=mapped_column(Text,nullable=True)
