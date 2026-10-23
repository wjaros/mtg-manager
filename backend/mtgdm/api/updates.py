from fastapi import APIRouter, Request
from pydantic import BaseModel

from mtgdm import updates
from mtgdm.api.deps import Db
from mtgdm.updates import UpdateInfo

router = APIRouter(prefix="/updates", tags=["updates"])


class UpdateSettings(BaseModel):
    enabled: bool


class SkipVersion(BaseModel):
    version: str


@router.get("")
def check(db: Db, request: Request, force: bool = False) -> UpdateInfo:
    """A newer release on GitHub? Checked at most every few hours unless forced (Settings: check now)."""
    return updates.check(db, request.app.state.github, force=force)


@router.put("/settings")
def settings(db: Db, request: Request, body: UpdateSettings) -> UpdateInfo:
    updates.set_enabled(db, body.enabled)
    return updates.check(db, request.app.state.github)


@router.post("/skip")
def skip(db: Db, request: Request, body: SkipVersion) -> UpdateInfo:
    """No reminder about this version (a newer one is shown again)."""
    updates.skip(db, body.version)
    return updates.check(db, request.app.state.github)
