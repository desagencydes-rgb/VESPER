"""An HTTP completion endpoint, adapted to `core.gateway.Provider`.

WHAT THIS IS FOR. Until this file existed, every VESPER model call in the tree
went to a test double: F1 registers three lambdas and the cost policy, router,
planner and verifier are green against them. The choke point had never had a
real call cross it.

THREE THINGS ARE DELIBERATE HERE.

1. NO RUNNER NAME APPEARS IN THIS MODULE. The endpoint's identity -- URL,
   build, model file -- arrives as data and is recorded in the evidence a call
   returns. INV-HW-1 (CI-007 scans `routing/`): write the profile, never the
   device. If a different runner speaks the same endpoint shape, it is
   configuration, not a patch.

2. THE BUILD TAG IS FETCHED, NOT DECLARED. `MEMORY.md` §1: node 1 carries two
   `llama-server.exe` and only one is comparable, so a figure without its build
   tag is not a measurement. The adapter reads the server's OWN `/props` at
   construction and carries `build_info` into every result. A provider that
   cannot say which build answered produces unauditable numbers, and an
   unauditable number is what INV-HW-2 refuses. The read also doubles as the
   liveness check: the instrument's self-report is not evidence, so we ask the
   server what it is rather than trusting the URL we were handed.

3. FAILURES ARE CLASSIFIED INTO THE GATEWAY'S VOCABULARY, NOT INVENTED. SR-004
   asks for retry timing a human can act on, and `ModelGateway` decides that
   from `classification`. An exception without one is treated as
   `server_error` and retried -- so an auth failure that arrives unclassified
   would be retried forever. Every raise below sets the attribute.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

# core/gateway.py's TERMINAL/TRANSIENT vocabulary. Imported rather than
# restated so the two cannot drift apart silently.
from core.gateway import Provider


class EndpointError(Exception):
    """Carries `classification`, which is what decides retry timing."""

    def __init__(self, message: str, classification: str) -> None:
        super().__init__(message)
        self.classification = classification


# HTTP status -> the gateway's classification. Anything unlisted is
# `server_error`, which is TRANSIENT: an unrecognised server fault is more
# likely a blip than a permanent refusal, and the retry budget is bounded.
_STATUS_CLASS = {
    400: "bad_request",
    401: "auth_failed",
    403: "auth_failed",
    404: "bad_request",
    429: "rate_limited",
    402: "quota_exhausted",
}


@dataclass(slots=True)
class EndpointIdentity:
    """What answered, recorded so a result can be attributed later."""

    base_url: str
    build_info: str | None
    model_path: str | None
    n_ctx: int | None

    def to_dict(self) -> dict:
        return {"base_url": self.base_url, "build_info": self.build_info,
                "model_path": self.model_path, "n_ctx": self.n_ctx}


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise EndpointError(
            f"HTTP {e.code} from {url}",
            _STATUS_CLASS.get(e.code, "server_error")) from e
    except TimeoutError as e:
        raise EndpointError(f"timeout after {timeout}s", "timeout") from e
    except urllib.error.URLError as e:
        # Covers refused connections and DNS. `ICMP is blocked both ways on
        # this network` -- reachability is a TCP fact here, and this is where
        # it surfaces at call time.
        reason = getattr(e, "reason", e)
        if isinstance(reason, TimeoutError):
            raise EndpointError(f"timeout after {timeout}s", "timeout") from e
        raise EndpointError(f"cannot reach {url}: {reason}",
                            "connection_error") from e


def _get_json(url: str, timeout: float) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise EndpointError(f"HTTP {e.code} from {url}",
                            _STATUS_CLASS.get(e.code, "server_error")) from e
    except TimeoutError as e:
        raise EndpointError(f"timeout after {timeout}s", "timeout") from e
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, TimeoutError):
            raise EndpointError(f"timeout after {timeout}s", "timeout") from e
        raise EndpointError(f"cannot reach {url}: {reason}",
                            "connection_error") from e


def identify(base_url: str, *, timeout: float = 10.0) -> EndpointIdentity:
    """Ask the endpoint what it is. Raises rather than guessing.

    Called before a provider is built, so an endpoint that cannot attribute
    its own output never becomes a provider at all. This is the fail-closed
    direction: an adapter that shrugged and recorded `build_info: null` would
    put an unattributable figure into the evidence chain, and the whole
    build-tag discipline exists because that has already cost this project a
    day once.
    """
    props = _get_json(base_url.rstrip("/") + "/props", timeout)
    dm = props.get("default_generation_settings") or {}
    return EndpointIdentity(
        base_url=base_url.rstrip("/"),
        build_info=props.get("build_info"),
        model_path=props.get("model_path") or dm.get("model"),
        n_ctx=dm.get("n_ctx") or props.get("n_ctx"),
    )


def _call_raw(ident: EndpointIdentity, prompt: str, options: dict,
              timeout: float) -> dict:
    """The raw continuation endpoint. Used for MEASUREMENT.

    `tools/spike/profile_node.py` drives this same path, so a throughput figure
    and a routed call exercise the same code when this mode is chosen. It does
    NOT apply the model's chat template, so an instruction-tuned model
    CONTINUES the prompt instead of answering it -- which is correct for a
    token-rate measurement and wrong for work.
    """
    payload = {
        "prompt": prompt,
        "n_predict": int(options.get("n_predict", 256)),
        "temperature": float(options.get("temperature", 0.7)),
        "stream": False,
    }
    if "stop" in options:
        payload["stop"] = options["stop"]
    d = _post_json(ident.base_url + "/completion", payload, timeout)
    timings = d.get("timings") or {}
    return {
        "text": d.get("content", ""),
        "tokens_predicted": d.get("tokens_predicted"),
        "tokens_evaluated": d.get("tokens_evaluated"),
        "predicted_per_second": timings.get("predicted_per_second"),
        "stop_reason": d.get("stop_type") or d.get("stopped_reason"),
        "reasoning": None,
    }


def _call_chat(ident: EndpointIdentity, prompt: str, options: dict,
               timeout: float) -> dict:
    """The chat endpoint, which applies the model's own template.

    A TRAP MEASURED HERE ON 2026-08-24, AND THE REASON `finish_reason` AND
    `reasoning` ARE RETURNED RATHER THAN DROPPED.

    A reasoning model spends its token budget THINKING FIRST, and this server
    splits that into a separate field. Asked to "reply with exactly: VESPER
    online." under a 40-token budget, the endpoint returned HTTP 200, a
    well-formed body, `completion_tokens: 40` -- and `content: ""`. Nothing in
    the transport failed. A caller that read `text` alone would have recorded
    an empty answer as a successful call, and a verifier comparing it against
    an expectation would have logged a disagreement with the model rather than
    with the budget.

    So the truncation is made VISIBLE: `finish_reason` distinguishes `stop`
    from `length`, and `reasoning` carries what the budget was actually spent
    on. `enable_thinking` is passed ONLY when the caller sets it -- the adapter
    does not quietly reconfigure the model, because a silent behaviour change
    is exactly what makes two runs incomparable.
    """
    msgs = []
    if options.get("system"):
        msgs.append({"role": "system", "content": options["system"]})
    msgs.append({"role": "user", "content": prompt})
    payload: dict[str, Any] = {
        "messages": msgs,
        "max_tokens": int(options.get("n_predict", 256)),
        "temperature": float(options.get("temperature", 0.7)),
        "stream": False,
    }
    if "stop" in options:
        payload["stop"] = options["stop"]
    if "enable_thinking" in options:
        payload["chat_template_kwargs"] = {
            "enable_thinking": bool(options["enable_thinking"])}
    d = _post_json(ident.base_url + "/v1/chat/completions", payload, timeout)
    choices = d.get("choices") or [{}]
    msg = choices[0].get("message") or {}
    usage = d.get("usage") or {}
    return {
        "text": msg.get("content") or "",
        "tokens_predicted": usage.get("completion_tokens"),
        "tokens_evaluated": usage.get("prompt_tokens"),
        "predicted_per_second": None,   # this endpoint does not report timings
        "stop_reason": choices[0].get("finish_reason"),
        "reasoning": msg.get("reasoning_content"),
    }


def build_provider(provider_id: str, profile_id: str, base_url: str, *,
                   timeout: float = 300.0,
                   mode: str = "chat",
                   identity: EndpointIdentity | None = None) -> Provider:
    """Wrap an endpoint as a `Provider` the gateway can call.

    `profile_id` is supplied by the caller and MUST be the id of a measured
    profile the router knows about. It is not derived from the model file:
    deriving it here would let an endpoint declare its own capability, which is
    exactly the declared-not-measured move INV-HW-2 forbids, and it would let a
    swapped model silently inherit another model's measured throughput.

    `mode` is "chat" (the model's template is applied; instructions are
    followed) or "completion" (raw continuation, the shape the throughput
    harness measures). It defaults to chat because work is the common case and
    a planner handed a continuation would be reading noise.
    """
    if mode not in ("chat", "completion"):
        raise ValueError(f"mode must be 'chat' or 'completion', got {mode!r}")
    if identity is not None:
        # FOUND BY THE LIVE RUNNER ON 2026-08-24, AND NOT FINDABLE WITHOUT IT.
        #
        # `identity` carries its own `base_url` and the call path uses THAT.
        # So passing a cached identity alongside a different `base_url`
        # silently ignored the argument: L-004 built a provider for a dead port
        # to test connection failure, handed it the identity of the LIVE
        # endpoint for convenience, and got a healthy 200 back. The test was
        # asserting connection classification against a working server.
        #
        # Nothing failed. It would have been a caller building several
        # providers from one cached identity and sending all of them to one
        # endpoint, with every result correctly labelled as coming from that
        # endpoint -- self-consistent, and wrong.
        if identity.base_url != base_url.rstrip("/"):
            raise ValueError(
                f"identity is for {identity.base_url!r} but base_url is "
                f"{base_url!r}. Re-identify the endpoint rather than reusing "
                "another one's identity: the identity decides where calls go, "
                "so a mismatch would send them somewhere the caller did not "
                "name and label them correctly on arrival.")
        ident = identity
    else:
        ident = identify(base_url, timeout=30.0)
    fn = _call_chat if mode == "chat" else _call_raw

    def call(prompt: str, options: dict) -> dict:
        out = fn(ident, prompt, options, timeout)
        # EVIDENCE, not decoration. A result that cannot say which build, which
        # model and which calling mode produced it cannot be compared with
        # another -- and comparability is the entire point of the build tag.
        out["endpoint"] = ident.to_dict()
        out["mode"] = mode
        return out

    return Provider(provider_id=provider_id, profile_id=profile_id, call=call)
