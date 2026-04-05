import socketserver
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server


class _ThreadingWSGIServer(socketserver.ThreadingMixIn, WSGIServer):
    daemon_threads = True


def serve(app, host="0.0.0.0", port=8080, **kwargs):
    server = make_server(host, int(port), app, server_class=_ThreadingWSGIServer, handler_class=WSGIRequestHandler)
    try:
        print(f"[waitress-local] serving on http://{host}:{int(port)}")
        server.serve_forever()
    finally:
        server.server_close()
