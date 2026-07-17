"""
OFFLINE SIMULATION of the "Building an Eval" notebook — no API key required.

Why this exists:
    The real notebook calls Claude, which needs an ANTHROPIC_API_KEY. This file
    swaps the live model for a deterministic FAKE "brain" so you can run the eval,
    watch the broken agent fail, flip on the fixes, and watch it pass.

    The grader logic below is copied VERBATIM from the notebook (cells 8 + 26).
    Only the agent is faked. The fake behavior is illustrative — it mimics how the
    broken vs. fixed agent would realistically act, so the pass/fail story matches
    what you'd see live.

Run it:
    python3 simulate_eval.py
"""

import re

# ──────────────────────────────────────────────────────────────────────────────
# The product catalog (same as the notebook)
# ──────────────────────────────────────────────────────────────────────────────
CATALOG = {
    "jeans": 49.99, "shirt": 29.99, "dress": 59.99, "jacket": 89.99,
    "sneakers": 74.99, "hat": 19.99, "socks": 9.99, "hoodie": 44.99,
    "shorts": 34.99, "t-shirt": 24.99, "sweater": 54.99, "belt": 24.99,
}

# ──────────────────────────────────────────────────────────────────────────────
# GRADERS — copied verbatim from notebook cell 8.
# Each takes a `result` dict ({"final_text", "tool_calls"}) and a `check`,
# and returns {"score": 0.0 or 1.0, "reason": ...}.
# ──────────────────────────────────────────────────────────────────────────────
def grade_response_contains(result, check, context=None):
    text = result["final_text"].lower()
    target = check.lower()
    if target in text:
        return {"score": 1.0, "reason": f"Found '{check}' in response"}
    return {"score": 0.0, "reason": f"'{check}' not found in response: {result['final_text'][:200]}"}


def grade_response_numeric(result, check, context=None):
    if isinstance(check, (int, float)):
        value, tolerance = float(check), 0.01
    else:
        value = float(check["value"])
        tolerance = float(check.get("tolerance", 0.01))

    numbers = re.findall(r"-?[\d,]+\.?\d*", result["final_text"])
    for num_str in numbers:
        try:
            num = float(num_str.replace(",", ""))
            if abs(num - value) <= tolerance:
                return {"score": 1.0, "reason": f"Found {num} (expected {value} +/- {tolerance})"}
        except ValueError:
            continue
    return {"score": 0.0, "reason": f"Expected {value} (+/- {tolerance}), found: {numbers[:10]}"}


def grade_tool_use(result, check, context=None):
    tool_name = check["tool_name"]
    expected_args = check.get("arguments", None)

    for call in result["tool_calls"]:
        if call["name"] != tool_name:
            continue
        if expected_args is None:
            return {"score": 1.0, "reason": f"Tool '{tool_name}' was called"}

        actual_args = call.get("arguments", {})
        match = all(
            (isinstance(v, str) and isinstance(actual_args.get(k), str) and v.lower() == actual_args[k].lower())
            or actual_args.get(k) == v
            for k, v in expected_args.items()
        )
        if match:
            return {"score": 1.0, "reason": f"Tool '{tool_name}' called with matching args: {expected_args}"}

    actual = [{"name": c["name"], "args": c.get("arguments", {})} for c in result["tool_calls"]]
    if expected_args:
        return {"score": 0.0, "reason": f"'{tool_name}' not called with {expected_args}. Actual: {actual}"}
    return {"score": 0.0, "reason": f"'{tool_name}' never called. Actual: {[c['name'] for c in result['tool_calls']]}"}


def grade_llm_judge(result, check, context=None):
    """FAKE offline judge. Live version asks Claude; here we use a keyword heuristic
    so 'What do you sell?' can still be graded without an API key."""
    text = result["final_text"].lower()
    if "list the available products" in check.lower() or "lists some of the available products" in check.lower():
        passed = any(p in text for p in CATALOG)  # mentions at least one real product
    else:  # "helpful and relevant" style criterion
        passed = len(text) > 0 and "error" not in text and "can't help" not in text
    if passed:
        return {"score": 1.0, "reason": "(fake judge) criterion met"}
    return {"score": 0.0, "reason": "(fake judge) criterion not met"}


GRADER_REGISTRY = {
    "response_contains": grade_response_contains,
    "response_numeric": grade_response_numeric,
    "tool_use": grade_tool_use,
    "llm_judge": grade_llm_judge,
}

# ──────────────────────────────────────────────────────────────────────────────
# REFERENCE TASKS — copied from notebook cell 26.
# ──────────────────────────────────────────────────────────────────────────────
reference_tasks = [
    {
        "id": "price_jeans",
        "description": "Direct price lookup for jeans",
        "query": "How much do jeans cost?",
        "category": "product_lookup",
        "graders": [
            {"type": "response_contains", "checks": ["49.99"]},
            {"type": "tool_use", "checks": [{"tool_name": "get_product", "arguments": {"product": "jeans"}}]},
        ],
    },
    {
        "id": "price_tshirt",
        "description": "Price lookup with hyphenated product name",
        "query": "Price of a t-shirt?",
        "category": "product_lookup",
        "graders": [
            {"type": "response_contains", "checks": ["24.99"]},
            {"type": "tool_use", "checks": [{"tool_name": "get_product", "arguments": {"product": "t-shirt"}}]},
        ],
    },
    {
        "id": "price_shoes_synonym",
        "description": "Synonym query: 'shoes' is not in catalog ('sneakers' is)",
        "query": "How much for shoes?",
        "category": "product_lookup",
        "graders": [
            {"type": "tool_use", "checks": [{"tool_name": "get_product"}]},
            {"type": "response_contains", "checks": ["sneakers"]},
        ],
    },
    {
        "id": "total_shirts_belts",
        "description": "Multi-item total requiring product lookups + calculation",
        "query": "3 shirts and 2 belts, what's my total?",
        "category": "multi_tool",
        "graders": [
            {"type": "response_numeric", "checks": [{"value": 139.95, "tolerance": 0.10}]},
            {"type": "tool_use", "checks": [
                {"tool_name": "get_product"},
                {"tool_name": "calculate", "arguments": {"op": "*"}},
                {"tool_name": "calculate", "arguments": {"op": "+"}},
            ]},
        ],
    },
    {
        "id": "discount_jacket",
        "description": "Calculate 20% off a jacket (lookup + percentage math)",
        "query": "What's 20% off a jacket?",
        "category": "calculation",
        "graders": [
            {"type": "response_numeric", "checks": [{"value": 71.99, "tolerance": 0.10}]},
            {"type": "tool_use", "checks": [
                {"tool_name": "get_product"},
                {"tool_name": "calculate"},
            ]},
        ],
    },
    {
        "id": "what_do_you_sell",
        "description": "Open-ended: agent describes available products",
        "query": "What do you sell?",
        "category": "capabilities",
        "graders": [
            {"type": "llm_judge", "checks": [
                "Response lists some of the available products in the catalog",
                "Response is helpful and relevant to a shopping context",
            ]},
        ],
    },
]

# ──────────────────────────────────────────────────────────────────────────────
# FAKE AGENT — stands in for Claude. `mode` is "broken" or "fixed".
# Returns the same {"final_text", "tool_calls"} shape the graders expect.
# This is hand-scripted to mirror how the real agent behaves with bad vs good
# tool specs / system prompt — NOT a real model.
# ──────────────────────────────────────────────────────────────────────────────
def fake_agent(query, mode):
    q = query.lower()

    # ── jeans: works in both modes ──
    if "jeans" in q:
        return {
            "final_text": "Jeans cost $49.99.",
            "tool_calls": [{"name": "get_product", "arguments": {"product": "jeans"}}],
        }

    # ── t-shirt: broken agent guesses the wrong key format ──
    if "t-shirt" in q or "tshirt" in q or "t shirt" in q:
        if mode == "broken":
            # No catalog hint in the spec → guesses "tshirt" → KeyError
            return {
                "final_text": "Sorry, I couldn't find that product.",
                "tool_calls": [{"name": "get_product", "arguments": {"product": "tshirt"}}],
            }
        return {
            "final_text": "A t-shirt is $24.99.",
            "tool_calls": [{"name": "get_product", "arguments": {"product": "t-shirt"}}],
        }

    # ── shoes: not in catalog; broken agent can't suggest an alternative ──
    if "shoes" in q:
        if mode == "broken":
            # Raw KeyError, no catalog knowledge → no "sneakers" suggestion
            return {
                "final_text": "Sorry, shoes don't seem to be available.",
                "tool_calls": [{"name": "get_product", "arguments": {"product": "shoes"}}],
            }
        return {
            "final_text": "We don't carry 'shoes', but we have sneakers for $74.99 — want those?",
            "tool_calls": [{"name": "get_product", "arguments": {"product": "shoes"}}],
        }

    # ── multi-tool total: broken agent does MENTAL math (skips calculate) ──
    if "shirts" in q and "belts" in q:
        if mode == "broken":
            return {
                "final_text": "3 shirts and 2 belts come to $139.95.",  # right number, wrong method
                "tool_calls": [
                    {"name": "get_product", "arguments": {"product": "shirt"}},
                    {"name": "get_product", "arguments": {"product": "belt"}},
                ],
            }
        return {
            "final_text": "3 shirts (89.97) + 2 belts (49.98) = $139.95 total.",
            "tool_calls": [
                {"name": "get_product", "arguments": {"product": "shirt"}},
                {"name": "get_product", "arguments": {"product": "belt"}},
                {"name": "calculate", "arguments": {"op": "*", "input1": 29.99, "input2": 3}},
                {"name": "calculate", "arguments": {"op": "*", "input1": 24.99, "input2": 2}},
                {"name": "calculate", "arguments": {"op": "+", "input1": 89.97, "input2": 49.98}},
            ],
        }

    # ── 20% off jacket: broken agent does mental math (skips calculate) ──
    if "20%" in q and "jacket" in q:
        if mode == "broken":
            return {
                "final_text": "20% off a jacket is about $71.99.",  # right number, no calculate tool
                "tool_calls": [{"name": "get_product", "arguments": {"product": "jacket"}}],
            }
        return {
            "final_text": "A jacket is $89.99; 20% off makes it $71.99.",
            "tool_calls": [
                {"name": "get_product", "arguments": {"product": "jacket"}},
                {"name": "calculate", "arguments": {"op": "*", "input1": 89.99, "input2": 0.8}},
            ],
        }

    # ── "what do you sell?" ──
    if "sell" in q:
        if mode == "broken":
            return {"final_text": "I'm a helpful assistant! How can I help?", "tool_calls": []}
        return {
            "final_text": "We sell jeans, shirts, dresses, jackets, sneakers, hats, "
                          "socks, hoodies, shorts, t-shirts, sweaters, and belts.",
            "tool_calls": [],
        }

    return {"final_text": "I'm not sure how to help with that.", "tool_calls": []}


# ──────────────────────────────────────────────────────────────────────────────
# RUNNER — apply graders to each task and tally results.
# ──────────────────────────────────────────────────────────────────────────────
def run_eval(mode):
    print(f"\n{'=' * 64}\nEVAL RESULTS — agent mode: {mode.upper()}\n{'=' * 64}")
    passed_count = 0
    for task in reference_tasks:
        result = fake_agent(task["query"], mode)
        grades = []
        for grader in task["graders"]:
            fn = GRADER_REGISTRY[grader["type"]]
            for check in grader["checks"]:
                grades.append({"type": grader["type"], **fn(result, check, {"query": task["query"]})})
        task_passed = all(g["score"] == 1.0 for g in grades)
        passed_count += task_passed
        print(f"\n[{'PASS' if task_passed else 'FAIL'}] {task['id']}: {task['description']}")
        print(f"   query:    {task['query']}")
        print(f"   response: {result['final_text']}")
        for g in grades:
            print(f"   {'+' if g['score'] == 1.0 else '-'} {g['type']}: {g['reason'][:110]}")
    total = len(reference_tasks)
    print(f"\n{'-' * 64}")
    print(f"OVERALL ({mode}): {passed_count}/{total} passed ({passed_count / total * 100:.0f}%)")
    print(f"{'-' * 64}")
    return passed_count, total


if __name__ == "__main__":
    print("Running the eval against the BROKEN agent (vague prompt, useless tool specs, raw KeyError)...")
    run_eval("broken")
    print("\n\nNow the SAME eval against the FIXED agent (cell 28: real prompt, catalog in specs, friendly errors)...")
    run_eval("fixed")
    print("\nThis is the whole lesson: same tasks, same graders — only the agent changed.")
