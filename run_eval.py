"""
Maths word-problem eval harness (version 3).

Sends every question in questions.json to each model, extracts the final
number from the reply, checks it against the correct answer, and prints
results tables. Every raw response is saved so you can inspect mistakes later.

Version 2 added: an untimed warm-up per model, tracking whether each reply
showed its working, and scores by question category.

New in version 3:
  - --prompts chooses the instructions: "default" (working suggested),
    "working" (working forced) or "direct" (working forbidden).
  - When both "working" and "direct" are run, an extra table compares them
    question by question: a controlled experiment.
  - --regrade accepts several result files at once.

Usage examples:
    python run_eval.py --models llama3.2 qwen2.5:7b qwen2.5:14b
    python run_eval.py --models qwen2.5:7b --prompts working direct
    python run_eval.py --models mock --prompts working direct   # test without Ollama
    python run_eval.py --regrade results/2026-11-17_19-30-00/responses.jsonl
"""

import argparse
import json
import random
import re
import time
from datetime import datetime
from pathlib import Path

# The instructions a model can be given, chosen with --prompts.
# Every prompt asks for a fixed final line, so grading stays reliable:
# we look for "ANSWER: <number>".
ANSWER_FORMAT = (
    "Finish with a final line in exactly this format:\n"
    "ANSWER: <number>\n"
    "Give only the number on that line, with no units or currency symbols."
)

PROMPTS = {
    # The original prompt: suggests working, but the model can skip it.
    "default": (
        "You are solving a maths word problem. Think it through step by step. "
        + ANSWER_FORMAT
    ),
    # Forces working: the model must show every calculation.
    "working": (
        "You are solving a maths word problem. Before giving your answer, you MUST "
        "write out your working step by step, showing every calculation. Never skip "
        "straight to the answer. " + ANSWER_FORMAT
    ),
    # Forbids working: the model must answer immediately.
    "direct": (
        "You are solving a maths word problem. Do NOT show any working or explanation. "
        "Reply with only the final answer line and nothing else. " + ANSWER_FORMAT
    ),
}

# A reply counts as "showed working" if there are at least this many
# characters of text before the ANSWER line. "215\n\nANSWER: 215" does not.
MIN_WORKING_CHARS = 40


# ---------------------------------------------------------------------------
# Talking to models
# ---------------------------------------------------------------------------

def ask_ollama(model, question, prompt="default"):
    """Send one question to a local Ollama model and return its reply text."""
    import ollama  # imported here so --models mock works without it installed

    reply = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": PROMPTS[prompt]},
            {"role": "user", "content": question},
        ],
        # temperature 0 = the model always picks its most likely answer,
        # so reruns give (nearly) the same results.
        options={"temperature": 0},
    )
    return reply["message"]["content"]


def ask_mock(question_obj, prompt="default"):
    """A fake model for testing. It does better when it shows working, like real models seem to."""
    shows_working = {"working": True, "direct": False}.get(prompt, random.random() < 0.6)
    accuracy = 0.85 if shows_working else 0.55
    correct = question_obj["answer"]
    guess = correct if random.random() < accuracy else correct + random.choice([-1, 1, 10])
    working = "Let me work through this step by step. First... then...\n" if shows_working else ""
    return f"{working}ANSWER: {guess}"


def ask_model(model, question_obj, prompt="default"):
    if model == "mock":
        return ask_mock(question_obj, prompt)
    return ask_ollama(model, question_obj["question"], prompt)


def warm_up(model):
    """Load the model into memory with a throwaway question, so loading time isn't timed."""
    if model == "mock":
        return
    print(f"  Loading {model} (warm-up, not timed)...")
    start = time.time()
    try:
        ask_ollama(model, "What is 2 + 2?")
        print(f"  Loaded in {time.time() - start:.1f}s")
    except Exception as e:
        print(f"  Warm-up failed: {e}")


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

NUMBER = r"-?\d[\d,]*(?:\.\d+)?"


def to_float(text):
    return float(text.replace(",", ""))


def extract_answer(reply):
    """
    Pull the model's final number out of its reply.

    Returns (number or None, method) where method says how we found it:
      "tagged"   - found on an "ANSWER:" line, as instructed
      "fallback" - no ANSWER line, so we took the last number in the reply
      "none"     - couldn't find any number
    """
    tagged = re.findall(r"ANSWER:\s*[£$]?\s*(" + NUMBER + ")", reply, re.IGNORECASE)
    if tagged:
        return to_float(tagged[-1]), "tagged"

    numbers = re.findall(NUMBER, reply)
    if numbers:
        return to_float(numbers[-1]), "fallback"

    return None, "none"


def showed_working(reply):
    """True if the reply has a meaningful amount of text before its final answer."""
    matches = list(re.finditer(r"ANSWER:", reply, re.IGNORECASE))
    before = reply[: matches[-1].start()] if matches else reply
    return len(before.strip()) >= MIN_WORKING_CHARS


def is_correct(got, expected):
    if got is None:
        return False
    return abs(got - expected) < 1e-6 + 1e-3 * abs(expected)


def grade(row):
    got, method = extract_answer(row["reply"])
    row["extracted"] = got
    row["extract_method"] = method
    row["correct"] = is_correct(got, row["expected"])
    row["showed_working"] = showed_working(row["reply"])
    return row


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def label(row):
    """Name used in the tables: the model, plus the prompt if it isn't the default."""
    prompt = row.get("prompt", "default")
    return row["model"] if prompt == "default" else f"{row['model']} [{prompt}]"


def score(rows):
    """'right/total' for a list of rows, or '-' if empty."""
    return f"{sum(r['correct'] for r in rows)}/{len(rows)}" if rows else "-"


def print_report(rows):
    labels = list(dict.fromkeys(label(r) for r in rows))  # keep run order
    width = max(16, max(len(l) for l in labels) + 2)
    difficulties = ["easy", "medium", "hard"]
    categories = list(dict.fromkeys(r.get("category", "unknown") for r in rows))

    # --- Main table ---
    print("\n=== Results ===")
    header = f"{'model':<{width}}{'score':>8}{'easy':>8}{'medium':>8}{'hard':>8}{'avg secs':>10}{'no ANSWER line':>16}"
    print(header)
    print("-" * len(header))
    for m in labels:
        mine = [r for r in rows if label(r) == m]
        cells = [score([r for r in mine if r["difficulty"] == d]) for d in difficulties]
        avg_secs = sum(r["seconds"] for r in mine) / len(mine)
        untagged = sum(r["extract_method"] != "tagged" for r in mine)
        print(f"{m:<{width}}{score(mine):>8}{cells[0]:>8}{cells[1]:>8}{cells[2]:>8}{avg_secs:>10.1f}{untagged:>16}")

    # --- By category ---
    print("\n=== Score by category ===")
    header = f"{'model':<{width}}" + "".join(f"{c:>13}" for c in categories)
    print(header)
    print("-" * len(header))
    for m in labels:
        mine = [r for r in rows if label(r) == m]
        cells = [score([r for r in mine if r.get("category", "unknown") == c]) for c in categories]
        print(f"{m:<{width}}" + "".join(f"{c:>13}" for c in cells))

    # --- Working vs no working ---
    # With --prompts working/direct this doubles as a check that the model
    # actually obeyed: [working] should be all "showed working", [direct] none.
    print("\n=== Did showing working help? ===")
    header = f"{'model':<{width}}{'showed working':>16}{'right':>8}{'no working':>12}{'right':>8}"
    print(header)
    print("-" * len(header))
    for m in labels:
        mine = [r for r in rows if label(r) == m]
        w = [r for r in mine if r["showed_working"]]
        nw = [r for r in mine if not r["showed_working"]]
        print(f"{m:<{width}}{len(w):>16}{score(w):>8}{len(nw):>12}{score(nw):>8}")

    # --- Controlled experiment: same model, same question, working vs direct ---
    prompts_used = {r.get("prompt", "default") for r in rows}
    if {"working", "direct"} <= prompts_used:
        print("\n=== Experiment: forced working vs forced direct (same questions) ===")
        header = f"{'model':<16}{'both right':>12}{'only working right':>20}{'only direct right':>19}{'both wrong':>12}"
        print(header)
        print("-" * len(header))
        for model in dict.fromkeys(r["model"] for r in rows):
            by_id = {}
            for r in rows:
                if r["model"] == model and r.get("prompt") in ("working", "direct"):
                    by_id.setdefault(r["id"], {})[r["prompt"]] = r["correct"]
            pairs = [v for v in by_id.values() if len(v) == 2]
            if not pairs:
                continue
            both = sum(v["working"] and v["direct"] for v in pairs)
            only_w = sum(v["working"] and not v["direct"] for v in pairs)
            only_d = sum(v["direct"] and not v["working"] for v in pairs)
            neither = sum(not v["working"] and not v["direct"] for v in pairs)
            print(f"{model:<16}{both:>12}{only_w:>20}{only_d:>19}{neither:>12}")
        print("The two middle columns are what matter: questions where the prompt changed the result.")

    # --- Mistakes ---
    print("\n=== Mistakes ===")
    wrong = [r for r in rows if not r["correct"]]
    if not wrong:
        print("None! Time to write harder questions.")
    for r in wrong:
        working = "showed working" if r["showed_working"] else "NO working"
        print(f"{label(r):<{width}}{r['id']}  expected {r['expected']}, got {r['extracted']}  ({working})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(models, prompts, questions_path):
    questions = json.loads(Path(questions_path).read_text(encoding="utf-8"))
    out_dir = Path("results") / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "responses.jsonl"

    rows = []
    with out_file.open("w", encoding="utf-8") as f:
        for model in models:
            warm_up(model)
            for prompt in prompts:
                print(f"\nRunning {model} with the '{prompt}' prompt on {len(questions)} questions...")
                for q in questions:
                    start = time.time()
                    try:
                        reply = ask_model(model, q, prompt)
                    except Exception as e:  # e.g. model not downloaded, Ollama not running
                        reply = f"ERROR: {e}"
                    row = grade({
                        "model": model,
                        "prompt": prompt,
                        "id": q["id"],
                        "difficulty": q.get("difficulty", "unknown"),
                        "category": q.get("category", "unknown"),
                        "question": q["question"],
                        "expected": q["answer"],
                        "reply": reply,
                        "seconds": round(time.time() - start, 2),
                    })
                    mark = "right" if row["correct"] else "WRONG"
                    print(f"  {q['id']} {mark}  ({row['seconds']}s)")
                    if reply.startswith("ERROR:"):
                        print(f"    {reply}")
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    rows.append(row)

    print_report(rows)
    print(f"\nFull responses saved to {out_file}")


def regrade(responses_paths, questions_path):
    """Re-score saved responses without asking the models again. Accepts several files."""
    questions = {q["id"]: q for q in json.loads(Path(questions_path).read_text(encoding="utf-8"))}
    rows = []
    for path in responses_paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            # Older result files have no category or prompt, so fill them in.
            row.setdefault("category", questions.get(row["id"], {}).get("category", "unknown"))
            row.setdefault("prompt", "default")
            rows.append(grade(row))
    print_report(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Maths word-problem eval")
    parser.add_argument("--models", nargs="+", help="Ollama model names, or 'mock' for a test run")
    parser.add_argument("--prompts", nargs="+", default=["default"], choices=list(PROMPTS),
                        help="which instructions to give the models: default, working, direct")
    parser.add_argument("--questions", default="questions.json")
    parser.add_argument("--regrade", nargs="+", help="saved responses.jsonl file(s) to re-score")
    args = parser.parse_args()

    if args.regrade:
        regrade(args.regrade, args.questions)
    elif args.models:
        run(args.models, args.prompts, args.questions)
    else:
        parser.print_help()
