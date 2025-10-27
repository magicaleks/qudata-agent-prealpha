from falcon.asgi import App

from src.server.middlewares import JSONMiddleware
from src.server.resources import ManageInstancesResource, PingResource, SSHResource

app = App()

app.add_middleware(JSONMiddleware())

app.add_route("/ping", PingResource())
app.add_route("/instances", ManageInstancesResource())
app.add_route("/ssh", SSHResource())
