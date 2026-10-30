import argparse
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .db import SessionLocal, init_db
from .seed import seed

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if os.getenv("LOCAL_LINEAR_SEED", "1") != "0":
        with SessionLocal() as db:
            seed(db)
    yield


app = FastAPI(title="Local Linear", lifespan=lifespan)
app.include_router(router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Second line of defence for rendered Markdown (which is already escaped server-side): no inline or
# third-party scripts, no framing. Remote images are allowed so Markdown image links work.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' https: data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Content-Security-Policy": CSP})


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(prog="local-linear", description="Run the Local Linear server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    uvicorn.run("local_linear.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
