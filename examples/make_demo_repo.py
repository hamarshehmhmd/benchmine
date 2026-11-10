"""Build a small demo repo (a text-utils library) with a realistic mix of commits.

Usage: python examples/make_demo_repo.py DEST
Writes DEST (a git repo) and DEST.solutions.json (used only by the scripted stand-in agent).
"""
import json
import os
import subprocess
import sys

BASE = '''"""textkit: small text helpers."""
import re


def slugify(text):
    text = re.sub(r"[^a-z0-9]+", "-", text.lower())
    return text.strip("-")


def wrap(text, width):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return lines
'''

BASE_TEST = '''from textkit.core import slugify, wrap


def test_slugify():
    assert slugify("Hello, World!") == "hello-world"


def test_wrap():
    assert wrap("a bb ccc dddd", 6) == ["a bb", "ccc", "dddd"]
'''

# (subject, body, code to append or (old, new) replacement, test file, test code)
FEATURES = [
    ("Add max_len to slugify", "slugify(text, max_len=None) should cut the slug to at most max_len characters\n"
     "without leaving a trailing dash.",
     ('def slugify(text):\n    text = re.sub(r"[^a-z0-9]+", "-", text.lower())\n    return text.strip("-")\n',
      'def slugify(text, max_len=None):\n    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")\n'
      '    if max_len is not None:\n        text = text[:max_len].rstrip("-")\n    return text\n'),
     "tests/test_slug_len.py",
     'from textkit.core import slugify\n\n\ndef test_max_len():\n    assert slugify("Hello big world", max_len=9) == "hello-big"\n'
     '    assert slugify("Hello big world", max_len=6) == "hello"\n'),
    ("Add titlecase() that keeps small words lowercase",
     "titlecase('the lord of the rings') -> 'The Lord of the Rings'. Small words: a, an, the, of, and, or, in, on, to.\n"
     "The first word is always capitalised.",
     '\n\nSMALL = {"a", "an", "the", "of", "and", "or", "in", "on", "to"}\n\n\ndef titlecase(text):\n'
     '    words = text.lower().split()\n    return " ".join(w if i and w in SMALL else w.capitalize() for i, w in enumerate(words))\n',
     "tests/test_titlecase.py",
     'from textkit.core import titlecase\n\n\ndef test_titlecase():\n    assert titlecase("the lord of the rings") == "The Lord of the Rings"\n'),
    ("Fix wrap() hanging words longer than width",
     "wrap('abcdefghij', 4) returned ['abcdefghij']; split words longer than width into width-sized chunks.",
     ('    for w in words:\n        if cur',
      '    for w in [w[i:i + width] for w in words for i in range(0, len(w), width)]:\n        if cur'),
     "tests/test_wrap_long.py",
     'from textkit.core import wrap\n\n\ndef test_long_word():\n    assert wrap("abcdefghij", 4) == ["abcd", "efgh", "ij"]\n'),
    ("Add strip_accents()", "strip_accents('Crème Brûlée') -> 'Creme Brulee' using unicodedata NFKD.",
     '\n\ndef strip_accents(text):\n    import unicodedata\n'
     '    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))\n',
     "tests/test_accents.py",
     'from textkit.core import strip_accents\n\n\ndef test_accents():\n    assert strip_accents("Crème Brûlée") == "Creme Brulee"\n'),
    ("Add truncate() with an ellipsis", "truncate(text, n) returns text unchanged if it fits, otherwise the first\n"
     "n-1 characters plus '…' (total length n).",
     '\n\ndef truncate(text, n):\n    return text if len(text) <= n else text[: n - 1] + "…"\n',
     "tests/test_truncate.py",
     'from textkit.core import truncate\n\n\ndef test_truncate():\n    assert truncate("hello", 10) == "hello"\n    assert truncate("hello world", 6) == "hello…"\n'),
    ("Add count_words() that ignores punctuation", "count_words(\"Hi, it's me - again!\") == 4.",
     '\n\ndef count_words(text):\n    return len(re.findall(r"[A-Za-z0-9\']+", text))\n',
     "tests/test_count.py",
     'from textkit.core import count_words\n\n\ndef test_count():\n    assert count_words("Hi, it\'s me - again!") == 4\n'),
    ("Add snake_case()", "snake_case('HTTPServerError') -> 'http_server_error', snake_case('fooBar baz') -> 'foo_bar_baz'.",
     '\n\ndef snake_case(text):\n    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\\1_\\2", text)\n'
     '    text = re.sub(r"([a-z0-9])([A-Z])", r"\\1_\\2", text)\n    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_").lower()\n',
     "tests/test_snake.py",
     'from textkit.core import snake_case\n\n\ndef test_snake():\n    assert snake_case("HTTPServerError") == "http_server_error"\n'
     '    assert snake_case("fooBar baz") == "foo_bar_baz"\n'),
    ("Add camel_case()", "camel_case('foo_bar baz') -> 'fooBarBaz'.",
     '\n\ndef camel_case(text):\n    parts = [p for p in re.split(r"[^A-Za-z0-9]+", text) if p]\n'
     '    return parts[0].lower() + "".join(p.capitalize() for p in parts[1:]) if parts else ""\n',
     "tests/test_camel.py",
     'from textkit.core import camel_case\n\n\ndef test_camel():\n    assert camel_case("foo_bar baz") == "fooBarBaz"\n    assert camel_case("") == ""\n'),
    ("Fix slugify keeping apostrophes as separators", "slugify(\"Don't stop\") gave 'don-t-stop'; drop apostrophes first so it is 'dont-stop'.",
     ('    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")\n',
      '    text = re.sub(r"[^a-z0-9]+", "-", re.sub(r"[\'’]", "", text.lower())).strip("-")\n'),
     "tests/test_slug_apostrophe.py",
     'from textkit.core import slugify\n\n\ndef test_apostrophe():\n    assert slugify("Don\'t stop") == "dont-stop"\n'),
    ("Add is_palindrome()", "is_palindrome('Never odd or even') is True: ignore case, spaces and punctuation.",
     '\n\ndef is_palindrome(text):\n    s = re.sub(r"[^a-z0-9]", "", text.lower())\n    return s == s[::-1]\n',
     "tests/test_palindrome.py",
     'from textkit.core import is_palindrome\n\n\ndef test_pal():\n    assert is_palindrome("Never odd or even")\n    assert not is_palindrome("textkit")\n'),
    ("Add initials()", "initials('ada lovelace') -> 'AL'; initials('Grace Brewster Hopper') -> 'GBH'.",
     '\n\ndef initials(text):\n    return "".join(w[0].upper() for w in text.split())\n',
     "tests/test_initials.py",
     'from textkit.core import initials\n\n\ndef test_initials():\n    assert initials("ada lovelace") == "AL"\n    assert initials("Grace Brewster Hopper") == "GBH"\n'),
    ("Add reverse_words()", "reverse_words('one two  three') -> 'three two one' (collapse whitespace).",
     '\n\ndef reverse_words(text):\n    return " ".join(reversed(text.split()))\n',
     "tests/test_reverse.py",
     'from textkit.core import reverse_words\n\n\ndef test_reverse():\n    assert reverse_words("one two  three") == "three two one"\n'),
]

# Commits benchmine should skip or reject, mixed into history.
NOISE = {
    2: ("docs: explain wrap()", "README.md", "# textkit\n\nSmall text helpers. `wrap(text, width)` splits on spaces.\n"),
    5: ("Bump version to 0.2.0", "textkit/__init__.py", '__version__ = "0.2.0"\n'),
    7: ("Add more slugify tests", "tests/test_slug_more.py",
        'from textkit.core import slugify\n\n\ndef test_spaces():\n    assert slugify("  a  b ") == "a-b"\n'),
}


def run(dest, *args, date=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="Dev", GIT_AUTHOR_EMAIL="dev@example.com",
               GIT_COMMITTER_NAME="Dev", GIT_COMMITTER_EMAIL="dev@example.com")
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", "-C", dest, *args], check=True, capture_output=True, env=env)


def write(dest, path, text):
    full = os.path.join(dest, path)
    os.makedirs(os.path.dirname(full) or dest, exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(text)


def main(dest):
    os.makedirs(dest)
    run(dest, "init", "-q", "-b", "main")
    run(dest, "config", "commit.gpgsign", "false")
    write(dest, "textkit/__init__.py", '__version__ = "0.1.0"\n')
    write(dest, "textkit/core.py", BASE)
    write(dest, "tests/test_core.py", BASE_TEST)
    write(dest, "pyproject.toml", '[project]\nname = "textkit"\nversion = "0.1.0"\n')
    write(dest, ".gitignore", "__pycache__/\n")
    run(dest, "add", "-A")
    run(dest, "commit", "-q", "-m", "Initial textkit", date="2026-09-01T10:00:00Z")
    code = BASE
    solutions = {}
    for i, (subject, body, change, tpath, tcode) in enumerate(FEATURES):
        if i in NOISE:
            s, p, t = NOISE[i]
            write(dest, p, t)
            run(dest, "add", "-A")
            run(dest, "commit", "-q", "-m", s, date="2026-09-%02dT09:00:00Z" % (2 + i))
        if isinstance(change, tuple):
            assert change[0] in code, subject
            code = code.replace(change[0], change[1])
        else:
            code = code + change
        write(dest, "textkit/core.py", code)
        write(dest, tpath, tcode)
        solutions[subject] = {"textkit/core.py": code}
        run(dest, "add", "-A")
        run(dest, "commit", "-q", "-m", "%s (#%d)\n\n%s\n\nCo-authored-by: Someone <s@example.com>" % (subject, 10 + i, body),
            date="2026-09-%02dT15:00:00Z" % (2 + i))
    with open(dest.rstrip("/") + ".solutions.json", "w") as fh:
        json.dump(solutions, fh, indent=1)
    print("demo repo at %s: %d commits" % (dest, 1 + len(FEATURES) + len(NOISE)))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
