import json

from codegen import make_code

BASE_URL = "http://localhost:8000"


def shorten_handler(store, environ, params):
    size = int(environ.get("CONTENT_LENGTH") or 0)
    body = json.loads(environ["wsgi.input"].read(size) or b"{}")
    url = body.get("url")
    if not url:
        return 400, {}, {"error": "url required"}
    code = make_code(url)
    store.save(code, url)
    return 201, {}, {"code": code, "short_url": f"{BASE_URL}/{code}"}


def redirect_handler(store, environ, params):
    url = store.get(params["code"])
    if url is None:
        return 404, {}, {"error": "not found"}
    return 302, {"Location": url}, None


ROUTES = [
    ("POST", "/shorten", shorten_handler),
    ("GET", "/<code>", redirect_handler),
]


def _match(pattern, path):
    p_parts, u_parts = pattern.strip("/").split("/"), path.strip("/").split("/")
    if len(p_parts) != len(u_parts):
        return None
    params = {}
    for p, u in zip(p_parts, u_parts):
        if p.startswith("<"):
            params[p[1:-1]] = u
        elif p != u:
            return None
    return params


def make_app(store):
    def app(environ, start_response):
        method, path = environ["REQUEST_METHOD"], environ.get("PATH_INFO", "/")
        for r_method, pattern, handler in ROUTES:
            params = _match(pattern, path)
            if params is not None and r_method == method:
                status, headers, body = handler(store, environ, params)
                payload = b"" if body is None else json.dumps(body).encode()
                start_response(f"{status} X", list(headers.items()) + [("Content-Length", str(len(payload)))])
                return [payload]
        start_response("404 Not Found", [("Content-Length", "0")])
        return [b""]
    return app
