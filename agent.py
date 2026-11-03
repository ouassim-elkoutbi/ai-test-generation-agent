"""Agent that generates, runs and validates pytest tests for Python functions.

For each function it asks an LLM to write a test from the docstring, runs it,
and reports whether the function passes, has a bug, or the test was malformed.
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MODELS = [
    "gemini-3.8-flash",
    "gemini-flash-latest",
    "gemini-3.8-pro",
    "gemini-pro-latest",
]
PYTEST_TIMEOUT = 30


def extract_functions(source_path):
    source = Path(source_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            functions.append(
                (node.name, ast.get_source_segment(source, node), ast.get_docstring(node) or "")
            )
    return functions


def build_prompt(module_name, func_name, func_source, docstring, error=None):
    prompt = f"""You are a senior Python engineer writing pytest unit tests.

Write a pytest test for `{func_name}`, imported with
`from {module_name} import {func_name}`.

Base the test only on the documented behaviour below. Do not infer behaviour
from the implementation: if the implementation contradicts the docstring, the
test must follow the docstring so that a real bug is caught.

Cover a normal case, an edge case, and any error the docstring says is raised
(use pytest.raises). Return only the test code, no explanation or markdown.

Docstring:
\"\"\"{docstring}\"\"\"

Signature (for reference):
{func_source}
"""
    if error:
        prompt += f"\nThe previous test failed to run. Fix it. Error:\n{error}\n"
    return prompt


def clean_code(text):
    text = text.strip()
    fence = re.match(r"^```(?:python)?\s*(.*?)\s*```$", text, re.DOTALL)
    return fence.group(1).strip() if fence else text


def generate_test(prompt, retries_per_model=4):
    """Try each model in turn; retry on overload (503), skip on 404/quota."""
    from google import genai
    from google.genai import errors

    client = genai.Client(
        api_key=os.environ["GOOGLE_API_KEY"],
        http_options={"timeout": 120000},
    )
    last_error = None
    for model in MODELS:
        for attempt in range(retries_per_model):
            try:
                response = client.models.generate_content(model=model, contents=prompt)
                return clean_code(response.text), model
            except errors.ClientError as exc:
                last_error = exc
                print(f"   ({model} not available, trying next model...)")
                break
            except errors.ServerError as exc:
                last_error = exc
                wait = min(2 ** attempt, 15)
                print(f"   ({model} busy, retrying in {wait}s...)")
                time.sleep(wait)
    raise last_error


def run_pytest(test_path, module_dir):
    # Minimal env on purpose: the test process never sees GOOGLE_API_KEY.
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(module_dir)}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(test_path), "-q", "--no-header"],
            capture_output=True,
            text=True,
            timeout=PYTEST_TIMEOUT,
            cwd=str(module_dir),
            env=env,
        )
        return proc.returncode, proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return -1, f"TIMEOUT: test run exceeded {PYTEST_TIMEOUT}s"


def classify(returncode):
    # pytest: 0 passed, 1 assertion failed, 2 collection error, 5 no tests.
    if returncode == 0:
        return "PASS"
    if returncode == 1:
        return "FUNCTION_BUG"
    return "TEST_BROKEN"


def process_function(module_name, module_dir, tests_dir, name, source, docstring):
    test_path = Path(tests_dir) / f"test_{name}.py"
    error = None
    attempts = 0
    while True:
        attempts += 1
        prompt = build_prompt(module_name, name, source, docstring, error=error)
        test_code, model_used = generate_test(prompt)
        test_path.write_text(test_code, encoding="utf-8")

        returncode, output = run_pytest(test_path, module_dir)
        verdict = classify(returncode)

        # Only regenerate when the TEST is broken. A failed assertion means the
        # function is wrong, so we keep the test and report the bug.
        if verdict == "TEST_BROKEN" and attempts == 1:
            error = output[-1500:]
            continue
        break

    return {
        "function": name,
        "verdict": verdict,
        "attempts": attempts,
        "model": model_used,
        "test_file": test_path.name,
        "pytest_output": output.strip()[-1200:],
    }


def main():
    parser = argparse.ArgumentParser(description="AI Test-Generation Agent")
    parser.add_argument("target", help="Python file to generate tests for")
    parser.add_argument("--tests-dir", default="generated_tests")
    parser.add_argument("--report", default="report.json")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    if not os.environ.get("GOOGLE_API_KEY"):
        sys.exit("ERROR: set GOOGLE_API_KEY (in your environment or a .env file).")

    target = Path(args.target).resolve()
    module_dir = target.parent
    module_name = target.stem
    tests_dir = Path(args.tests_dir).resolve()
    tests_dir.mkdir(exist_ok=True)

    functions = extract_functions(target)
    print(f"Found {len(functions)} function(s) in {target.name}\n")

    results = []
    for name, source, docstring in functions:
        print(f"-> {name}: generating test...")
        result = process_function(module_name, module_dir, tests_dir, name, source, docstring)
        print(f"   [{result['verdict']}] {name} (attempts: {result['attempts']})")
        results.append(result)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": target.name,
        "models_available": MODELS,
        "total": len(results),
        "passed": sum(r["verdict"] == "PASS" for r in results),
        "bugs_found": sum(r["verdict"] == "FUNCTION_BUG" for r in results),
        "broken_tests": sum(r["verdict"] == "TEST_BROKEN" for r in results),
        "results": results,
    }
    Path(args.report).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"\nSummary: {summary['passed']} passed, {summary['bugs_found']} bug(s) found, "
        f"{summary['broken_tests']} broken test(s). Report written to {args.report}"
    )


if __name__ == "__main__":
    main()