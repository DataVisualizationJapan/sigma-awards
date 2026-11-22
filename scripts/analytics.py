"""DVJ analytics snippet renderer (specification 1.0.0, standard library only)."""
import html
import json
import re
from pathlib import Path


def render(config_path, *, script_src=None, runtime_path=None):
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if not isinstance(config.get("enabled"), bool):
        raise ValueError("analytics.enabled must be a boolean")
    if not re.fullmatch(r"G-[A-Z0-9]+", config.get("measurement_id", "")):
        raise ValueError("invalid analytics measurement_id")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", config.get("site_id", "")):
        raise ValueError("invalid analytics site_id")
    hosts = config.get("production_hosts")
    if not isinstance(hosts, list) or not hosts or any(
        not isinstance(h, str) or not re.fullmatch(r"[a-z0-9.-]+", h) for h in hosts
    ):
        raise ValueError("production_hosts must be explicit hostnames")
    if not config["enabled"]:
        return ""
    payload = json.dumps(config, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    snippet = '<script id="dvj-analytics-config" type="application/json">' + payload + '</script>\n'
    if runtime_path is not None and script_src is None:
        runtime = Path(runtime_path).read_text(encoding="utf-8").replace("</script", "<\\/script")
        return snippet + '<script>\n' + runtime + '\n</script>'
    if script_src is not None and runtime_path is None:
        return snippet + '<script src="' + html.escape(script_src, quote=True) + '" defer></script>'
    raise ValueError("provide exactly one of script_src or runtime_path")
