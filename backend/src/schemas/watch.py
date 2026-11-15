from typing import Annotated
from pydantic import BaseModel,Field,ConfigDict
class WatchSetInput(BaseModel):
 model_config=ConfigDict(str_strip_whitespace=True)
 study_id:int=Field(gt=0,strict=True)
 name:str=Field(min_length=2,max_length=180)
 plan_ids:list[Annotated[int,Field(gt=0,strict=True)]]=Field(min_length=1,max_length=20)
