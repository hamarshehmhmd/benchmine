"""Thin, dependency-free helpers around the git CLI."""
import io
import os
import subprocess
import tarfile


JUNK = ["__pycache__/", "*.pyc", ".pytest_cache/", "node_modules/", ".venv/", "venv/", ".tox/",
        ".mypy_cache/", ".ruff_cache/", "*.egg-info/", "target/", ".gradle/", ".benchmine/"]


class GitError(RuntimeError):
    pass


def git(repo, *args, check=True, binary=False):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    if check and p.returncode != 0:
        raise GitError("git %s failed: %s" % (" ".join(args), p.stderr.decode(errors="replace").strip()))
    return p.stdout if binary else p.stdout.decode("utf-8", errors="replace")


def toplevel(path):
    return git(path, "rev-parse", "--show-toplevel").strip()


def rev_parse(repo, rev):
    return git(repo, "rev-parse", "--verify", rev + "^{commit}").strip()


def first_parent_commits(repo, rev="HEAD", limit=200, since=None):
    args = ["rev-list", "--first-parent", "-n", str(limit)]
    if since:
        args.append("--since=" + since)
    args.append(rev)
    return [c for c in git(repo, *args).split() if c]


def parents(repo, sha):
    line = git(repo, "rev-list", "--parents", "-n", "1", sha).split()
    return line[1:]


def message(repo, sha):
    return git(repo, "log", "-1", "--format=%B", sha)


def commit_date(repo, sha):
    return git(repo, "log", "-1", "--format=%cI", sha).strip()


def changed_files(repo, base, ref):
    """[(status, path)] between base and ref; renames reported as delete+add."""
    out = git(repo, "diff", "--name-status", "--no-renames", "-z", base, ref)
    parts = [p for p in out.split("\0") if p]
    res = []
    for i in range(0, len(parts) - 1, 2):
        res.append((parts[i][0], parts[i + 1]))
    return res


def numstat(repo, base, ref, paths):
    if not paths:
        return 0, 0
    out = git(repo, "diff", "--numstat", "--no-renames", base, ref, "--", *paths)
    add = rem = 0
    for line in out.splitlines():
        a, r, _ = line.split("\t", 2)
        if a != "-":
            add += int(a)
            rem += int(r)
    return add, rem


def diff(repo, base, ref, paths):
    return git(repo, "diff", "--binary", "--no-renames", base, ref, "--", *paths, binary=True)


def show_file(repo, rev, path):
    """Bytes of path at rev, or None if it does not exist there."""
    p = subprocess.run(["git", "-C", repo, "show", "%s:%s" % (rev, path)], capture_output=True)
    return p.stdout if p.returncode == 0 else None


def export_tree(repo, rev, dest):
    """Write the tracked tree at rev into dest (no .git, so no future history to peek at)."""
    data = git(repo, "archive", "--format=tar", rev, binary=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        try:
            tf.extractall(dest, filter="tar")
        except TypeError:  # Python < 3.12 without the filter backport
            tf.extractall(dest)


def init_snapshot(path):
    """Make dest a fresh one-commit repo so the agent and we can diff its edits."""
    env = dict(os.environ, GIT_AUTHOR_NAME="benchmine", GIT_AUTHOR_EMAIL="benchmine@localhost",
               GIT_COMMITTER_NAME="benchmine", GIT_COMMITTER_EMAIL="benchmine@localhost")
    subprocess.run(["git", "-C", path, "init", "-q"], capture_output=True, env=env)
    info = os.path.join(path, ".git", "info")
    os.makedirs(info, exist_ok=True)
    with open(os.path.join(info, "exclude"), "a") as fh:
        fh.write("\n".join(JUNK) + "\n")
    for args in ( ["add", "-A"], ["-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "--no-verify", "-m", "task base"]):
        p = subprocess.run(["git", "-C", path, *args], capture_output=True, env=env)
        if p.returncode != 0:
            raise GitError("snapshot git %s failed: %s" % (args[0], p.stderr.decode(errors="replace")))


def worktree_changes(path):
    """Files the agent changed (tracked edits, deletions and new untracked files)."""
    git(path, "add", "-A", check=False)
    out = git(path, "diff", "--cached", "--name-status", "--no-renames", "-z", "HEAD")
    parts = [p for p in out.split("\0") if p]
    files = [parts[i + 1] for i in range(0, len(parts) - 1, 2)]
    stat = git(path, "diff", "--cached", "--numstat", "--no-renames", "HEAD")
    add = rem = 0
    for line in stat.splitlines():
        a, r, _ = line.split("\t", 2)
        if a != "-":
            add += int(a)
            rem += int(r)
    patch = git(path, "diff", "--cached", "--binary", "--no-renames", "HEAD", binary=True)
    return files, add, rem, patch
