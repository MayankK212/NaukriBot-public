"""
Offline tests for the Gemini LLM answerer (no live Naukri session needed).

Usage:
  python test_llm_answers.py            # all offline tests
  python test_llm_answers.py --parser   # JSON parsing only
  python test_llm_answers.py --validate # answer validation only
  python test_llm_answers.py --suggest  # suggest_answer integration only
  python test_llm_answers.py --live     # real Gemini calls (needs GEMINI_API_KEY in .env)

None of the offline tests touch the network. resume_data.json is read only at
runtime by the caller, never committed.
"""

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from llm_answers import (  # noqa: E402
    GeminiAnswerer,
    extract_candidates,
    parse_model_text,
)
from auto_apply import NaukriInteractiveApplier  # noqa: E402

PASS = 0
FAIL = 0


_SENTINEL = object()


def check(name, got, expected=_SENTINEL):
    # Supports both check(name, got, expected) and check(got, expected).
    global PASS, FAIL
    if expected is _SENTINEL:
        name, got, expected = f"eq({name!r})", name, got
    ok = got == expected
    PASS += ok
    FAIL += not ok
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: got={got!r} expected={expected!r}")


def check_true(name, cond):
    check(name, bool(cond), True)


# ------------------------------------------------------------------
# --parser
# ------------------------------------------------------------------
def test_parser():
    print("\n== parser ==")
    plain = '{"answer": "Yes", "confidence": "high", "reason": "profile"}'
    r = parse_model_text(plain)
    check_true("plain json", isinstance(r, dict) and r["answer"] == "Yes" and r["confidence"] == "high")

    fenced = '```json\n{"answer": "60 days", "confidence": "medium", "reason": "x"}\n```'
    check("fenced json", parse_model_text(fenced)["answer"], "60 days")

    prose = 'Sure! Here you go: {"answer": "Noida", "confidence": "high", "reason": "y"} Thanks!'
    check("trailing prose", parse_model_text(prose)["answer"], "Noida")

    check("empty input", parse_model_text(""), None)
    check("garbage input", parse_model_text("garbage"), None)
    check("array input", parse_model_text('[1, 2, 3]'), None)
    check("missing answer", parse_model_text('{"confidence": "high"}'), None)
    check("bad confidence", parse_model_text('{"answer": "x", "confidence": "maybe"}'), None)
    r = parse_model_text('{"answer": "No", "confidence": "low", "reason": "unknown"}')
    check_true("low confidence parsed", r is not None and r["confidence"] == "low")

    env = {"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}
    check("valid envelope", extract_candidates(env), "hi")
    check("error envelope", extract_candidates({"error": {"message": "boom"}}), None)
    check("empty envelope", extract_candidates({}), None)
    check("non-dict body", extract_candidates("nope"), None)


# ------------------------------------------------------------------
# --validate
# ------------------------------------------------------------------
def _answerer(api_key="fake", **kw):
    return GeminiAnswerer({"current_location": "Noida"}, api_key=api_key, **kw)


def test_validate():
    print("\n== validate ==")
    a = _answerer()

    # single_choice exact option → canonical label
    r = a._validate({"answer": "Yes", "confidence": "high", "reason": ""},
                    "single_choice", ["Yes", "No"])
    check(r, ("Yes", True))

    # low confidence → never confident
    r = a._validate({"answer": "Yes", "confidence": "low", "reason": "unsure"},
                    "single_choice", ["Yes", "No"])
    check(r, (None, False))

    # answer not an option → flag
    r = a._validate({"answer": "Maybe", "confidence": "high", "reason": ""},
                    "single_choice", ["Yes", "No"])
    check(r, (None, False))

    # punctuation-insensitive canonical label
    r = a._validate({"answer": "4 - 6 years", "confidence": "high", "reason": ""},
                    "single_choice", ["4-6 years", "6-8 years"])
    check(r, ("4-6 years", True))

    # multi_choice, every piece valid
    r = a._validate({"answer": "Python, SQL", "confidence": "high", "reason": ""},
                    "multi_choice", ["Python", "SQL", "Java"])
    check(r, ("Python, SQL", True))

    # multi_choice with an unknown piece → no partial apply
    r = a._validate({"answer": "Python, Rust", "confidence": "high", "reason": ""},
                    "multi_choice", ["Python", "SQL"])
    check(r, (None, False))

    # text mode: non-empty accepted, empty rejected
    r = a._validate({"answer": "60 days", "confidence": "medium", "reason": ""},
                    "text", [])
    check(r, ("60 days", True))
    r = a._validate({"answer": "  ", "confidence": "high", "reason": ""}, "text", [])
    check(r, (None, False))

    # unvalidatable parsed input
    check(a._validate(None, "single_choice", ["Yes"]), (None, False))


def test_suggest_smoke(monkey_calls=None):
    """suggest-level tests with a monkeypatched _call_api (no network)."""
    print("\n== suggest (monkeypatched API) ==")
    calls = []

    a = _answerer()
    a._call_api = lambda prompt: (calls.append(prompt), '{"answer": "Yes", "confidence": "high", "reason": "t"}')[1]

    r = a.suggest("Do you have a passport?", "single_choice", ["Yes", "No"])
    check(r, ("Yes", True))
    check_true("one api call", len(calls) == 1)

    # cache hit → no second call
    r2 = a.suggest("Do you have a passport?", "single_choice", ["Yes", "No"])
    check(r2, ("Yes", True))
    check_true("cache hit (still 1 call)", len(calls) == 1)

    # low confidence → flagged
    b = _answerer()
    b._call_api = lambda prompt: '{"answer": "Yes", "confidence": "low", "reason": "unsure"}'
    check(b.suggest("Will you work night shifts?", "single_choice", ["Yes", "No"]), (None, False))

    # model returns a non-option → flagged
    c = _answerer()
    c._call_api = lambda prompt: '{"answer": "Maybe", "confidence": "high", "reason": "hmm"}'
    check(c.suggest("Any preference?", "single_choice", ["Yes", "No"]), (None, False))

    # disabled (blank key) → never calls API (blank beats the env fallback)
    d = GeminiAnswerer({}, api_key=" ")
    d._call_api = lambda prompt: (_ for _ in ()).throw(AssertionError("must not call"))
    check(d.suggest("Q?", "single_choice", ["Yes"]), (None, False))

    # per-job cap: max_calls_per_job=1, second distinct question → flagged
    e = _answerer(max_calls_per_job=1)
    e._call_api = lambda prompt: '{"answer": "Yes", "confidence": "high", "reason": "t"}'
    check(e.suggest("Q1?", "single_choice", ["Yes", "No"]), ("Yes", True))
    check(e.suggest("Q2?", "single_choice", ["Yes", "No"]), (None, False))
    check_true("quota reason recorded", "quota" in (e.last_reason or ""))


# ------------------------------------------------------------------
# --suggest  (integration with NaukriInteractiveApplier)
# ------------------------------------------------------------------
class FakeAnswerer:
    def __init__(self, answer="Yes", confident=True):
        self.answer, self.confident = answer, confident

    def suggest(self, question, mode, option_texts):
        return self.answer, self.confident

    def reset(self):
        pass


def test_suggest_integration():
    print("\n== suggest_answer integration ==")
    profile = {"full_name": "ALEX SAMPLE"}

    # no LLM → cannot answer → flagged
    applier = NaukriInteractiveApplier(None, profile, interactive=False)
    check(applier.suggest_answer("What is your name?", "text", []), ("", False))

    # fake confident answerer
    applier2 = NaukriInteractiveApplier(None, profile, interactive=False,
                                        llm_answerer=FakeAnswerer("ALEX SAMPLE", True))
    check(applier2.suggest_answer("What is your name?", "text", []), ("ALEX SAMPLE", True))

    # fake unsure answerer → flagged
    applier3 = NaukriInteractiveApplier(None, profile, interactive=False,
                                        llm_answerer=FakeAnswerer("", False))
    check(applier3.suggest_answer("Anything?", "single_choice", ["Yes", "No"]), ("", False))


# ------------------------------------------------------------------
# --live
# ------------------------------------------------------------------
def test_live():
    from database import get_resume_data
    print("\n== live Gemini (needs GEMINI_API_KEY in .env) ==")
    profile = get_resume_data()
    if not (os.getenv("GEMINI_API_KEY") or "").strip():
        print("SKIP: GEMINI_API_KEY not set")
        return
    a = GeminiAnswerer(profile)

    cases = [
        ("Which city are you currently based in?", "single_choice",
         ["Noida", "Gurgaon", "Delhi / NCR", "Bengaluru"]),
        ("Select all your skills", "multi_choice",
         ["Python", "SQL", "Java", "Machine Learning", "Excel"]),
        ("How many years of experience do you have with PySpark?",
         "single_choice", ["0-2", "2-4", "4-6", "6-8", "8+"]),
        ("What is your notice period?", "single_choice",
         ["Immediate", "15 days", "30 days", "60 days", "90 days"]),
        # NOT answerable from profile → must flag, never guess:
        ("Are you willing to work night shifts?", "single_choice", ["Yes", "No"]),
    ]
    for q, mode, opts in cases:
        ans, conf = a.suggest(q, mode, opts)
        if conf:
            picked = [p.strip() for p in str(ans).split(",") if p.strip()]
            ok = all(p in opts for p in picked)
            print(f"[{'PASS' if ok else 'FAIL'}] {q!r} → {ans!r} (confident={conf})")
            global PASS, FAIL
            PASS += ok
            FAIL += not ok
        else:
            print(f"[FLAG] {q!r} → needs_review ({a.last_reason})")


# ------------------------------------------------------------------
# main
# ------------------------------------------------------------------
def main():
    args = set(sys.argv[1:])
    offline_all = not (args & {"--parser", "--validate", "--suggest", "--live"})
    if offline_all or "--parser" in args:
        test_parser()
    if offline_all or "--validate" in args:
        test_validate()
        test_suggest_smoke()
    if offline_all or "--suggest" in args:
        test_suggest_integration()
    if "--live" in args:
        test_live()

    print(f"\n===== RESULT: {PASS} passed, {FAIL} failed =====")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
