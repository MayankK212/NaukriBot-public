import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Database functions
from database import _get_db_objects, get_resume_data, job_fingerprint
# Shared location logic (keeps scraper + apply consistent)
from scraper import _get_locations, _matches_location
from browser_setup import launch_browser, new_context

load_dotenv()

LOCAL_STORAGE_PATH = Path(__file__).with_name("resume_data.json")
APPLIED_JSON_PATH = Path(__file__).with_name("applied_jobs.json")
DEBUG_DIR = Path(__file__).with_name("debug")  # 🐞 DOM dumps land here on failure

# ==========================================
# 📂 LOCAL APPLIED JOBS STORAGE HELPERS
# ==========================================
def load_local_applied_jobs():
    """Loads all applied jobs from local applied_jobs.json."""
    if APPLIED_JSON_PATH.exists():
        with APPLIED_JSON_PATH.open("r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []


def save_local_applied_job(job_data):
    """
    Appends a single applied job to local applied_jobs.json without overwriting.
    Skips if the link OR the content fingerprint (title/company/location/
    salary/rating) already exists — so a changed link with identical details
    is still treated as a duplicate and NOT inserted.
    """
    existing_jobs = load_local_applied_jobs()

    new_link = job_data.get("link")
    new_fp = job_fingerprint(job_data)

    for job in existing_jobs:
        if new_link and job.get("link") == new_link:
            print("↩️  Skipped applied_jobs.json (same link already present).")
            return
        if job_fingerprint(job) == new_fp:
            print("↩️  Skipped applied_jobs.json (same job details already present).")
            return

    existing_jobs.append(job_data)
    with APPLIED_JSON_PATH.open("w", encoding="utf-8") as f:
        json.dump(existing_jobs, f, indent=2)
    print("💾 Locally appended to applied_jobs.json")


def applied_job_exists(applied_collection, job_data):
    """
    True if 'applied_jobs' already contains this job — matched by EITHER the
    exact link OR the content fingerprint (so a changed link with identical
    details is still recognised as a duplicate).
    """
    conditions = [{"fingerprint": job_fingerprint(job_data)}]
    if job_data.get("link"):
        conditions.append({"link": job_data["link"]})
    try:
        return applied_collection.find_one({"$or": conditions}, {"_id": 1}) is not None
    except Exception:
        return False


# ==========================================
# 🧠 DYNAMIC CHATBOT / QUESTIONNAIRE ENGINE
# ==========================================
class NaukriInteractiveApplier:
    """
    Handles Naukri's React chatbot "Side Drawer" that asks screening
    questions one-at-a-time. Detection is class-based (IDs are dynamic),
    extraction targets the latest bot bubble, and each answer is confirmed
    by the user via CLI before the chat is advanced.
    """

    # ---- Static, class-based selectors (dynamic IDs are ignored) ----
    DRAWER = ".chatbot_Drawer, [class*='chatbot_Drawer'], .chatbot_MessageContainer"
    BOT_BUBBLE = (
        ".chatbot_Drawer li.botItem .botMsg, "
        "[class*='chatbot_Drawer'] li.botItem .botMsg, "
        "li.botItem .botMsg"
    )
    # Answer input widgets inside the drawer
    TEXT_INPUT = (
        ".chatbot_Drawer div[contenteditable='true'], "
        ".chatbot_Drawer textarea, "
        ".chatbot_Drawer input.textbox, "
        ".chatbot_Drawer input[type='text'], "
        "[class*='chatbot_Drawer'] div[contenteditable='true'], "
        "[class*='chatbot_Drawer'] input[type='text'], "
        "[class*='chatbot_Drawer'] textarea"
    )
    # Radio/checkbox options are located by their real <input> elements
    # scoped to the drawer (see _choice_options), so no wrapper selectors here.
    SEND_BTN = (
        ".chatbot_Drawer .sendMsg, "
        ".chatbot_Drawer .sendMsgbtn, "
        ".chatbot_Drawer div[class*='sendMsg'], "
        ".chatbot_Drawer button:has-text('Save'), "
        ".chatbot_Drawer button:has-text('Send'), "
        "[class*='chatbot_Drawer'] div[class*='sendMsg']"
    )

    MAX_QUESTIONS = 25          # safety cap against infinite loops
    NEW_Q_TIMEOUT = 1200       # ms to wait for the next bot bubble

    def __init__(self, page, user_profile, interactive=True):
        self.page = page
        self.profile = user_profile or {}
        # interactive=False → fully unattended: no prompts, auto-submit.
        self.interactive = interactive

    # ---------------------------------------------------------------
    # DEBUG
    # ---------------------------------------------------------------
    def _dump_debug(self, page, tag):
        """Saves drawer/page HTML + a screenshot so failures are inspectable."""
        try:
            DEBUG_DIR.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%H%M%S")
            base = DEBUG_DIR / f"{tag}_{stamp}"
            # Prefer the drawer's HTML; fall back to full page.
            drawer = page.locator(self.DRAWER).first
            if drawer.count() > 0:
                html = drawer.inner_html()
            else:
                html = page.content()
            base.with_suffix(".html").write_text(html, encoding="utf-8")
            try:
                page.screenshot(path=str(base.with_suffix(".png")))
            except Exception:
                pass
            print(f"   🐞 Debug dump saved: {base}.html")
        except Exception as e:
            print(f"   🐞 Debug dump failed: {e}")

    # ---------------------------------------------------------------
    # DETECTION
    # ---------------------------------------------------------------
    def wait_for_drawer(self, page, timeout=20000):
        """
        Waits for the side drawer to actually render its first bubble.
        Handles the slow/intermediate-screen case by waiting for the
        container first, then polling for a bubble separately.
        """
        try:
            page.wait_for_selector(self.DRAWER, state="visible", timeout=timeout)
        except PWTimeout:
            return False

        # Container is up; the first bot bubble may lag (intermediate screen,
        # slow React mount). Poll independently instead of failing immediately.
        deadline = time.time() + (timeout / 1000.0)
        while time.time() < deadline:
            if self._bot_bubbles(page).count() > 0 and self.get_latest_question(page):
                return True
            page.wait_for_timeout(400)
        return False

    # ---------------------------------------------------------------
    # QUESTION EXTRACTION
    # ---------------------------------------------------------------
    def _bot_bubbles(self, page):
        return page.locator(self.BOT_BUBBLE)

    def get_latest_question(self, page):
        """Returns the text of the most recent bot bubble (the active question)."""
        bubbles = self._bot_bubbles(page)
        count = bubbles.count()
        if count == 0:
            return None
        last = bubbles.nth(count - 1)
        try:
            text = (last.inner_text() or "").strip()
        except Exception:
            text = ""
        return " ".join(text.split()) if text else None

    def wait_for_new_question(self, page, previous_count, timeout=None):
        """
        Waits until a NEW bot bubble appears (count increases beyond
        previous_count). Returns True if a new question arrived.
        """
        timeout = timeout or self.NEW_Q_TIMEOUT
        deadline = time.time() + (timeout / 1000.0)
        while time.time() < deadline:
            if self._bot_bubbles(page).count() > previous_count:
                # Small settle so React finishes rendering the text/options.
                page.wait_for_timeout(400)
                return True
            if self.is_finished(page):
                return False
            page.wait_for_timeout(300)
        return False

    # ---------------------------------------------------------------
    # ANSWER WIDGET DETECTION
    # ---------------------------------------------------------------
    # JS that derives a radio/checkbox's visible label text, wherever it lives
    # (associated <label for>, enclosing <label>, or parent container text).
    _LABEL_JS = """el => {
        if (el.id) {
            const l = document.querySelector('label[for="' + el.id + '"]');
            if (l && l.innerText.trim()) return l.innerText;
        }
        const lab = el.closest('label');
        if (lab && lab.innerText.trim()) return lab.innerText;
        const p = el.parentElement;
        return p ? p.innerText : '';
    }"""

    def _choice_options(self, drawer, input_type):
        """
        Returns a list of option dicts for radios/checkboxes INSIDE the drawer:
        {'text': <label>, 'id': <input id>, 'input': <Locator to the input>}.
        Works on the real <input> elements (which may be visually hidden).
        """
        inputs = drawer.locator(f"input[type='{input_type}']")
        out = []
        for i in range(inputs.count()):
            inp = inputs.nth(i)
            try:
                text = inp.evaluate(self._LABEL_JS) or ""
            except Exception:
                text = ""
            out.append({
                "text": " ".join(text.split()),
                "id": inp.get_attribute("id") or "",
                "input": inp,
            })
        return out

    def detect_answer_mode(self, page):
        """
        Inspects the drawer's input area and returns (mode, payload).
        mode ∈ {'single_choice', 'multi_choice', 'text', 'unknown'}
        payload: list[option-dict] for choices, a Locator for text, else None.
        """
        drawer = page.locator(self.DRAWER).first
        scope = drawer if drawer.count() > 0 else page

        checks = self._choice_options(scope, "checkbox")
        if checks:
            return "multi_choice", checks

        radios = self._choice_options(scope, "radio")
        if radios:
            return "single_choice", radios

        text = page.locator(self.TEXT_INPUT)
        if text.count() > 0 and text.first.is_visible():
            return "text", text

        return "unknown", None

    @staticmethod
    def _is_checked(inp):
        try:
            return inp.is_checked()
        except Exception:
            try:
                return bool(inp.evaluate("el => el.checked"))
            except Exception:
                return False

    # ---------------------------------------------------------------
    # PROFILE → SUGGESTED ANSWER
    # ---------------------------------------------------------------
    def suggest_answer(self, question, mode, option_texts):
        """
        Maps the question text to a value from resume_data.json.
        Returns (answer, confident): `confident` is True only when the answer
        came from a real profile-based intent match (not a blind default).
        Unattended mode uses `confident` to decide whether to submit or skip.
        """
        q = (question or "").lower()
        p = self.profile
        is_choice = mode in ("single_choice", "multi_choice")

        def num(v, default):
            try:
                return str(int(float(str(v).split()[0])))
            except Exception:
                return str(v or default)

        # City SELECTION — pick a city from a list ("select the city / which
        # city / preferred location"). Needs a real location value.
        city_selection = any(k in q for k in (
            "which city", "select the city", "select city", "choose your",
            "choose the", "preferred location", "preferred city",
            "which location", "current city", "base location", "job location",
        ))
        # Residency / relocation YES-NO — "Are you residing in X / willing to
        # relocate to X?" → always Yes (open to any location). NOT a city pick.
        residency_q = (not city_selection) and any(k in q for k in (
            "reside", "residing", "relocat", "willing to move",
            "currently living", "currently based", "comfortable relocating",
        ))

        langs = [str(l).lower() for l in (p.get("languages") or [])]
        has_skill = any(str(sk).lower() in q for sk in p.get("skills", []))
        # "how many years..." asks for a COUNT; "do you have experience with X"
        # is a yes/no skill-possession question.
        asks_count = ("how many" in q) or ("years" in q) or ("no. of year" in q)

        # ---- Value pick based on intent ----
        # NOTE: to answer a NEW kind of question you must add BOTH a key in
        # resume_data.json AND a rule here that maps the question wording to it.
        matched_intent = True
        if "notice" in q:
            guess = str(p.get("notice_period", "Immediate"))
        # Graduation YEAR — must come BEFORE the generic "year"→experience rule.
        elif "graduat" in q and ("year" in q or "pass" in q):
            guess = str(p.get("graduation_year") or "")
        # Degree / qualification name.
        elif "highest" in q and any(k in q for k in ("education", "qualif", "degree")):
            guess = str(p.get("highest_education") or "")
        elif any(k in q for k in ("degree", "qualification", "b.tech", "btech",
                                  "b.e.", "graduation degree", "under grad", "ug degree")):
            guess = str(p.get("ug_degree") or p.get("highest_education") or "")
        # Date of birth.
        elif any(k in q for k in ("date of birth", "dob", "birth date", "born")):
            guess = str(p.get("date_of_birth") or "")
        # Skill-possession (Yes/No): "Do you have experience with <skill>?" —
        # only when it's NOT asking for a number of years.
        elif has_skill and not asks_count:
            guess = "Yes"
        elif any(k in q for k in ("year", "experience", "exp ")):
            # "How many years of experience in <X>?" — claim total experience
            # ONLY when <X> is a skill you actually have, OR it's a general/
            # total-experience question. If it asks about a skill you DON'T
            # have, don't guess a number — flag it so the whole job is skipped
            # (you shouldn't apply to jobs needing skills you lack).
            generic_exp = any(g in q for g in (
                "total", "overall", "this field", "relevant",
                "work experience", "professional",
            ))
            asks_about_specific = (" in " in q) or (" with " in q)
            if asks_about_specific and not has_skill and not generic_exp:
                guess = ""              # unknown skill → no number
                matched_intent = False  # → not confident → job flagged & skipped
            else:
                guess = num(p.get("experience_years", 3), 3)
        elif any(k in q for k in ("rate", "scale of", "out of 10", "score")):
            # "Rate your communication skills on the scale of 10" etc.
            if "communicat" in q and p.get("communication_skills_scale_of_10"):
                guess = str(p.get("communication_skills_scale_of_10"))
            else:
                guess = str(p.get("default_rating", "8"))
        elif "current" in q and ("ctc" in q or "salary" in q or "package" in q):
            guess = str(p.get("current_ctc", "Negotiable"))
        elif any(k in q for k in ("expected", "ctc", "salary", "package", "lpa")):
            guess = str(p.get("expected_ctc", "Negotiable"))
        elif city_selection:
            guess = str(p.get("location") or p.get("current_location") or "Noida")
        elif residency_q:
            # Residing here OR willing to relocate → always Yes.
            guess = "Yes"
        # Language comfort ("Are you comfortable with English?").
        elif any(lang in q for lang in langs) or ("english" in q and "english" in langs):
            guess = "Yes"
        elif "name" in q:
            guess = str(p.get("full_name", ""))
        elif "email" in q:
            guess = str(p.get("email", ""))
        elif any(sk.lower() in q for sk in p.get("skills", [])):
            guess = "Yes"
        else:
            # No profile intent matched → a blind default (low confidence).
            guess = "Yes" if is_choice else ""
            matched_intent = False

        # A rule matched but the profile value is empty → not usable.
        if matched_intent and not str(guess).strip():
            matched_intent = False

        # ---- For choice widgets, snap the guess to a real option ----
        if is_choice and option_texts:
            # City-selection questions get NCR/region-aware matching.
            if city_selection:
                loc_match = self._match_location_option(option_texts)
                if loc_match:
                    return loc_match, True
            # Numeric answers (experience/years) → match by RANGE, so "6" picks
            # "4-6" and never "12-14" (naive substring matched 14→'…4').
            if re.fullmatch(r"\d+(?:\.\d+)?", str(guess).strip()):
                rng = self._match_numeric_range(guess, option_texts)
                if rng is not None:
                    return rng, matched_intent
            match = self._match_option(guess, option_texts)
            if match is not None:
                return match, matched_intent
            # No real option matched → first *real* option is a blind guess.
            first_real = self._first_real_option(option_texts)
            return (first_real or guess), False

        return guess, (matched_intent and bool(str(guess).strip()))

    @staticmethod
    def _match_numeric_range(value, option_texts):
        """
        Matches a number to a range/threshold option:
          "6" → "4-6" or "6-8"; "6" → "5+"/"more than 5"; "6" → "less than 8".
        Returns the matching option text, or None.
        """
        try:
            target = float(str(value).strip())
        except (TypeError, ValueError):
            return None
        for opt in option_texts:
            low = opt.lower()
            nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", opt)]
            if not nums:
                continue
            if len(nums) >= 2:                       # a range "a-b"
                lo, hi = nums[0], nums[1]
                if lo <= target <= hi:
                    return opt
            else:                                    # a single-number threshold
                n = nums[0]
                if any(w in low for w in ("+", "more", "above", "greater", "least", "min")):
                    if target >= n:
                        return opt
                elif any(w in low for w in ("less", "below", "under", "max", "upto", "up to")):
                    if target <= n:
                        return opt
                elif target == n:
                    return opt
        return None

    @staticmethod
    def _first_real_option(option_texts):
        """First option that isn't a 'skip this question' style opt-out."""
        for opt in option_texts:
            if "skip" not in opt.strip().lower():
                return opt
        return option_texts[0] if option_texts else None

    def _match_location_option(self, option_texts):
        """
        Matches the profile location to an option, with NCR/region awareness
        (e.g. profile 'Noida' → option 'Delhi / NCR').
        """
        loc = str(self.profile.get("location")
                  or self.profile.get("current_location") or "").strip().lower()
        if not loc:
            return None
        # Direct/containment match first.
        direct = self._match_option(loc, option_texts)
        if direct:
            return direct
        # Delhi-NCR grouping.
        ncr_cities = {
            "noida", "greater noida", "gurgaon", "gurugram",
            "ghaziabad", "faridabad", "delhi", "new delhi", "ncr",
        }
        if loc in ncr_cities or "ncr" in loc or "delhi" in loc:
            for opt in option_texts:
                if "ncr" in opt.lower():
                    return opt
            for opt in option_texts:
                o = opt.lower()
                if "delhi" in o and "skip" not in o:
                    return opt
        return None

    @staticmethod
    def _match_option(value, option_texts):
        """Fuzzy-ish match of a value to one of the visible option labels."""
        v = (value or "").strip().lower()
        if not v:
            return None
        # exact
        for opt in option_texts:
            if opt.strip().lower() == v:
                return opt
        # containment either direction
        for opt in option_texts:
            o = opt.strip().lower()
            if o and (v in o or o in v):
                return opt
        # yes/no shortcuts
        if v in ("yes", "y", "true"):
            for opt in option_texts:
                if opt.strip().lower() in ("yes", "y"):
                    return opt
        if v in ("no", "n", "false"):
            for opt in option_texts:
                if opt.strip().lower() in ("no", "n"):
                    return opt
        return None

    # ---------------------------------------------------------------
    # ANSWER APPLICATION
    # ---------------------------------------------------------------
    def fill_text(self, page, value):
        text = page.locator(self.TEXT_INPUT).first
        text.click()
        # contenteditable divs don't respond to .fill() reliably → select+type.
        try:
            text.fill("")
        except Exception:
            pass
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        text.type(str(value), delay=25)
        return True

    def _select_one(self, page, opt):
        """
        Selects a single radio/checkbox robustly and verifies it stuck.
        Tries: label click → force input click → JS click+change event.
        """
        inp = opt["input"]
        iid = opt.get("id") or ""

        # 1) Click the associated <label> (inputs are often visually hidden).
        if iid:
            lab = page.locator(f"label[for='{iid}']").first
            if lab.count() > 0:
                try:
                    lab.scroll_into_view_if_needed(timeout=1500)
                    lab.click(force=True, timeout=2500)
                except Exception:
                    pass
        if self._is_checked(inp):
            return True

        # 2) Force-click the input element itself.
        try:
            inp.scroll_into_view_if_needed(timeout=1500)
            inp.click(force=True, timeout=2500)
        except Exception:
            pass
        if self._is_checked(inp):
            return True

        # 3) Last resort: JS click + fire a change event so React updates state.
        try:
            inp.evaluate(
                "el => { el.click(); "
                "el.dispatchEvent(new Event('change', {bubbles: true})); }"
            )
        except Exception:
            pass
        return self._is_checked(inp)

    def select_option(self, page, options, value, multi=False):
        """Selects the option(s) matching `value`; returns True only if verified."""
        texts = [o["text"] for o in options]
        wants = ([value] if not multi
                 else [v.strip() for v in str(value).split(",") if v.strip()])

        ok = False
        for want in wants:
            match = self._match_option(want, texts)
            if match is None:
                print(f"      ✗ No option matched {want!r} in {texts}")
                continue
            idx = texts.index(match)
            if self._select_one(page, options[idx]):
                print(f"      ✓ Selected: {match!r}")
                ok = True
            else:
                print(f"      ✗ Click did not register for: {match!r}")
        return ok

    def click_send(self, page):
        btn = page.locator(self.SEND_BTN).first
        if btn.count() > 0 and btn.is_visible():
            btn.click()
            page.wait_for_timeout(600)
            return True
        # Fallback: many chatbots accept Enter to advance.
        try:
            page.keyboard.press("Enter")
            page.wait_for_timeout(600)
            return True
        except Exception:
            return False

    # Success markers must be SPECIFIC and matched INSIDE the drawer only.
    # (Page-wide / loose markers like "thank you" caused false positives that
    #  made the questionnaire exit before reading the first question.)
    FINISH_MARKERS = (
        "application has been sent",
        "application has been submitted",
        "application sent successfully",
        "successfully applied",
        "your application has been",
        "you have successfully applied",
    )

    def is_finished(self, page):
        """
        True only if the DRAWER is gone, or a specific success message
        appears INSIDE the drawer. Scoping to the drawer avoids matching
        stray page text (footers, toasts, greetings).
        """
        drawer = page.locator(self.DRAWER).first
        try:
            if drawer.count() == 0:
                return True  # drawer closed → flow completed/closed
        except Exception:
            return False

        try:
            drawer_text = (drawer.inner_text() or "").lower()
        except Exception:
            drawer_text = ""

        return any(marker in drawer_text for marker in self.FINISH_MARKERS)

    # Page-level success markers for a DIRECT apply (no chatbot): after
    # clicking Apply, Naukri shows a toast / status like these.
    APPLY_SUCCESS_MARKERS = (
        "successfully applied",
        "you have successfully applied",
        "application has been sent",
        "application sent successfully",
        "your application has been",
        "you have applied",
        "applied to this job",
        "successfully submitted your application",
    )

    def detect_apply_success(self, page):
        """
        True if the page shows a direct-apply success (no chatbot drawer):
        a specific success message, or a visible 'Applied' status chip.
        """
        # 1) Specific success text anywhere on the page.
        try:
            body_text = (page.locator("body").inner_text() or "").lower()
        except Exception:
            body_text = ""
        if any(marker in body_text for marker in self.APPLY_SUCCESS_MARKERS):
            return True

        # 2) An 'Applied' status chip that appears after a successful apply.
        try:
            chip = page.locator(
                "span:has-text('Applied'), div.styles_applied__, "
                "div[class*='applied']:has-text('Applied')"
            ).first
            if chip.count() > 0 and chip.is_visible():
                return True
        except Exception:
            pass

        return False

    # Page-level ERROR markers: Naukri sometimes shows an apply failure toast.
    # These mean the application did NOT go through → keep the job pending.
    APPLY_ERROR_MARKERS = (
        "error applying",
        "there was an error",
        "something went wrong",
        "please try again",
        "unable to apply",
        "could not apply",
        "failed to apply",
        "apply failed",
        "error occurred while applying",
    )

    def detect_apply_error(self, page):
        """True if the page shows an apply-error message (application failed)."""
        try:
            body_text = (page.locator("body").inner_text() or "").lower()
        except Exception:
            return False
        return any(marker in body_text for marker in self.APPLY_ERROR_MARKERS)

    # Terminal bot bubbles that are NOT questions — they signal the chatbot
    # has finished asking and the application is ready to submit.
    CLOSING_MARKERS = (
        "thank you for your response",
        "thank you for your responses",
        "thanks for your response",
        "thank you for applying",
        "thank you for your interest",
        "your responses have been recorded",
        "we have received your responses",
    )

    def _is_closing_message(self, text):
        t = (text or "").lower()
        return any(m in t for m in self.CLOSING_MARKERS)

    def _apply_answer(self, page, mode, options, answer):
        """Applies an answer to whatever widget the current question uses."""
        if mode == "text":
            return self.fill_text(page, answer)
        if mode == "single_choice":
            return self.select_option(page, options, answer, multi=False)
        if mode == "multi_choice":
            return self.select_option(page, options, answer, multi=True)
        try:
            return self.fill_text(page, answer)
        except Exception:
            return False

    # ---------------------------------------------------------------
    # PHASE 1 — AUTO-ANSWER (no per-question prompts)
    # ---------------------------------------------------------------
    def run_questionnaire(self, page):
        """
        Auto-answers every chatbot question (no per-question approval),
        printing each Q → A. Then shows a summary and lets the user edit
        any answer, and finally reports readiness to submit.

        Returns (status, qa_dict).
        status ∈ {'applied', 'user_rejected', 'incomplete'}
        """
        qa_log = []          # ordered: [{'q','a','mode','options'}]
        asked = set()

        for _ in range(self.MAX_QUESTIONS):
            if self.is_finished(page):
                break

            question = self.get_latest_question(page)
            if not question:
                page.wait_for_timeout(800)
                question = self.get_latest_question(page)
            if not question:
                print("   ⚠️ Drawer open but could not extract question text.")
                self._dump_debug(page, "empty_question")
                break

            # Closing bubble → all questions answered.
            if self._is_closing_message(question):
                print(f"   ✅ Closing message: {question!r}")
                break

            if question in asked:
                if not self.wait_for_new_question(page, self._bot_bubbles(page).count()):
                    break
                continue
            asked.add(question)

            mode, options = self.detect_answer_mode(page)
            option_texts = ([o["text"] for o in options]
                            if mode in ("single_choice", "multi_choice") else [])
            answer, confident = self.suggest_answer(question, mode, option_texts)

            # -------- Auto-apply (no prompt) --------
            prev_count = self._bot_bubbles(page).count()
            applied_ok = self._apply_answer(page, mode, options, answer)

            # Unattended "easy-only" policy: a question is HARD if we couldn't
            # apply the answer OR we weren't confident about it. Hard questions
            # → don't submit; flag the whole job for manual review.
            if not self.interactive and (not applied_ok or not confident):
                reason = ("could not fill widget" if not applied_ok
                          else "no confident profile-based answer")
                print(f"   🟡 Hard question ({reason}) → flagging job for manual review.")
                print(f"      ❓ {question}")
                self._dump_debug(page, "needs_review")
                qa_log.append({"q": question, "a": "[needs manual review]",
                               "mode": mode, "options": option_texts})
                return "needs_review", {i["q"]: i["a"] for i in qa_log}

            # Interactive mode: only stop to ask if the answer couldn't be applied.
            if not applied_ok and self.interactive:
                print(f"   ⚠️ Could not auto-answer: {question!r}")
                self._dump_debug(page, "answer_failed")
                manual = input(
                    "   ⏸️  Answer it in the browser, then press Enter "
                    "(or type the value to use): "
                ).strip()
                if manual:
                    answer = manual
                    self._apply_answer(page, mode, options, answer)
                else:
                    answer = "[answered manually in browser]"

            # Print the Q → A as it happens.
            print(f"   ❓ {question}")
            print(f"   👉 {answer}\n")

            qa_log.append({"q": question, "a": answer, "mode": mode,
                           "options": option_texts})

            self.click_send(page)
            got_next = self.wait_for_new_question(page, prev_count)
            if not got_next and self.is_finished(page):
                break
            if not got_next:
                break  # likely the last question

        if not qa_log:
            return "incomplete", {}

        # -------- PHASE 2 — review + optional edits (interactive only) --------
        if self.interactive:
            status = self._review_and_edit(page, qa_log)
        else:
            print("   🤖 Unattended mode — auto-submitting without review.")
            status = "applied"
        qa_dict = {item["q"]: item["a"] for item in qa_log}
        return status, qa_dict

    # ---------------------------------------------------------------
    # PHASE 2 — BATCH REVIEW & EDIT
    # ---------------------------------------------------------------
    def _print_summary(self, qa_log):
        print("\n================= 📝 REVIEW YOUR ANSWERS =================")
        for i, item in enumerate(qa_log, 1):
            print(f"   {i}. Q: {item['q']}")
            print(f"      A: {item['a']}")
        print("==========================================================")

    def _review_and_edit(self, page, qa_log):
        """
        Shows all Q&A and lets the user edit any before submitting.
        Returns 'applied' (proceed to submit) or 'user_rejected'.
        """
        while True:
            self._print_summary(qa_log)
            resp = input(
                "   ✅ All correct? Press ENTER to SUBMIT, "
                "or enter question number(s) to edit (e.g. 1,3), "
                "or 'n' to abort: "
            ).strip().lower()

            if resp == "":
                return "applied"
            if resp in ("n", "no", "abort"):
                return "user_rejected"

            # Parse the numbers to edit.
            try:
                targets = [int(x) for x in resp.replace(" ", "").split(",") if x]
            except ValueError:
                print("   ⚠️ Please enter numbers like: 1,3")
                continue

            for n in targets:
                if not (1 <= n <= len(qa_log)):
                    print(f"   ⚠️ No question #{n}.")
                    continue
                item = qa_log[n - 1]
                print(f"\n   ✏️  Editing #{n}: {item['q']}")
                if item["options"]:
                    print(f"       Options: {item['options']}")
                new_val = input("       New answer: ").strip()
                if not new_val:
                    print("       (unchanged)")
                    continue
                if self._edit_answer(page, qa_log, n - 1, new_val):
                    item["a"] = new_val
                    print(f"       ✓ Updated to: {new_val!r}")
                else:
                    print("       ⚠️ This chatbot didn't accept an in-place edit.")

    def _edit_answer(self, page, qa_log, index, new_val):
        """
        Best-effort edit of an already-sent answer: re-click the matching
        user-answer bubble to re-open its input, then apply the new value.
        Naukri chatbots vary — returns False if editing isn't supported.
        """
        user_bubbles = page.locator(
            ".chatbot_Drawer li.userItem, [class*='chatbot_Drawer'] li.userItem"
        )
        if index >= user_bubbles.count():
            return False
        try:
            user_bubbles.nth(index).click()
            page.wait_for_timeout(800)
        except Exception:
            return False

        # If clicking re-exposed an input widget, apply the new value + resend.
        mode, options = self.detect_answer_mode(page)
        if mode == "unknown":
            return False
        if self._apply_answer(page, mode, options, new_val):
            self.click_send(page)
            page.wait_for_timeout(800)
            return True
        return False

    # ---------------------------------------------------------------
    # FALLBACK: plain (non-chatbot) form scan  — kept from original flow
    # ---------------------------------------------------------------
    def fill_plain_form(self, page):
        qa = {}
        fields = page.locator("input[type='text'], select, textarea")
        for i in range(fields.count()):
            field = fields.nth(i)
            if not field.is_visible():
                continue
            id_attr = field.get_attribute("id") or ""
            placeholder = field.get_attribute("placeholder") or ""
            label_text = ""
            if id_attr:
                lab = page.locator(f"label[for='{id_attr}']").first
                if lab.count() > 0:
                    label_text = lab.inner_text().strip()
            key = label_text or placeholder or (field.get_attribute("name") or f"Field {i+1}")
            answer, _confident = self.suggest_answer(key, "text", [])
            if answer:
                try:
                    field.fill(str(answer))
                    qa[key] = answer
                except Exception:
                    pass
        return qa

    # ---------------------------------------------------------------
    # PER-JOB ORCHESTRATION
    # ---------------------------------------------------------------
    def apply_job_interactively(self, job_meta):
        job_link = job_meta["link"]
        apply_page = self.page.context.new_page()

        try:
            apply_page.goto(job_link, wait_until="domcontentloaded", timeout=45000)
            apply_page.wait_for_timeout(2500)

            # Already applied?
            already = apply_page.locator(
                "span:has-text('Applied'), button:has-text('Applied')"
            ).first
            if already.count() > 0 and already.is_visible():
                print("   ℹ️ Already Applied (skipping).")
                apply_page.close()
                return "already_applied", {}

            # External redirect: "Apply on company site" → defer to the manual
            # queue instead of trying to auto-apply. Checked BEFORE the normal
            # Apply button, because that text also contains the word "Apply".
            company_site = apply_page.locator(
                "button:has-text('company site'), a:has-text('company site'), "
                ".company-site-button"
            ).first
            if company_site.count() > 0 and company_site.is_visible():
                print("   🌐 'Apply on company site' detected → apply_manually queue.")
                apply_page.close()
                return "apply_manually", {}

            # Find & click Apply
            apply_btn = None
            for sel in (
                "button:has-text('Apply')",
                "a:has-text('Apply')",
                "button.apply-button",
                "button[class*='apply']",
                "#apply-button",
            ):
                btn = apply_page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    apply_btn = btn
                    break

            if not apply_btn:
                print("   ❌ Apply button not found / external redirect required.")
                apply_page.close()
                return "skipped", {}

            apply_btn.click()
            apply_page.wait_for_timeout(2500)

            # --- Apply error shown? Keep the job pending for a retry. ---
            if self.detect_apply_error(apply_page):
                print("   ⚠️ Page reported an apply error → keeping job pending.")
                apply_page.close()
                return "error", {}

            # --- Direct apply (no chatbot): success shown immediately? ---
            if self.detect_apply_success(apply_page):
                print("   ✅ Direct apply succeeded (no chatbot) → applied_jobs.")
                apply_page.close()
                return "applied", {}

            # --- Detect the chatbot drawer ---
            if self.wait_for_drawer(apply_page):
                print("   🗂️  Chatbot drawer detected — auto-answering questions.")
                # Phase 1 auto-answers; Phase 2 (inside) reviews + edits.
                status, qa = self.run_questionnaire(apply_page)

                if status == "user_rejected":
                    print("   🚫 Aborted by user during review.")
                    apply_page.close()
                    return "user_rejected", qa

                if status == "needs_review":
                    print("   🟡 Skipped (needs manual review) — NOT submitted.")
                    apply_page.close()
                    return "needs_review", qa

                # Review already confirmed → submit automatically.
                print(f"\n🚀 Submitting: '{job_meta['title']}' @ '{job_meta['company']}'")
                self._final_submit(apply_page)
                apply_page.wait_for_timeout(1500)
                if self.detect_apply_error(apply_page):
                    print("   ⚠️ Apply error after submit → keeping job pending.")
                    apply_page.close()
                    return "error", qa
                apply_page.close()
                return "applied", qa

            # --- No drawer → maybe direct apply succeeded, else plain form ---
            print("   🟢 No chatbot drawer detected within timeout.")
            if self.detect_apply_error(apply_page):
                print("   ⚠️ Page reported an apply error → keeping job pending.")
                apply_page.close()
                return "error", {}
            if self.detect_apply_success(apply_page):
                print("   ✅ Direct apply succeeded (no chatbot) → applied_jobs.")
                apply_page.close()
                return "applied", {}

            self._dump_debug(apply_page, "no_drawer")
            print("   ↪️  Checking for a plain form / direct apply.")
            qa = self.fill_plain_form(apply_page)
            if qa:
                for q, a in qa.items():
                    print(f"   ❓ {q}  ->  👉 {a}")

            print(f"\n📢 Ready to submit: '{job_meta['title']}' @ '{job_meta['company']}'")
            if self.interactive:
                if input("👉 SUBMIT this application? (y/n): ").strip().lower() != "y":
                    apply_page.close()
                    return "user_rejected", qa
            else:
                print("   🤖 Unattended mode — auto-submitting.")

            self._final_submit(apply_page)
            apply_page.wait_for_timeout(1500)
            if self.detect_apply_error(apply_page):
                print("   ⚠️ Apply error after submit → keeping job pending.")
                apply_page.close()
                return "error", qa
            apply_page.close()
            return "applied", qa

        except Exception as e:
            print(f"   💥 Playwright error: {e}")
            try:
                apply_page.close()
            except Exception:
                pass
            return "failed", {}

    def _final_submit(self, page):
        for sel in (
            "button:has-text('Submit')",
            "button:has-text('Save and Apply')",
            "button:has-text('Apply')",
            "button:has-text('Continue')",
            self.SEND_BTN,
            "input[type='submit']",
        ):
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                try:
                    btn.click()
                    page.wait_for_timeout(2500)
                    break
                except Exception:
                    continue
        print("   🚀 Submit action triggered.")


# ==========================================
# 🚀 SYSTEM INITIATOR
# ==========================================
def run_interactive_apply(interactive=True):
    """
    Applies to all pending jobs. When interactive=False it runs fully
    unattended (no prompts, auto-submit) and RETURNS a list of per-job
    result dicts suitable for an email report.
    """
    mode = "INTERACTIVE" if interactive else "UNATTENDED"
    print(f"🤖 Starting Naukri Auto-Apply Engine ({mode})...")

    results = []  # for the email report

    user_profile = get_resume_data()
    if not user_profile:
        print("❌ Critical: No active user profile data found.")
        return results

    _, db, _ = _get_db_objects()
    pending_collection = db["pending_jobs"]
    applied_collection = db["applied_jobs"]
    manual_collection = db["apply_manually"]  # jobs needing manual company-site apply

    try:
        db_applied_links = [d["link"] for d in applied_collection.find({}, {"link": 1, "_id": 0})]
    except Exception:
        db_applied_links = []

    local_applied_links = [j["link"] for j in load_local_applied_jobs()]
    all_applied_links = list(set(db_applied_links + local_applied_links))

    pending_jobs = list(pending_collection.find({
        "status": "pending",
        "link": {"$nin": all_applied_links},
    }))

    if not pending_jobs:
        print("😴 No pending jobs to apply. Run scraper first!")
        return results

    # Location filter (defense-in-depth): never apply to a job outside the
    # preferred locations — even if older/unfiltered jobs are still in the DB.
    preferred_locs = [l for l in _get_locations(user_profile) if l]
    if preferred_locs:
        keep, drop = [], []
        for j in pending_jobs:
            (keep if _matches_location(j.get("location"), preferred_locs) else drop).append(j)
        for j in drop:
            pending_collection.update_one(
                {"_id": j["_id"]}, {"$set": {"status": "location_mismatch"}}
            )
        if drop:
            print(f"🧭 Location filter: skipped {len(drop)} out-of-location jobs "
                  f"(preferred: {preferred_locs}).")
        pending_jobs = keep

    if not pending_jobs:
        print("😴 No pending jobs match your preferred locations.")
        return results

    print(f"📋 Found {len(pending_jobs)} pending jobs to process.")

    with sync_playwright() as p:
        browser = launch_browser(p)
        context = new_context(browser)

        if os.path.exists("cookies.json"):
            with open("cookies.json", "r") as f:
                context.add_cookies(json.load(f))
        else:
            print("⚠️ Warning: cookies.json missing! Manual login may be required.")

        page = context.new_page()
        applier = NaukriInteractiveApplier(page, user_profile, interactive=interactive)

        for idx, job in enumerate(pending_jobs, 1):
            print(f"\n==================== [JOB {idx}/{len(pending_jobs)}] ====================")
            print(f"💼 Role    : {job.get('title')}")
            print(f"🏢 Company : {job.get('company')}")
            print(f"📍 Location: {job.get('location')}")
            print(f"💰 Salary  : {job.get('salary', 'Not Disclosed')}")
            print(f"🔗 Link    : {job.get('link')}")

            status, answers_logged = applier.apply_job_interactively(job)

            # Record the outcome for the email report.
            results.append({
                "title": job.get("title"),
                "company": job.get("company"),
                "location": job.get("location"),
                "link": job.get("link"),
                "status": status,
                "questions_and_answers": answers_logged or {},
            })

            if status == "applied":
                applied_data = {
                    "job_id": str(job["_id"]),
                    "title": job.get("title"),
                    "company": job.get("company"),
                    "location": job.get("location"),
                    "salary": job.get("salary"),
                    "rating": job.get("rating"),
                    "link": job.get("link"),
                    "fingerprint": job_fingerprint(job),
                    "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "questions_and_answers": answers_logged,
                }
                # Save to 'applied_jobs' FIRST, then remove from 'pending_jobs'.
                # Only delete once the record is confirmed present, so a DB
                # failure can never drop the job from both collections.
                saved_to_db = False
                if applied_job_exists(applied_collection, applied_data):
                    saved_to_db = True
                    print("   ↩️ Already in 'applied_jobs' (link/details match) — not re-inserting.")
                else:
                    try:
                        applied_collection.insert_one(applied_data.copy())
                        saved_to_db = True
                        print("   📥 Saved to MongoDB collection 'applied_jobs'.")
                    except Exception as db_err:
                        print(f"   ⚠️ MongoDB save failed: {db_err}")

                if saved_to_db:
                    pending_collection.delete_one({"_id": job["_id"]})
                    print("   🗑️  Removed from 'pending_jobs'.")
                else:
                    # Keep it in pending (mark applied) so the local JSON + DB
                    # can be reconciled later without losing the record.
                    pending_collection.update_one(
                        {"_id": job["_id"]}, {"$set": {"status": "applied"}}
                    )
                    print("   ⚠️ Kept in 'pending_jobs' (marked applied) since DB save failed.")

                applied_data.pop("_id", None)
                save_local_applied_job(applied_data)

            elif status == "user_rejected":
                pending_collection.update_one(
                    {"_id": job["_id"]}, {"$set": {"status": "skipped_by_user"}}
                )

            elif status == "apply_manually":
                # "Apply on company site" → move to apply_manually, drop from pending.
                manual_data = {
                    "job_id": str(job["_id"]),
                    "title": job.get("title"),
                    "company": job.get("company"),
                    "location": job.get("location"),
                    "salary": job.get("salary"),
                    "rating": job.get("rating"),
                    "link": job.get("link"),
                    "fingerprint": job_fingerprint(job),
                    "flagged_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "status": "apply_manually",
                    "reason": "Apply on company site (external redirect)",
                }
                moved = False
                if applied_job_exists(manual_collection, manual_data):
                    moved = True
                    print("   ↩️ Already in 'apply_manually' — not re-inserting.")
                else:
                    try:
                        manual_collection.insert_one(manual_data.copy())
                        moved = True
                        print("   🌐 Saved to MongoDB collection 'apply_manually'.")
                    except Exception as db_err:
                        print(f"   ⚠️ MongoDB save failed: {db_err}")

                if moved:
                    pending_collection.delete_one({"_id": job["_id"]})
                    print("   🗑️  Removed from 'pending_jobs'.")
                else:
                    pending_collection.update_one(
                        {"_id": job["_id"]}, {"$set": {"status": "apply_manually"}}
                    )
                    print("   ⚠️ Kept in 'pending_jobs' since DB save failed.")

            elif status == "already_applied":
                already_data = {
                    "job_id": str(job["_id"]),
                    "title": job.get("title"),
                    "company": job.get("company"),
                    "location": job.get("location"),
                    "salary": job.get("salary"),
                    "rating": job.get("rating"),
                    "link": job.get("link"),
                    "fingerprint": job_fingerprint(job),
                    "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "status": "already_applied",
                    "questions_and_answers": {},
                }
                # Save to 'applied_jobs' FIRST, then remove from 'pending_jobs'.
                saved_to_db = False
                if applied_job_exists(applied_collection, already_data):
                    saved_to_db = True
                    print("   ↩️ Already in 'applied_jobs' (link/details match) — not re-inserting.")
                else:
                    try:
                        applied_collection.insert_one(already_data.copy())
                        saved_to_db = True
                        print("   📥 Saved to MongoDB collection 'applied_jobs'.")
                    except Exception as db_err:
                        print(f"   ⚠️ MongoDB save failed: {db_err}")

                if saved_to_db:
                    pending_collection.delete_one({"_id": job["_id"]})
                    print("   🗑️  Removed from 'pending_jobs'.")
                else:
                    pending_collection.update_one(
                        {"_id": job["_id"]}, {"$set": {"status": "already_applied"}}
                    )
                    print("   ⚠️ Kept in 'pending_jobs' since DB save failed.")

                already_data.pop("_id", None)
                save_local_applied_job(already_data)

            elif status == "error":
                # Apply failed on the site → keep it pending so it's retried.
                pending_collection.update_one(
                    {"_id": job["_id"]}, {"$set": {"status": "pending"}}
                )
                print("   🔁 Kept in 'pending_jobs' (status=pending) for retry.")

            elif status == "needs_review":
                # Hard questions in unattended mode → left for the user to do
                # manually. Marked so it won't be auto-retried blindly.
                pending_collection.update_one(
                    {"_id": job["_id"]}, {"$set": {"status": "needs_review"}}
                )
                print("   🟡 Marked 'needs_review' in 'pending_jobs'.")

            else:
                pending_collection.update_one(
                    {"_id": job["_id"]}, {"$set": {"status": status}}
                )

            time.sleep(1)

        print("\n🎉 Applying session completed!")
        browser.close()

    return results


if __name__ == "__main__":
    run_interactive_apply()
