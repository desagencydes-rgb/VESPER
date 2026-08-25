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

2. IDENTITY IS FETCHED, NOT DECLARED. `MEMORY.md` §1: node 1 carries two
   `llama-server.exe` and only one is comparable, so a figure without its build
   tag is not a measurement. The adapter reads the server's OWN `/props` at
   construction and carries `build_info` into every result. A provider that
   cannot say which build answered produces unauditable numbers, and an
   unauditable number is what INV-HW-2 refuses. The read also doubles as the
   liveness check: the instrument's self-report is not evidence, so we ask the
   server what it is rather than trusting the URL we were handed.

   A REMOTE API HAS NO BUILD TAG, and the same discipline still applies: it is
   attributed by MODEL ID, which the caller names and `/models` is consulted to
   confirm. Asking the endpoint which model it would pick and then recording
   that answer as provenance is circular, so the model is never chosen here.
   `build_provider` refuses an endpoint that can offer neither -- fail-closed,
   because a result nothing can be traced to is not evidence.

   SR-003 is why the remote path exists at all: "automatic API switching when
   quota/error occurs, with retry without stopping." APIs are the primary
   route and SR-005's local model is the OFFLINE BACKUP -- not the other way
   round, which is how this was first built.

3. A CREDENTIAL REACHES THE REQUEST HEADER AND NOTHING ELSE. It is held in a
   closure, never on `EndpointIdentity` -- which is copied verbatim into every
   result and therefore into telemetry, the evidence chain and any checkpoint
   carrying one. A key on that dataclass would be persisted by all three and
   the leak would look exactly like correct provenance recording. `L-006`
   asserts a canary key appears in no result, no published record and no file
   the run wrote.

4. FAILURES ARE CLASSIFIED INTO THE GATEWAY'S VOCABULARY, NOT INVENTED. SR-004
   asks for retry timing a human can act on, and `ModelGateway` decides that
   from `classification`. An exception without one is treated as
   `server_error` and retried -- so an auth failure that arrives unclassified
   would be retried forever. Every raise below sets the attribute.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

# core/gateway.py's TERMINAL/TRANSIENT vocabulary. Imported rather than
# restated so the two cannot drift apart silently.
from core.gateway import Provider


class EndpointError(Exception):
    """Carries `classification`, which is what decides retry timing.

    `retry_after_ms` is the SERVER'S OWN answer to "when?", when it gave one.
    A computed backoff is a guess about a quota whose shape we cannot see: a
    500 ms retry against a per-DAY limit is not patience, it is a second
    identical failure. SR-004 asks for a retry time a human can act on, and the
    authoritative one is the number the server sent.

    `quota_limit` IS THE FIELD THAT SEPARATES "SPENT" FROM "NEVER HAD ANY", and
    it is the one thing the status code cannot tell you. Measured 2026-08-25: a
    `429` carrying `limit: 0` means the tier has no allowance for that model at
    all, so the refusal is permanent, whereas the same status with a non-zero
    limit returns when the window rolls. `core/gateway.py` books it; None means
    the server published no limit, which is NOT zero.
    """

    def __init__(self, message: str, classification: str,
                 retry_after_ms: int | None = None,
                 quota_limit: int | None = None) -> None:
        super().__init__(message)
        self.classification = classification
        self.retry_after_ms = retry_after_ms
        self.quota_limit = quota_limit


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
    """What answered, recorded so a result can be attributed later.

    NO CREDENTIAL IS EVER STORED HERE. This object is copied verbatim into
    every result and therefore into telemetry, the evidence chain and any
    checkpoint that carries a result. A key on this dataclass would be
    persisted by every one of them, and the leak would look exactly like
    correct provenance recording. The key lives in a closure in
    `build_provider` and reaches only the request header.
    """

    base_url: str
    build_info: str | None
    model_path: str | None
    n_ctx: int | None
    # Remote endpoints have no build tag. Their attributable identity is the
    # model id the API itself reports, which is the same discipline applied to
    # a different kind of server.
    model: str | None = None

    def attribution(self) -> str | None:
        """What this endpoint can be identified BY, or None if nothing can.

        A local runner attributes by build; a remote API attributes by model
        id. A result that can do neither is unattributable, and an
        unattributable result is not evidence -- callers refuse it rather than
        record a figure nobody can trace.
        """
        return self.build_info or self.model

    def to_dict(self) -> dict:
        return {"base_url": self.base_url, "build_info": self.build_info,
                "model_path": self.model_path, "n_ctx": self.n_ctx,
                "model": self.model}


# THE QUOTA CEILING, READ OUT OF PROSE BECAUSE THAT IS WHERE IT IS.
#
# `tests/fixtures/provider-responses/google-429-limit-zero.json` is a verbatim
# capture from 2026-08-25. Its structured `details` block carries the metric
# names, the quota ids and a retry delay -- and NOT the limit. The only place
# `limit: 0` appears anywhere in that response is the human-readable `message`
# string, three times.
#
# So this regex is not laziness, it is the shape of the data, and it is the
# most fragile thing in this module: a vendor rewording that sentence removes
# the only signal that separates a permanent refusal from a temporary one, and
# nothing will fail loudly when they do -- the ladder just starts retrying a
# dead rung again. The fixture README says these expire; this is the line that
# expires first, and re-measuring it is a live call the owner has to make.
# A REQUEST WITH NO USER-AGENT IS REFUSED BY AT LEAST ONE PROVIDER'S WAF, and
# it does not look like a WAF refusal when it happens.
#
# MEASURED 2026-08-25, same key, same payload, differing only in this header:
#   User-Agent: Python-urllib/3.13   -> HTTP 403
#   User-Agent: curl/8.7.1           -> HTTP 200
#   User-Agent: vesper/1.0           -> HTTP 200
#
# urllib sends `Python-urllib/<version>` unless told otherwise, so the default
# is the one value that fails. THE DANGEROUS PART IS THE CLASSIFICATION: 403
# maps to `auth_failed`, which is TERMINAL, so the gateway would retire a
# working E1-PRIVATE rung permanently on its first call and the owner would
# reasonably conclude their key was bad. Half the private-safe capacity would
# disappear with a plausible-looking explanation.
#
# Named for VESPER rather than disguised as a browser: the point is to identify
# the caller honestly, not to evade a filter that is entitled to refuse us.
USER_AGENT = "vesper/1.0 (+https://github.com/desagencydes-rgb/VESPER)"

_QUOTA_LIMIT = re.compile(r"\blimit:\s*(\d+)")

# DRIFT DETECTOR FOR THE LINE ABOVE, and the reason it needs one.
#
# The limit that separates "this tier has no allowance" from "today's window is
# spent" exists ONLY in the prose of the vendor's `message`. Verified against
# the captured refusal: the structured QuotaFailure block carries `quotaMetric`,
# `quotaId` and `quotaDimensions` -- and no limit value at all. So a regex over
# a sentence is not laziness here, it is the only signal there is.
#
# THAT MAKES IT THE MOST PERISHABLE LINE IN THE TREE. If the vendor rewords the
# sentence, `_quota_limit_from` returns None, the refusal books as EXHAUSTED,
# the ladder retries a permanently dead rung every day forever -- AND NOTHING
# GOES RED. The fixture still parses, because the fixture is frozen; the check
# still passes, because it checks the fixture. A test that cannot fail when the
# world changes is not covering the thing it appears to cover.
#
# So absence of a match is split in two. "No limit published" is ordinary and
# silent -- most providers never publish one. "A refusal that talks about a
# limit in a shape we could not read" is a PARSER DRIFT signal, and it is said
# out loud. This deliberately does NOT change routing: EXHAUSTED remains the
# safe default either way (defaulting a missing field to zero would retire a
# working model on its first rate limit, which is far worse). It only makes a
# silent degradation visible, which is the whole difference between a bug that
# gets found and one that quietly costs a rung.
_QUOTA_LIMIT_SUSPECT = re.compile(
    r"\b(?:limit|quota)\b[^.\n]{0,40}?\b(?:is|of|=|:)\s*\d", re.I)


def _quota_limit_from(message: str) -> int | None:
    """The smallest published limit in a refusal message, or None.

    THE MINIMUM, NOT THE FIRST AND NOT THE LAST. The captured refusal names
    three metrics -- per-day requests, per-minute requests and input tokens --
    and a zero on ANY of them is enough to make the call impossible. Taking the
    first match would be reading whichever metric the vendor happened to order
    first; taking the minimum reads the binding constraint, which is the one
    that decides whether this rung can ever answer.
    """
    found = [int(m) for m in _QUOTA_LIMIT.findall(message or "")]
    return min(found) if found else None


def quota_limit_parse_suspect(message: str) -> bool:
    """True when a refusal names a limit in a shape the parser did not read.

    NOT an error and NOT a routing input -- a signal that the one line standing
    between "permanently unavailable" and "back tomorrow" may have drifted. See
    the comment on `_QUOTA_LIMIT_SUSPECT`. A True here means: re-measure against
    a live refusal, because the fixture can no longer tell you.
    """
    m = message or ""
    if _QUOTA_LIMIT.search(m):
        return False                      # parsed fine; nothing to report
    return bool(_QUOTA_LIMIT_SUSPECT.search(m))


def _error_detail(err) -> tuple:
    """Read an HTTP error body ONCE, for its retry hint, message and quota limit.

    Read once because `err.read()` is not repeatable -- a second caller gets
    an empty string and silently concludes the server said nothing. All three
    facts come from the same read for that reason.

    RETURNS `retry_after_ms = None` FOR A NON-POSITIVE HINT, and that is the
    fix rather than a tidy-up. Measured 2026-08-24: this endpoint's `retryDelay`
    varies run to run -- 36s, 19s, and sometimes 0s -- and an earlier version
    took 0 at face value. `if hint is not None` then chose it over the
    exponential backoff, slept zero, and retried instantly. A server saying
    "retry immediately" on a 429 is not an instruction worth obeying: it turns
    a backoff into a hammer, against the exact endpoint that just asked for
    less traffic. Absent and zero are treated the same, and the computed
    backoff stands.
    """
    retry_ms = None
    message = ""
    hdr = None
    try:
        hdr = err.headers.get("Retry-After")
    except Exception:  # noqa: BLE001
        pass
    if hdr:
        try:
            v = int(float(hdr) * 1000)
            retry_ms = v if v > 0 else None
        except (TypeError, ValueError):
            pass
    try:
        d = json.loads(err.read().decode("utf-8", errors="replace"))
        if isinstance(d, list):
            d = d[0] if d else {}
        e = d.get("error") or {}
        message = (e.get("message") or "")[:300]
        if retry_ms is None:
            for det in (e.get("details") or []):
                delay = det.get("retryDelay")
                if isinstance(delay, str) and delay.endswith("s"):
                    try:
                        v = int(float(delay[:-1]) * 1000)
                    except (TypeError, ValueError):
                        continue
                    if v > 0:
                        retry_ms = v
                    break
    except Exception:  # noqa: BLE001
        pass
    return retry_ms, message, _quota_limit_from(message)


def _post_json(url: str, payload: dict, timeout: float,
               headers: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8")
    h = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        retry_ms, message, limit = _error_detail(e)
        raise EndpointError(
            f"HTTP {e.code} from {url}" + (f" -- {message}" if message else ""),
            _STATUS_CLASS.get(e.code, "server_error"), retry_ms, limit) from e
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


def _get_json(url: str, timeout: float, headers: dict | None = None) -> dict:
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as r:
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


def _auth_headers(api_key: str | None) -> dict:
    """The ONLY place a credential is attached to anything.

    Returned fresh each call and never stored on a dataclass, so there is no
    object holding a key that some later `to_dict()` could serialise into
    telemetry. INV-TRUST-1 forbids a Z2 node RECEIVING a secret; nothing
    forbids a result carrying one into a log, which is why that has to be
    prevented structurally rather than remembered.
    """
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def identify(base_url: str, *, timeout: float = 10.0,
             api_key: str | None = None,
             model: str | None = None) -> EndpointIdentity:
    """Ask the endpoint what it is. Raises rather than guessing.

    Called before a provider is built, so an endpoint that cannot attribute
    its own output never becomes a provider at all. This is the fail-closed
    direction: an adapter that shrugged and recorded `build_info: null` would
    put an unattributable figure into the evidence chain, and the whole
    build-tag discipline exists because that has already cost this project a
    day once.
    """
    base = base_url.rstrip("/")
    headers = _auth_headers(api_key)
    try:
        props = _get_json(base + "/props", timeout, headers)
    except EndpointError:
        # No `/props` -- a remote OpenAI-compatible API rather than a local
        # runner. It has no build tag to give, so it is attributed by model id,
        # and the model must be NAMED by the caller: asking the endpoint which
        # model it would pick and then recording that answer as provenance is
        # circular. `/v1/models` is consulted only to confirm the named model
        # is actually served, never to choose one.
        if not model:
            raise EndpointError(
                f"{base} exposes no /props and no model was named. A remote "
                "endpoint is attributed by model id; without one, results "
                "from it cannot be traced to what produced them.",
                "bad_request") from None
        try:
            listed = _get_json(base + "/models", timeout, headers)
            ids = {m.get("id") for m in (listed.get("data") or [])}
            if ids and model not in ids:
                raise EndpointError(
                    f"model {model!r} is not served by {base}. Available: "
                    f"{sorted(i for i in ids if i)[:8]}", "bad_request")
        except EndpointError as e:
            # A listing that is absent or forbidden is not proof of anything;
            # only a listing that ANSWERS and omits the model is.
            if getattr(e, "classification", "") == "bad_request" and \
                    "is not served by" in str(e):
                raise
        return EndpointIdentity(base_url=base, build_info=None,
                                model_path=None, n_ctx=None, model=model)
    dm = props.get("default_generation_settings") or {}
    return EndpointIdentity(
        base_url=base,
        build_info=props.get("build_info"),
        model_path=props.get("model_path") or dm.get("model"),
        n_ctx=dm.get("n_ctx") or props.get("n_ctx"),
        model=model,
    )


_VERSIONED = re.compile(r"^(v\d+(alpha|beta)?\d*|openai)$", re.I)


def _chat_suffix(base_url: str) -> str:
    """Where chat/completions lives, decided from the url rather than assumed.

    A local runner exposes it at `/v1/chat/completions` from the root. A remote
    OpenAI-compatible base already carries its own version segment, so
    appending `/v1` again doubles it.

    THIS FILE GOT IT WRONG WHILE WARNING ABOUT IT. The first version tested
    `endswith("/v1")`, which is false for `.../v1beta/openai`, and every remote
    call went to `.../v1beta/openai/v1/chat/completions`. It WORKED -- that
    vendor tolerates the doubled segment -- so nothing failed and the defect
    surfaced only because a 429 printed the full url into an error message. A
    bug that the server forgives is one that waits for a server that does not.
    """
    tail = base_url.rstrip("/").rsplit("/", 1)[-1]
    return ("/chat/completions" if _VERSIONED.match(tail)
            else "/v1/chat/completions")


def _budget(options: dict) -> int:
    """The token allowance for one call, under either of its two spellings.

    `max_tokens` is the OpenAI spelling and `n_predict` is the local runner's.
    `core.gateway` derives the budget from `core.effort` and writes BOTH, but a
    caller reaching this module directly may write either -- and reading only
    `n_predict`, as this did until 2026-08-25, silently discarded a budget
    written under the other name and served 256 instead. A truncation at 256
    does not look like a dropped setting; it looks like a model that stopped.

    `max_tokens` wins where both appear, because that is the one the effort
    policy writes first and a disagreement means somebody set the other by hand.
    """
    return int(options.get("max_tokens") or options.get("n_predict") or 256)


def _call_raw(ident: EndpointIdentity, prompt: str, options: dict,
              timeout: float, headers: dict | None = None) -> dict:
    """The raw continuation endpoint. Used for MEASUREMENT.

    `tools/spike/profile_node.py` drives this same path, so a throughput figure
    and a routed call exercise the same code when this mode is chosen. It does
    NOT apply the model's chat template, so an instruction-tuned model
    CONTINUES the prompt instead of answering it -- which is correct for a
    token-rate measurement and wrong for work.
    """
    payload = {
        "prompt": prompt,
        "n_predict": _budget(options),
        "temperature": float(options.get("temperature", 0.7)),
        "stream": False,
    }
    if "stop" in options:
        payload["stop"] = options["stop"]
    d = _post_json(ident.base_url + "/completion", payload, timeout, headers)
    timings = d.get("timings") or {}
    return {
        "text": d.get("content", ""),
        "tokens_predicted": d.get("tokens_predicted"),
        "tokens_evaluated": d.get("tokens_evaluated"),
        "tokens_cached": d.get("tokens_cached"),
        "predicted_per_second": timings.get("predicted_per_second"),
        "stop_reason": d.get("stop_type") or d.get("stopped_reason"),
        "reasoning": None,
    }


def _call_chat(ident: EndpointIdentity, prompt: str, options: dict,
               timeout: float, headers: dict | None = None) -> dict:
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
        "max_tokens": _budget(options),
        "temperature": float(options.get("temperature", 0.7)),
        "stream": False,
    }
    if "stop" in options:
        payload["stop"] = options["stop"]
    if "enable_thinking" in options:
        payload["chat_template_kwargs"] = {
            "enable_thinking": bool(options["enable_thinking"])}
    if ident.model:
        # Required by every OpenAI-compatible remote; harmless to a local
        # runner, which serves one model and ignores the field.
        payload["model"] = ident.model
    suffix = _chat_suffix(ident.base_url)
    d = _post_json(ident.base_url + suffix, payload, timeout, headers)
    choices = d.get("choices") or [{}]
    msg = choices[0].get("message") or {}
    usage = d.get("usage") or {}
    text = msg.get("content") or ""
    reasoning = msg.get("reasoning_content")
    finish = choices[0].get("finish_reason")
    if not text.strip() and not (reasoning or "").strip():
        # A NULL ANSWER THAT LOOKS LIKE A SUCCESSFUL ONE. Measured against a
        # real remote on 2026-08-24: HTTP 200, a well-formed body,
        # finish_reason "stop", and no content at all -- intermittently, on a
        # prompt that answered correctly on the retry and on every direct
        # probe. Nothing in the transport failed and nothing in the response
        # says anything went wrong.
        #
        # Passed through, this reaches the planner or the verifier as a real
        # empty answer, and they have no way to tell it from a model that
        # genuinely had nothing to say. It is the same defect shape as the
        # thinking-budget truncation above, minus the one field that made that
        # one detectable.
        #
        # So it is raised as TRANSIENT rather than returned. That is the
        # honest reading -- the model did not answer, and "did not answer" is
        # a failed attempt -- and it puts the event in `gateway.attempt`
        # history where a rate can be seen, instead of nowhere.
        #
        # WIDENED THE SAME DAY IT WAS WRITTEN. This first tested
        # `finish_reason == "stop"` only, on the reasoning that a `length`
        # finish is self-explaining. It is not: measured on the remote,
        # `finish_reason: "length"` arrives with completion_tokens 0, empty
        # content and no reasoning, at max_tokens 100 -- nowhere near the
        # budget. A reasoning model counts its thinking against that budget
        # and the OpenAI-compatible layer does not always report it, so
        # "length" can mean "spent it all before saying anything". Empty is
        # empty whatever the label says, and the label is carried in the
        # message rather than trusted as an explanation.
        raise EndpointError(
            "endpoint returned HTTP 200 with no content and no reasoning "
            f"(finish_reason={finish!r}, completion_tokens="
            f"{usage.get('completion_tokens')}). The model did not answer; a "
            "null answer is not an answer.",
            "server_error")
    # Cache evidence, where the endpoint reports it. A prompt served from
    # cache costs a fraction of one that is not, so a rate quoted without
    # saying which it was is two different numbers wearing one label.
    cached = ((usage.get("prompt_tokens_details") or {}).get("cached_tokens"))
    # `timings` is a llama.cpp extension, absent from the OpenAI schema and
    # therefore absent from a remote that only implements the spec. Read it
    # where it exists rather than timing the call from here: a rate measured on
    # this side includes the network and the client, and would quietly become a
    # different number the moment either changed.
    timings = d.get("timings") or {}
    rate = timings.get("predicted_per_second")
    return {
        "text": text,
        "tokens_predicted": usage.get("completion_tokens"),
        "tokens_evaluated": usage.get("prompt_tokens"),
        "tokens_cached": cached,
        "predicted_per_second": rate,   # None where the endpoint reports none
        "stop_reason": finish,
        "reasoning": reasoning,
    }


def build_provider(provider_id: str, profile_id: str, base_url: str, *,
                   timeout: float = 300.0,
                   mode: str = "chat",
                   api_key: str | None = None,
                   model: str | None = None,
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
        ident = identify(base_url, timeout=30.0, api_key=api_key, model=model)
    if ident.attribution() is None:
        raise ValueError(
            f"{base_url} cannot attribute its own output: no build tag and no "
            "model id. A result nothing can be traced to is not evidence, and "
            "this is the fail-closed direction -- see `identify`.")
    fn = _call_chat if mode == "chat" else _call_raw
    # Built once, held in this closure, and never stored on `ident`. See
    # `_auth_headers` and `EndpointIdentity`.
    headers = _auth_headers(api_key)

    def call(prompt: str, options: dict) -> dict:
        out = fn(ident, prompt, options, timeout, headers)
        # EVIDENCE, not decoration. A result that cannot say which build, which
        # model and which calling mode produced it cannot be compared with
        # another -- and comparability is the entire point of the build tag.
        out["endpoint"] = ident.to_dict()
        out["mode"] = mode
        return out

    # THE LEDGER'S SECOND KEY, carried from the identity rather than invented.
    # A local runner serves one model and reports none, and "" is the honest key
    # for that -- it says "this endpoint's only model", which is true, where
    # copying `provider_id` in would make two models on one account share a
    # quota line and retire both when either is refused.
    return Provider(provider_id=provider_id, profile_id=profile_id, call=call,
                    model=ident.model or "")
