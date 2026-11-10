#!/usr/bin/env python3
"""A SCRIPTED STAND-IN AGENT for demos and tests. It is not an AI model.

It reads the task prompt, looks the answer up in the demo repo's solutions file and either applies it
or "fails" (leaves a TODO), following a fixed profile, so the demo can show a stable model, a cheaper
model and a model that silently got worse. Cost and time are simulated.

Usage (as a benchmine --cmd): python standin.py PROFILE SOLUTIONS.json
"""
import json
import os
import sys
import time

# Subjects each profile gets wrong.
PROFILES = {
    "big-model": {"Add snake_case()"},
    "small-model": {"Add snake_case()", "Fix wrap() hanging words longer than width", "Add max_len to slugify",
                    "Fix slugify keeping apostrophes as separators"},
    "big-model-after-update": {"Add snake_case()", "Fix wrap() hanging words longer than width", "Add max_len to slugify",
                               "Fix slugify keeping apostrophes as separators", "Add truncate() with an ellipsis",
                               "Add count_words() that ignores punctuation", "Add strip_accents()"},
}
PRICE = {"big-model": 0.42, "small-model": 0.07, "big-model-after-update": 0.31}


def main():
    profile, solutions = sys.argv[1], sys.argv[2]
    prompt = open(os.environ["BENCHMINE_PROMPT_FILE"]).read()
    sols = json.load(open(solutions))
    subject = next((s for s in sols if s in prompt), None)
    time.sleep(0.2 + 0.05 * (len(prompt) % 7))
    if subject and subject not in PROFILES[profile]:
        for path, text in sols[subject].items():
            with open(path, "w") as fh:
                fh.write(text)
        print("stand-in agent: applied a fix for %r" % subject)
    else:
        with open("textkit/core.py", "a") as fh:
            fh.write("\n# TODO: %s\n" % (subject or "unknown task"))
        print("stand-in agent: gave up")
    with open(os.environ["BENCHMINE_COST_FILE"], "w") as fh:
        fh.write(str(PRICE[profile] * (1 + (len(prompt) % 5) / 10)))


if __name__ == "__main__":
    main()
