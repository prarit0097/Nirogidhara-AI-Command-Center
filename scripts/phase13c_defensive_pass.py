"""Phase 13C defensive transformation pass on SaasAdmin.tsx.

Transforms unsafe array-like accesses into safe `(x ?? []).method(...)`
patterns. Designed to be idempotent (running twice produces the same
output) and conservative (skips already-defended accesses).

Targets:
- `.length`  -> `(parent ?? []).length`
- `.map(`    -> `(parent ?? []).map(`
- `.filter(` -> `(parent ?? []).filter(`
- `.find(`   -> `(parent ?? []).find(`
- `.reduce(` -> `(parent ?? []).reduce(`
- `.forEach(`-> `(parent ?? []).forEach(`
- `.some(`   -> `(parent ?? []).some(`
- `.every(`  -> `(parent ?? []).every(`
- `.slice(`  -> `(parent ?? []).slice(`
- `.join(`   -> `(parent ?? []).join(`

Rules:
- Never wraps an access that's already inside `(... ?? [])` (idempotent).
- Never wraps `?.method(` (already nullish-safe).
- Never wraps string literals or template literal `.length` accesses.
- Only matches identifiers/chains in the form `[A-Za-z_$][A-Za-z0-9_$]*`
  optionally followed by `.<name>` segments (NO function calls in the
  chain, since those are already-evaluated expressions whose result we
  shouldn't second-guess).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

METHODS = (
    "map", "filter", "find", "reduce", "forEach", "some", "every",
    "slice", "join",
)

# Match `<chain>.<method>(`  where `<chain>` is one or more dotted
# identifiers, NOT preceded by `?` (already safe), NOT preceded by an
# opening `(` followed by `... ?? []` (already wrapped), NOT preceded by
# `'` or `"` (string literal), NOT starting after `??` (would create
# `(x ?? [] ?? []).method`).
#
# Negative lookbehind for `?` covers `x?.method`. We also exclude `??`
# preceding the chain by checking the immediately preceding char isn't
# `]` followed by `).method` — but a simpler approach: after the
# transformation, anywhere we'd produce `?? []) ?? []`, that's
# self-evidently already-wrapped; an idempotence pass will catch any
# accidental double-wrap.
#
# The chain pattern allows simple member access like
# `foo.bar.baz.items` but NOT calls like `foo.bar()`.
CHAIN = r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*"


def _already_wrapped(line_before_match: str) -> bool:
    """Check whether the chain we're about to wrap is already inside a
    `(... ?? [])` expression. Cheap heuristic: look at the 30 chars
    before the match start for a recent `?? []`.
    """
    tail = line_before_match[-40:]
    return "?? []" in tail


def transform_method_calls(src: str) -> tuple[str, int]:
    """Wrap unsafe `chain.method(` with `(chain ?? []).method(`."""
    count = 0
    methods_alt = "|".join(METHODS)
    pattern = re.compile(rf"(?<![?\w.])({CHAIN})\.({methods_alt})\(")
    out: list[str] = []
    pos = 0
    for m in pattern.finditer(src):
        chain = m.group(1)
        method = m.group(2)
        # Skip if the chain itself starts with an already-wrapped form.
        # That can't happen with our pattern (no parens allowed in chain)
        # but the previous-context check covers the case where the chain
        # is on the right side of `?? [])`.
        prefix = src[max(0, m.start() - 40):m.start()]
        if _already_wrapped(prefix):
            continue
        # Skip if the literal prefix character is `.` (chained method
        # call like `foo.bar().map(` — the prior method call already
        # returned an array; transforming would break it).
        # Our CHAIN regex disallows `(`, so this is impossible — but
        # double-check by ensuring there's no `)` immediately before
        # the chain start with no whitespace.
        prev_char = src[m.start() - 1] if m.start() > 0 else ""
        if prev_char == ")":
            continue
        out.append(src[pos:m.start()])
        out.append(f"({chain} ?? []).{method}(")
        pos = m.end()
        count += 1
    out.append(src[pos:])
    return "".join(out), count


def transform_length(src: str) -> tuple[str, int]:
    """Wrap unsafe `chain.length` with `(chain ?? []).length`."""
    count = 0
    pattern = re.compile(rf"(?<![?\w.])({CHAIN})\.length\b")
    out: list[str] = []
    pos = 0
    for m in pattern.finditer(src):
        chain = m.group(1)
        prefix = src[max(0, m.start() - 40):m.start()]
        if _already_wrapped(prefix):
            continue
        prev_char = src[m.start() - 1] if m.start() > 0 else ""
        if prev_char == ")":
            continue
        # Skip string literals — if the chain is just a quoted literal,
        # the chain regex wouldn't have captured a quote, so safe.
        # Skip `Array.length`, `String.length`, etc. (capitalized type
        # references) — these are constructors / classes, not arrays.
        first_id = chain.split(".")[0]
        if first_id in ("Array", "String", "Object", "Number", "Math"):
            continue
        out.append(src[pos:m.start()])
        out.append(f"({chain} ?? []).length")
        pos = m.end()
        count += 1
    out.append(src[pos:])
    return "".join(out), count


def main(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    src, n_methods = transform_method_calls(src)
    src, n_length = transform_length(src)
    path.write_text(src, encoding="utf-8", newline="\n")
    print(f"Transformed {n_methods} array method calls + {n_length} .length accesses")


if __name__ == "__main__":
    target = Path(
        sys.argv[1] if len(sys.argv) > 1
        else "frontend/src/pages/SaasAdmin.tsx"
    )
    main(target)
