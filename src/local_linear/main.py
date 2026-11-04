import argparse
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .api import router
from .auth import COOKIE, token_ok
from .db import SessionLocal, init_db
from .hosts import host_allowed
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
app.add_middleware(GZipMiddleware, minimum_size=1024)

SECURITY_HEADERS = {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"}


@app.middleware("http")
async def reject_foreign_hosts(request: Request, call_next):
    if not host_allowed(request.headers.get("host", "")):
        response = PlainTextResponse("Invalid host header", status_code=421)
    elif request.url.path != "/login" and not token_ok(
        request.headers.get("authorization", ""), request.cookies.get(COOKIE, "")
    ):
        response = PlainTextResponse("Unauthorized: open /login?token=<LOCAL_LINEAR_TOKEN>", status_code=401)
    else:
        response = await call_next(request)
    response.headers.update(SECURITY_HEADERS)
    return response


@app.get("/login", include_in_schema=False)
def login(token: str = ""):
    """Browser sign-in: store the token in a cookie (SameSite=Strict also blocks cross-site requests)."""
    if not token_ok(f"Bearer {token}", ""):
        return PlainTextResponse("Unauthorized", status_code=401)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict")
    return response


class RevalidatingStaticFiles(StaticFiles):
    """Static files that browsers re-check on every load (cheap, ETag based), so an upgraded
    app.js/style.css is picked up immediately instead of a stale cached copy."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", RevalidatingStaticFiles(directory=STATIC_DIR), name="static")


# Second line of defence for rendered Markdown (which is already escaped server-side): no inline or
# third-party scripts, no framing. Remote images are allowed so Markdown image links work.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' https: data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)  # no icon, but no 404 in the browser console either


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
