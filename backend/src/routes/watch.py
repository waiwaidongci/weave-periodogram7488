from fastapi import APIRouter,Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from src.config.database import get_db
from src.controllers.dependencies import current_user,writers
from src.models import WatchSet
from src.schemas.watch import WatchSetInput
from src.services.watch import create_set,set_state,recompute
router=APIRouter()
@router.get('/watch-sets')
def sets(db:Session=Depends(get_db),user=Depends(current_user)):return [set_state(db,s.id) for s in db.scalars(select(WatchSet).order_by(WatchSet.id))]
@router.post('/watch-sets')
def create(data:WatchSetInput,db:Session=Depends(get_db),user=Depends(writers)):return create_set(db,data,user.email)
@router.post('/watch-sets/{id}/recompute')
def redo(id:int,db:Session=Depends(get_db),user=Depends(writers)):return recompute(db,id,user.email)
