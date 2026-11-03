# AI Test-Generation Agent

A small agent that uses an LLM (Google Gemini) to **generate, run and validate
pytest unit tests for Python functions**. It is a focused exploration of
agentic AI applied to the software-testing part of the development lifecycle.

## What it does

For every top-level function in a target Python file, the agent:

1. **Parses** the file with the `ast` module and extracts the function source
   and its docstring.
2. **Generates** a pytest test with Gemini, based on the function's
   *documented* behaviour (the docstring), not on its implementation.
3. **Runs** the test with pytest in a sandboxed subprocess (hard timeout, a
   minimal environment that does **not** include the API key).
4. **Classifies** the result:
   - `PASS` — the function meets its documented behaviour.
   - `FUNCTION_BUG` — an assertion failed, so the function likely has a bug.
     The test is **kept unchanged** and the bug is reported.
   - `TEST_BROKEN` — the generated test has a syntax/collection error, so it is
     regenerated once with the error fed back to the model.
5. Writes a **JSON report** with the verdict and metrics (passed, bugs found,
   broken tests, attempts).

```
 target.py ──ast──> function + docstring ──Gemini──> pytest test
      └──────────── run (sandboxed) ── classify ── report.json
```

## Design decision: fix the code, not the test

A naive agent, when a test fails, asks the LLM to "fix the test". That is
wrong: if the failure is caused by a bug in the function, weakening the test to
make it pass hides the bug. This agent only regenerates a test when the **test
itself** is broken (syntax/collection error). When an **assertion** fails it
reports the function as buggy and never touches the test, so it can never get a
green result by weakening its own checks.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env               # then put your Gemini key in .env
python agent.py sample_code.py
```

`sample_code.py` ships with a deliberately buggy `is_even` so you can see the
agent catch a real bug (`FUNCTION_BUG`) while `add` and `factorial` pass.

## Safety note

`subprocess` is not a real sandbox. This prototype runs only your own, trusted
code, with a hard timeout and without exposing the API key to the test process.
Running untrusted code would require real isolation (e.g. a properly configured
container).

## Tech

Python · Google Gemini · pytest · subprocess · ast · JSON

## Roadmap

- v1 (this version): generate, run, classify, report.
- v2: when a `FUNCTION_BUG` is found, ask the LLM to fix the **function** and
  re-run the **same, frozen** tests to confirm the fix.
