"""Verifiers: decide whether a tier's answer can be accepted or must escalate.

Everything here is a pure function of the prompt and the model output. Nothing
looks at a gold answer, so the same code runs in the gateway and in the offline
replay (eval/replay.py).

Honest scope, from the dev-split replay (n=75, in-sample):
  * format_rules catches many of the small model's failures to follow an
    explicit output format (missing "ANSWER:" line, invalid JSON, ...).
  * It catches none of the medium model's errors: those are confident,
    well-formatted, factually wrong answers. Rules cannot see that.
  * answers_agree only decides short numeric / one-word answers; for free text
    it returns None (undecidable).
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Verdict:
    accept: bool
    reason: str = ""

    def __bool__(self) -> bool:  # lets callers write `if verdict:`
        return self.accept


# ---------------------------------------------------------------- helpers

_MD = re.compile(r"[*_`#>]+")
_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_ANS = re.compile(r"ANSWER:\s*(\S[^\n]*)", re.IGNORECASE)
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
_CJK_WANTED = re.compile(
    r"จีน|ญี่ปุ่น|เกาหลี|chinese|japanese|korean|mandarin|中文|日本語|한국어", re.IGNORECASE
)


def _clean(text: str) -> str:
    """NFKC plus plain spaces (models emit U+202F / U+00A0 / odd hyphens)."""
    text = unicodedata.normalize("NFKC", text)
    return text.replace(" ", " ").replace(" ", " ")


def prompt_text(messages) -> str:
    """All non-assistant text of a chat request, joined (handles list-style content)."""
    parts = []
    for m in messages or []:
        if m.get("role") == "assistant":
            continue
        c = m.get("content", "")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
        parts.append(str(c))
    return "\n".join(parts)


def last_number(text: str):
    """Last number in the text as a float, or None. Commas are thousands separators."""
    nums = _NUM.findall(_clean(text).replace(",", ""))
    return float(nums[-1]) if nums else None


def extract_answer(output: str) -> str:
    """The text after the last 'ANSWER:' marker, else the whole output. Markdown stripped."""
    text = _clean(output)
    match = None
    for match in _ANS.finditer(text):
        pass
    answer = _MD.sub("", match.group(1) if match else text).strip()
    return answer.rstrip(".!").strip()


def find_json(output: str):
    """First balanced {...} block in the text that parses as JSON, else None."""
    for start in (m.start() for m in re.finditer(r"\{", output)):
        depth = 0
        for end in range(start, len(output)):
            if output[end] == "{":
                depth += 1
            elif output[end] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(output[start:end + 1])
                    except ValueError:
                        break
    return None


# ------------------------------------------------------------ rule checks

def nonempty(messages, output: str) -> Verdict:
    """Phase 1 verifier: the model said something."""
    if output and output.strip():
        return Verdict(True, "ok")
    return Verdict(False, "empty")


def format_rules(prompt: str, output: str) -> Verdict:
    """Check that the output obeys format instructions found in the prompt."""
    out = (output or "").strip()
    if not out:
        return Verdict(False, "empty")

    if re.search(r"ANSWER:\s*<", prompt):  # prompt demands an 'ANSWER: ...' line
        if not _ANS.search(_clean(out)):
            return Verdict(False, "missing ANSWER line")
        wants_number = re.search(r"ANSWER:\s*<(?:ตัวเลข|number)", prompt, re.IGNORECASE)
        if wants_number and last_number(extract_answer(out)) is None:
            return Verdict(False, "ANSWER line has no number")
    elif re.search(r"final number|ตัวเลขสุดท้าย", prompt, re.IGNORECASE):
        if last_number(out.splitlines()[-1]) is None:
            return Verdict(False, "last line has no number")

    if re.search(r"\bJSON\b", prompt) and find_json(out) is None:
        return Verdict(False, "no valid JSON")

    if _CJK.search(out) and not _CJK.search(prompt) and not _CJK_WANTED.search(prompt):
        return Verdict(False, "unexpected CJK characters")

    return Verdict(True, "ok")


def format_verify(messages, output: str) -> Verdict:
    """Adapter with the cascade's verifier signature: (messages, text) -> Verdict."""
    return format_rules(prompt_text(messages), output)


# -------------------------------------------------------------- agreement

def answers_agree(output_a: str, output_b: str):
    """True / False when two answers can be compared, None when they cannot.

    Comparable: both short answers with numbers (compare the numbers), or both
    very short strings (compare after normalising). Longer free text returns
    None: string similarity was not reliable on this dataset.
    """
    a, b = extract_answer(output_a), extract_answer(output_b)
    na, nb = last_number(a), last_number(b)
    if na is not None and nb is not None and len(a) <= 40 and len(b) <= 40:
        return abs(na - nb) < 1e-6
    sa = re.sub(r"[^\w]", "", _clean(a).lower())
    sb = re.sub(r"[^\w]", "", _clean(b).lower())
    if sa and sb and len(sa) <= 20 and len(sb) <= 20:
        return sa == sb
    return None


VERIFIERS = {"nonempty": nonempty, "format": format_verify}
