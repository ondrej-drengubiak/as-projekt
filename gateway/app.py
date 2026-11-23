"""API gateway / Strangler Fig facade. Smerovanie podľa tabuľky ROUTES (JSON v env)."""
import os, json, httpx
from fastapi import FastAPI, Request, Response

app = FastAPI(title="strangler-gateway")
ROUTES = json.loads(os.environ.get("ROUTES", "{}"))
DEFAULT = os.environ["MONOLITH_URL"]
client = httpx.AsyncClient(timeout=10.0, limits=httpx.Limits(max_connections=300, max_keepalive_connections=100))

def upstream(path):
    for prefix, url in ROUTES.items():
        if path == prefix or path.startswith(prefix + "/"):
            return url
    return DEFAULT

@app.get("/__routes")
def routes():
    return {"routes": ROUTES, "default": DEFAULT}

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def proxy(path: str, request: Request):
    p = "/" + path
    body = await request.body()
    try:
        r = await client.request(request.method, upstream(p) + p, params=request.query_params, content=body,
                                 headers={"content-type": request.headers.get("content-type", "application/json")})
    except httpx.HTTPError:
        return Response(content=b'{"detail":"bad gateway"}', status_code=502, media_type="application/json")
    return Response(content=r.content, status_code=r.status_code, media_type=r.headers.get("content-type"))
