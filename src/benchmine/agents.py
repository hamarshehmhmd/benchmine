"""Agent presets. Each is a shell command template run inside the task tree.

Placeholders: {prompt_file} {prompt} (shell-quoted) {model} {task_id} {workdir}
Env passed to the agent: BENCHMINE_PROMPT_FILE, BENCHMINE_TASK_ID, BENCHMINE_MODEL, BENCHMINE_COST_FILE
(write a USD number there to report cost).
"""

# The CLI flags below follow each vendor's documented non-interactive mode. They are not exercised in
# CI (that needs paid accounts); check them against your installed version with `benchmine agents`.
PRESETS = {
    "claude-code": {
        "cmd": "claude -p {prompt} --output-format json --permission-mode acceptEdits {model_flag}",
        "model_flag": "--model {model}",
        "cost_regex": r'"total_cost_usd"\s*:\s*([0-9.eE+-]+)',
        "doc": "https://code.claude.com/docs/en/headless",
    },
    "codex": {
        "cmd": "codex exec --full-auto --skip-git-repo-check {model_flag} - < {prompt_file}",
        "model_flag": "-m {model}",
        "cost_regex": None,
        "doc": "https://developers.openai.com/codex/noninteractive",
    },
    "gemini": {
        "cmd": "gemini --yolo {model_flag} -p {prompt}",
        "model_flag": "-m {model}",
        "cost_regex": None,
        "doc": "https://github.com/google-gemini/gemini-cli",
    },
    "cursor": {
        "cmd": "cursor-agent -p --force --output-format text {model_flag} {prompt}",
        "model_flag": "--model {model}",
        "cost_regex": None,
        "doc": "https://cursor.com/docs/cli/headless",
    },
    "aider": {
        "cmd": "aider --yes-always --no-auto-commits --no-gitignore --no-check-update {model_flag} --message-file {prompt_file}",
        "model_flag": "--model {model}",
        "cost_regex": r"Cost:.*?\$([0-9.]+) session",
        "doc": "https://aider.chat/docs/scripting.html",
    },
    "opencode": {
        "cmd": "opencode run {model_flag} {prompt}",
        "model_flag": "-m {model}",
        "cost_regex": None,
        "doc": "https://opencode.ai/docs/cli/",
    },
}

BUILTIN = {
    "oracle": "applies the real change from history (should score 100%: checks your tasks and test command)",
    "noop": "changes nothing (should score 0%: checks the tests really catch a missing change)",
}


def resolve(agent, cmd=None, model=None):
    """Return (kind, command_template, cost_regex). kind is 'oracle', 'noop' or 'cmd'."""
    if agent in BUILTIN and not cmd:
        return agent, None, None
    if cmd:
        return "cmd", cmd, None
    if agent not in PRESETS:
        raise ValueError("unknown agent %r: use one of %s, or --cmd" % (agent, ", ".join(list(BUILTIN) + list(PRESETS))))
    p = PRESETS[agent]
    flag = p["model_flag"].replace("{model}", "{model}") if model else ""
    return "cmd", p["cmd"].replace("{model_flag}", flag), p["cost_regex"]
