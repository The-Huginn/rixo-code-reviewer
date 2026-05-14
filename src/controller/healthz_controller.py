from fastapi import APIRouter

router = APIRouter()


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/healthz/readiness")
def readiness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/healthz/liveness")
def liveness() -> dict[str, str]:
    return {"status": "ok"}
