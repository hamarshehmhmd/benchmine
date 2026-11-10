"""Per-repo config (.benchmine/config.json) and test-file / test-command detection."""
import fnmatch
import json
import os

DIRNAME = ".benchmine"

TEST_PATTERNS = [
    "test_*.py", "*_test.py", "tests.py", "conftest.py",
    "*_test.go",
    "*.test.js", "*.test.jsx", "*.test.ts", "*.test.tsx", "*.test.mjs", "*.test.cjs",
    "*.spec.js", "*.spec.jsx", "*.spec.ts", "*.spec.tsx", "*.spec.mjs",
    "*Test.java", "*Tests.java", "*Test.kt", "*Tests.kt", "*_spec.rb", "*_test.rb", "*Tests.cs", "*Test.cs",
    "*_test.exs", "*_test.dart", "*Test.php",
]
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs", "testdata", "testing", "e2e"}

DEFAULTS = {
    "test_cmd": None,          # e.g. "python -m pytest -q {tests}"
    "setup_cmd": None,         # run in each fresh task tree before the agent, e.g. "npm ci"
    "test_patterns": TEST_PATTERNS,
    "test_dirs": sorted(TEST_DIRS),
    "ignore": ["*.md", "*.rst", "*.txt", "docs/*", "CHANGELOG*", ".github/*", "*.lock",
               "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "go.sum"],
    "prompt_template": (
        "You are working in a git repository checked out in the current directory.\n"
        "Make this change to the code:\n\n{message}\n\n"
        "Edit the files directly. Do not ask questions. Hidden tests will check the result."
    ),
    "timeout": 1800,
    "test_timeout": 600,
}


def is_test_path(path, cfg=None):
    cfg = cfg or DEFAULTS
    norm = path.replace("\\", "/")
    parts = norm.split("/")
    name = parts[-1]
    dirs = set(cfg.get("test_dirs", TEST_DIRS))
    if any(p in dirs for p in parts[:-1]):
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in cfg.get("test_patterns", TEST_PATTERNS))


def is_ignored(path, cfg=None):
    cfg = cfg or DEFAULTS
    name = path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(name, p) for p in cfg.get("ignore", []))


def detect_test_cmd(root):
    """Best guess at a test command template for the repo at root."""
    has = lambda f: os.path.exists(os.path.join(root, f))
    if has("go.mod"):
        return "go test {test_pkgs}"
    if has("Cargo.toml"):
        return "cargo test"
    if has("package.json"):
        try:
            with open(os.path.join(root, "package.json")) as fh:
                pkg = json.load(fh)
            scripts = pkg.get("scripts", {})
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        except (OSError, ValueError):
            scripts, deps = {}, {}
        if "vitest" in deps:
            return "npx vitest run {tests}"
        if "jest" in deps:
            return "npx jest {tests}"
        if "test" in scripts:
            return "npm test --silent"
        return "node --test {tests}"
    if any(has(f) for f in ("pyproject.toml", "setup.py", "setup.cfg", "pytest.ini", "tox.ini")):
        return "python -m pytest -q -p no:cacheprovider {tests}"
    if has("Gemfile"):
        return "bundle exec rspec {tests}"
    if has("pom.xml"):
        return "mvn -q test"
    if has("build.gradle") or has("build.gradle.kts"):
        return "./gradlew test"
    if has("Makefile"):
        return "make test"
    return None


def load(root):
    cfg = dict(DEFAULTS)
    path = os.path.join(root, DIRNAME, "config.json")
    if os.path.exists(path):
        with open(path) as fh:
            cfg.update(json.load(fh))
    if not cfg.get("test_cmd"):
        cfg["test_cmd"] = detect_test_cmd(root)
    return cfg


def save(root, cfg):
    d = os.path.join(root, DIRNAME)
    os.makedirs(d, exist_ok=True)
    keep = {k: v for k, v in cfg.items() if k in ("test_cmd", "setup_cmd", "timeout", "test_timeout")
            or (k in DEFAULTS and v != DEFAULTS[k])}
    with open(os.path.join(d, "config.json"), "w") as fh:
        json.dump(keep, fh, indent=2)
        fh.write("\n")
    gi = os.path.join(d, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w") as fh:
            fh.write("runs/\nwork/\n")
