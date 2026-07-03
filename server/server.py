#!/usr/bin/env python3
"""Appraiser proxy — holds the Anthropic API key server-side.

POST /appraise  {"url": "https://…", "passcode": "…"}

The prompt is built HERE, from the URL only, so the endpoint can run
appraisals and nothing else — it is not a general-purpose Claude proxy.
Anthropic's response body is passed through verbatim (the frontend parses it).

Env (via systemd EnvironmentFile):
  ANTHROPIC_API_KEY    required
  APPRAISER_PASSCODE   required
  PORT                 default 8090 (bind 127.0.0.1 — nginx fronts it)

Stdlib only. Python 3.10+.
"""
import json
import os
import re
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API_KEY = os.environ["ANTHROPIC_API_KEY"]
PASSCODE = os.environ["APPRAISER_PASSCODE"]
PORT = int(os.environ.get("PORT", "8090"))

PROMPT_TEMPLATE = """You are a founder-mode investment diagnostic. Your job is diagnosis, not encouragement. You are appraising ONE product at this URL: __URL__

First, research it with web search: what it does, who it is for, pricing, real traction or usage signals, customer reviews, and the status-quo alternative people use today. A marketing website states the founder's claims — it is NOT evidence of demand. Treat claims as claims.

Then score the business model on the evidence you actually found, six dimensions, 0–10 each (60 total). Be stingy: a 7+ needs concrete behavioral evidence (people paying, expanding usage, building a workflow around it, scrambling if it vanished), not a good story or a slick site. Where you only have website claims for a dimension, cap it low and say what evidence is missing. Take a position on every dimension and state what evidence would change your mind. No praise for its own sake. Plain, blunt language. Never use: delve, crucial, robust, comprehensive, leverage, landscape, foster, showcase.

Dimensions (9–10 anchor || 0–3 anchor):
- demand: pays / scrambles when it breaks || people find it interesting
- pain: costly ongoing duct-taped workaround today || there's no current solution
- customer: a named person, role, consequence || a category
- wedge: shippable now, someone pays this week || need the whole platform first
- learning: watched real usage, was surprised, adapted || surveys / demos / as expected
- durability: specific thesis on why it gets MORE essential in 3 years || rising tide / growth-rate

Bands: 45–60 strong; 30–44 refine; <30 not proven. Then 2–3 directions: one minimal wedge (ships fastest), one ideal version (best long-term), optionally one lateral (reframes the problem) — each with effort S/M/L and risk Low/Med/High. Recommend one, tied to the weakest dimension. End with ONE concrete real-world action that produces evidence to move the weakest dimension — specific, not "validate the market".

Respond with ONLY a JSON object, no markdown, no preamble, exactly this shape:
{"product":"","one_liner":"","summary":"2-3 sentence read of what you found","dimensions":[{"key":"demand","score":0,"justification":"one line tied to a fact you found","evidence_missing":"what you couldn't find","change_my_mind":"what evidence would move this"}],"weakest_link":"<dimension key>","verdict":"one blunt sentence","directions":[{"label":"","kind":"minimal_wedge|ideal|lateral","effort":"S|M|L","risk":"Low|Med|High","summary":""}],"recommendation":"one line tied to the weakest dimension","assignment":"one concrete action"}
All six dimensions in the array, in the order listed."""

URL_RE = re.compile(r"^https?://\S{4,2000}$")


class Handler(BaseHTTPRequestHandler):
    server_version = "appraiser/1.0"

    def _send(self, code, payload, raw=False):
        body = payload if raw else json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path.rstrip("/") != "/appraise":
            return self._send(404, {"error": {"message": "not found"}})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length))
            assert isinstance(data, dict)
        except Exception:
            return self._send(400, {"error": {"message": "send JSON: {url, passcode}"}})
        if str(data.get("passcode", "")) != PASSCODE:
            return self._send(401, {"error": {"message": "wrong passcode"}})
        url = str(data.get("url", "")).strip()
        if not URL_RE.match(url):
            return self._send(400, {"error": {"message": "send a valid http(s) product URL"}})

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps({
                "model": "claude-sonnet-4-6",
                "max_tokens": 4000,
                "messages": [{"role": "user", "content": PROMPT_TEMPLATE.replace("__URL__", url)}],
                "tools": [{"type": "web_search_20250305", "name": "web_search"}],
            }).encode(),
            headers={
                "Content-Type": "application/json",
                "x-api-key": API_KEY,
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=280) as r:
                self._send(r.status, r.read(), raw=True)
        except urllib.error.HTTPError as e:
            # pass Anthropic's error body through so the frontend shows the real reason
            self._send(e.code, e.read() or json.dumps(
                {"error": {"message": f"upstream returned {e.code}"}}).encode(), raw=True)
        except Exception as e:
            self._send(502, {"error": {"message": f"upstream error: {e.__class__.__name__}"}})

    def log_message(self, fmt, *args):
        # skip passcodes/bodies; method + path + status is enough
        print(f"{self.address_string()} {fmt % args}", flush=True)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
