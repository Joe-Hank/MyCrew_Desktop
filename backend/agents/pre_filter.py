"""Stage 0: Rule-based pre-filter — runs before any LLM call.

Three checks (in order):

1. **Length cap** — refuse messages > MAX_INPUT_CHARS. Cheap DoS guard
   + tokens-per-round protection.
2. **Injection regex** — refuse common prompt-injection prefixes
   ("ignore previous", "you are DAN", role-overwrite attempts). This
   is a best-effort heuristic; real injection arms races aren't won
   here, but we catch the lazy 90%.
3. **Sensitive-word mask** — pass-through with `*` replacement; never
   refuses (per user spec).

Output:
  - `PreFilterPass(masked_text)` — proceed to compliance gate
  - `PreFilterDeny(reason)`     — return polite refusal, skip LLM

All decisions are deterministic and recorded into `events` via the
caller (router.dispatch).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from agents.sensitive_words_loader import mask


MAX_INPUT_CHARS = 4000

# Prompt-injection / jailbreak patterns. Case-insensitive. Conservative:
# we'd rather let a slightly suspicious message through to the LLM gate
# than reject legit project requests that happen to use similar wording.
_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        # English overrides
        r"\bignore (all |the )?(previous|prior|above) (instructions?|prompts?|rules?)\b",
        r"\bdisregard (your|all|previous) (instructions?|system prompt)\b",
        r"\bsystem prompt[:\s]*",
        r"\byou are (now |actually )?(DAN|jailbroken|unrestricted)\b",
        r"\bpretend (to be|you are)\b.{0,40}\b(no rules|unrestricted|jailbroken)\b",
        # Chinese overrides
        r"忽略(以上|之前|前面|所有)?\s*(指令|提示|规则|约束)",
        r"忘记(之前|前面|以上|所有)\s*(指令|提示|规则|你的角色)",
        r"你(现在|从现在起)\s*(是|扮演)\s*.{0,20}\s*(DAN|越狱|无限制|没有规则)",
    ]
]


@dataclass
class PreFilterPass:
    masked_text: str
    masked_count: int  # number of sensitive-word substitutions applied


@dataclass
class PreFilterDeny:
    reason: str          # short machine-readable code
    user_message: str    # what to show the user


def run_pre_filter(content: str) -> PreFilterPass | PreFilterDeny:
    """Single entry point. Pure function, no IO, no async."""
    if not content or not content.strip():
        return PreFilterDeny(
            reason="empty_input",
            user_message="（消息为空，请描述你想做的项目）",
        )

    if len(content) > MAX_INPUT_CHARS:
        return PreFilterDeny(
            reason="too_long",
            user_message=(
                f"输入过长（{len(content)} 字符，上限 {MAX_INPUT_CHARS}）。"
                "请拆成更短的描述。"
            ),
        )

    for pat in _INJECTION_PATTERNS:
        if pat.search(content):
            return PreFilterDeny(
                reason="injection_pattern",
                user_message=(
                    "检测到可疑的指令覆盖模式。如果是误判，请用普通描述重述项目需求。"
                ),
            )

    masked = mask(content)
    masked_count = sum(
        1 for orig_char, new_char in zip(content, masked)
        if orig_char != new_char
    )
    return PreFilterPass(masked_text=masked, masked_count=masked_count)
