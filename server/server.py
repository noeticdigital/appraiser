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

PROMPT_TEMPLATE = """You are a product diagnostic that scores ONE product at this URL through THREE independent lenses. Your job is diagnosis, not encouragement. URL: __URL__

First, research it with web search: what it does, who it is for, pricing, real traction or usage signals, customer reviews, and the status-quo alternative people use today. A marketing website states the founder's claims — it is NOT evidence of demand. Treat claims as claims. Plain, blunt language. Never use: delve, crucial, robust, comprehensive, leverage, landscape, foster, showcase.

=== LENS 1 - FOUNDER-MODE (YC-style), six dimensions 0-10 each (60 total) ===
Be stingy: a 7+ needs concrete behavioral evidence (people paying, expanding usage, building a workflow around it, scrambling if it vanished), not a good story or a slick site. Where you only have website claims, cap it low and say what evidence is missing. Take a position on every dimension.
- demand: pays / scrambles when it breaks || people find it interesting
- pain: costly ongoing duct-taped workaround today || there's no current solution
- customer: a named person, role, consequence || a category
- wedge: shippable now, someone pays this week || need the whole platform first
- learning: watched real usage, was surprised, adapted || surveys / demos / as expected
- durability: specific thesis on why it gets MORE essential in 3 years || rising tide / growth-rate
Bands: 45-60 strong; 30-44 refine; <30 not proven. Then 2-3 directions (one minimal wedge, one ideal, optionally one lateral) each with effort S/M/L + risk Low/Med/High; recommend one tied to the weakest dimension; end with ONE concrete evidence-producing action.

=== LENS 2 - MPI BENCHMARK (Living Best QOL concept-test methodology) ===
Estimate how this product would score if run through a large consumer concept-test survey (the Living Best MPI, a QOL/eldercare study of 135 concepts). Estimate THREE fractions 0-1, grounded in research and calibrated to the study benchmarks:
- addressable: fraction who would see it as appropriate for at least one buying scenario (did NOT pick "none of the above"). Study average ~ 0.50.
- market_interest: top-3-box interest with the 3rd box discounted 50%. Study average ~ 0.27.
- purchase_interest: top-2-box purchase intent with the 2nd box discounted 50%. Study average ~ 0.14.
Calibration anchors (addressable/interest/purchase -> resulting index): BrainHQ 0.61/0.43/0.25->333 (top); Comfort Linen 0.49/0.28/0.21->150; Assistme 0.39/0.20/0.14->57 (weak); Bleep 0.42/0.20/0.07->33 (bottom). Index 100 = study average. Do NOT compute the index yourself - just estimate the three fractions honestly (most products land near or below the averages) and explain in one line, plus one line vs the benchmark.

=== LENS 3 - EXPERT PANEL (secondary cross-reference) ===
Assess as our panel of 30 aging/eldercare + Japan-market experts would. They are skeptical by default (of 30 interviews: 19 mixed, 7 skeptical, only 4 positive) and consistently probe these themes (share of experts who raised each): Product differentiation / scope (73%); Regulatory / certification e.g. Japan PMDA, reimbursement (67%); Incumbent competition / no blue ocean (53%); Elderly adoption / technology resistance (53%); Localization language + culture (47%); Distribution / local partner requirement (47%); Funding / who-pays incentive architecture (40%). Judge the product against each relevant theme; do not invent enthusiasm. If it is lukewarm or fails a theme, say so. Give an overall verdict on the panel's 5-point scale. State the single strongest Japan-market-entry risk and any genuine enabler. If the product is outside eldercare/Japan, apply the same lens by analogy and say so.

Respond with ONLY a JSON object, no markdown, no preamble, exactly this shape:
{"product":"","one_liner":"","summary":"2-3 sentence read of what you found",
 "dimensions":[{"key":"demand","score":0,"justification":"one line tied to a fact you found","evidence_missing":"what you couldn't find","change_my_mind":"what evidence would move this"}],
 "weakest_link":"<dimension key>","verdict":"one blunt sentence",
 "directions":[{"label":"","kind":"minimal_wedge|ideal|lateral","effort":"S|M|L","risk":"Low|Med|High","summary":""}],
 "recommendation":"one line tied to the weakest dimension","assignment":"one concrete action",
 "mpi":{"addressable":0.0,"market_interest":0.0,"purchase_interest":0.0,"rationale":"one line on why these fractions","vs_benchmark":"one line vs study averages"},
 "expert":{"overall_verdict":"enthusiastic_endorse|endorse|mixed|skeptical|reject","risks":[{"theme":"","severity":"high|med|low","note":"one line"}],"strengths":["one line"],"japan_entry":"single strongest entry risk or enabler","vs_quant":"expert_more_bullish|aligned|expert_more_bearish","reading":"1-2 sentences: what the expert lens adds beyond the survey score"}}
All six YC dimensions in the array, in order."""

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
                "max_tokens": 6000,
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
