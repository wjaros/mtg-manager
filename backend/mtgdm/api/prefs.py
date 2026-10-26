from fastapi import APIRouter
from pydantic import BaseModel, Field

from mtgdm import prefs
from mtgdm.api.deps import Db

router = APIRouter(prefix="/prefs", tags=["prefs"])


class Prefs(BaseModel):
    values: dict[str, str]
    scale: float
    # The window app: the scale zooms its web view. In a browser the browser's own zoom does that.
    native_zoom: bool


class PrefUpdate(BaseModel):
    key: str = Field(min_length=1, max_length=prefs.MAX_KEY)
    value: str | None = Field(default=None, max_length=prefs.MAX_VALUE)  # None removes it


class ScaleUpdate(BaseModel):
    scale: float = Field(ge=prefs.MIN_SCALE, le=prefs.MAX_SCALE)


def _prefs(db: Db) -> Prefs:
    return Prefs(values=prefs.get_all(db), scale=prefs.get_scale(db), native_zoom=prefs.native_zoom())


@router.get("")
def get_prefs(db: Db) -> Prefs:
    """The UI's preferences, loaded once before it renders."""
    return _prefs(db)


@router.put("", status_code=204)
def put_pref(db: Db, body: PrefUpdate) -> None:
    prefs.set_pref(db, body.key, body.value)


@router.put("/scale")
def put_scale(db: Db, body: ScaleUpdate) -> Prefs:
    """Size of the whole interface; the window app zooms its web view right away."""
    prefs.set_scale(db, body.scale)
    return _prefs(db)
