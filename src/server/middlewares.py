import json

import falcon


class JSONMiddleware:

    async def process_request(self, req: falcon.asgi.Request, resp: falcon.asgi.Response):
        if req.content_length in (None, 0):
            req.context["json"] = None
            return

        content_type = (req.content_type or "").lower()
        if "application/json" in content_type:
            try:
                body = await req.stream.read()
                if body:
                    req.context["json"] = json.loads(body.decode("utf-8"))
                else:
                    req.context["json"] = None
            except json.JSONDecodeError:
                pass
        else:
            req.context["json"] = None

    async def process_response(
        self,
        req: falcon.asgi.Request,
        resp: falcon.asgi.Response,
        resource,
        req_succeeded: bool,
    ):
        if "result" in resp.context:
            resp.text = json.dumps(
                resp.context["result"],
                ensure_ascii=False,
                indent=None,
                separators=(",", ":"),
            )
            resp.content_type = "application/json; charset=utf-8"

        if not req_succeeded and resp.status >= falcon.HTTP_400:
            try:
                json.loads(resp.text or "")
            except Exception:
                resp.text = json.dumps(
                    {"error": resp.status},
                    ensure_ascii=False,
                )
                resp.content_type = "application/json; charset=utf-8"
