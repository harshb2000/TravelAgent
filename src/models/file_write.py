from typing import Literal
from pydantic import BaseModel, Field


class FileWriteOutput(BaseModel):
    status: Literal["ok"] = Field(description="Always 'ok' on success")
    path: str = Field(description="Actual filename written — may differ from requested if a collision was resolved by incrementing the version suffix")
