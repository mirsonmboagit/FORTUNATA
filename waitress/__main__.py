import argparse
import importlib
import sys

from .runner import serve


def _parse_listen(value):
    listen = str(value or "").strip()
    if not listen:
        raise SystemExit("missing listen address")
    if ":" not in listen:
        return listen, 8080
    host, port_text = listen.rsplit(":", 1)
    host = host.strip() or "0.0.0.0"
    try:
        port = int(port_text.strip())
    except ValueError as exc:
        raise SystemExit(f"invalid port in --listen: {value}") from exc
    return host, port


def _load_wsgi_app(target):
    target = str(target or "").strip()
    if ":" not in target:
        raise SystemExit("application target must look like module:callable")
    module_name, app_name = target.split(":", 1)
    module = importlib.import_module(module_name)
    app = getattr(module, app_name, None)
    if app is None:
        raise SystemExit(f"application '{app_name}' not found in module '{module_name}'")
    return app


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m waitress")
    parser.add_argument("--listen", default="0.0.0.0:8080")
    parser.add_argument("app_target")
    args = parser.parse_args(argv)
    host, port = _parse_listen(args.listen)
    app = _load_wsgi_app(args.app_target)
    serve(app, host=host, port=port)


if __name__ == "__main__":
    main(sys.argv[1:])
