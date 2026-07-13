from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


RUNNER = r'''
import ast, json, math, statistics, sys
code = sys.stdin.read()
tree = ast.parse(code, mode="exec")
banned_nodes = (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.With, ast.AsyncWith,
                ast.Try, ast.Raise, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
banned_names = {"open", "exec", "eval", "compile", "input", "help", "breakpoint", "globals", "locals", "vars", "dir", "getattr", "setattr", "delattr", "__import__"}
for node in ast.walk(tree):
    if isinstance(node, banned_nodes): raise ValueError(f"Disallowed syntax: {type(node).__name__}")
    if isinstance(node, ast.Name) and node.id in banned_names: raise ValueError(f"Disallowed name: {node.id}")
    if isinstance(node, ast.Attribute) and node.attr.startswith("_"): raise ValueError("Private attributes are disallowed")
safe = {"abs":abs,"all":all,"any":any,"bool":bool,"dict":dict,"enumerate":enumerate,"float":float,
        "int":int,"len":len,"list":list,"max":max,"min":min,"pow":pow,"print":print,"range":range,
        "reversed":reversed,"round":round,"set":set,"sorted":sorted,"str":str,"sum":sum,"tuple":tuple,"zip":zip}
scope = {"__builtins__": safe, "math": math, "statistics": statistics}
exec(compile(tree, "<mcp-python>", "exec"), scope, scope)
result = scope.get("result")
if result is not None: print("__AIOS_RESULT__" + json.dumps(result, default=str))
'''


def run_restricted_python(code: str, timeout_seconds: int = 5) -> dict[str, Any]:
    if not code.strip():
        raise ValueError("code is required")
    timeout_seconds = max(1, min(timeout_seconds, 15))
    root = Path(os.getenv("AIOS_MCP_WORKSPACE_ROOT", Path(__file__).resolve().parents[2])).resolve()
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", RUNNER], input=code, text=True, capture_output=True,
            cwd=root, timeout=timeout_seconds, env={"PYTHONIOENCODING": "utf-8"}, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"Python execution exceeded {timeout_seconds} seconds") from exc
    stdout, stderr = completed.stdout[-50_000:], completed.stderr[-20_000:]
    result: Any = None
    clean_lines = []
    for line in stdout.splitlines():
        if line.startswith("__AIOS_RESULT__"):
            try: result = json.loads(line.removeprefix("__AIOS_RESULT__"))
            except json.JSONDecodeError: result = line.removeprefix("__AIOS_RESULT__")
        else:
            clean_lines.append(line)
    return {"ok": completed.returncode == 0, "return_code": completed.returncode, "stdout": "\n".join(clean_lines), "stderr": stderr, "result": result}
