"""Home automation: the pumpkin tells your smart home what it is doing (it sends webhooks, e.g. to Home
Assistant, so a light can come on when the butler appears), and your smart home can ring the pumpkin
(POST /api/doorbell when the real doorbell rings)."""

import json
import threading
import urllib.request


class Home:
    def __init__(self, cfg, log):
        self.cfg, self.log = cfg, log
        self.hooks = {k: v for k, v in (cfg.get("webhooks") or {}).items() if v}
        if cfg["enabled"]:
            log(f"home automation: sends {', '.join(self.hooks) or 'nothing'}; doorbell at /api/doorbell")

    def allowed(self, data):
        """The doorbell request carries the shared key from config.toml (if one is set)."""
        key = self.cfg.get("key", "")
        return self.cfg["enabled"] and (not key or str(data.get("key", "")) == key)

    def send(self, event, **data):
        """POST {"event": ..., ...} to the webhook configured for this event, in the background."""
        url = self.hooks.get(event)
        if not self.cfg["enabled"] or not url:
            return

        def post():
            try:
                req = urllib.request.Request(url, data=json.dumps({"event": event, **data}).encode(),
                                             headers={"Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(req, timeout=5).close()
                self.log(f"🏠 sent {event}")
            except Exception as exc:
                self.log(f"🏠 {event} webhook failed: {exc}")

        threading.Thread(target=post, daemon=True).start()
