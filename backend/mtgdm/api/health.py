from fastapi import APIRouter
from pydantic import BaseModel

from mtgdm import __version__
from mtgdm.api.deps import Db
from mtgdm.db import current_version

router = APIRouter(tags=["system"])


class Health(BaseModel):
    status: str
    version: str
    schema_version: int


@router.get("/health")
def health(db: Db) -> Health:
    return Health(status="ok", version=__version__, schema_version=current_version(db))
