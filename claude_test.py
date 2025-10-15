import argparse
import json
import os
import tempfile
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

from anthropic import Anthropic
from dotenv import load_dotenv

from autograder_test import run_autograder_zip
from claude_prompt import build_codeassist_prompt

load_dotenv() # Environment variables
client = Anthropic(
    api_key=os.environ["ANTHROPIC_API_KEY"],   # use ANTHROPIC_API_KEY
)

#--------- Upload Files ----------#
def UploadFiles ( path: Path, pattern: str ) :
    path = Path(path)
    uploaded_files = []
    # Find all files matching pattern
    for file in path.rglob(pattern):
        with open( file, "rb" ) as f:
            uploaded = client.beta.files.upload(
                file=(file.name, f, "text/plain"),
                extra_headers={"anthropic-beta": "files-api-2025-04-14"}, # Have to include this to work
            )
        uploaded_files.append(uploaded.id)

    return uploaded_files

def UploadAutograderResults(results: dict, filename: str = "autograder_results.json") -> str:
    """Upload full autograder results as a file to Claude Files API and return file_id."""
    serialized = json.dumps(results, indent=2)
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json", prefix="autograder_", delete=False) as tmp:
        tmp.write(serialized)
        tmp.flush()
        tmp_path = Path(tmp.name)
    try:
        with open(tmp_path, "rb") as f:
            # Only PDF and plaintext documents are supported for document blocks.
            # Upload as text/plain so it can be attached in a message.
            uploaded = client.beta.files.upload(
                file=(filename, f, "text/plain"),
                extra_headers={"anthropic-beta": "files-api-2025-04-14"},
            )
        return uploaded.id
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

def _singleton_root(extracted_dir: Path) -> Path:
    entries = [p for p in extracted_dir.iterdir()]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return extracted_dir

def UploadAutograderTests(zip_path: Path) -> list[str]:
    uploaded: list[str] = []
    with tempfile.TemporaryDirectory(prefix="autograder_tests_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmpdir_path)
        root = _singleton_root(tmpdir_path)
        uploaded.extend(UploadFiles(root, "*.py"))
    return uploaded

def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + "\n... [truncated]"

def _format_gradescope_section(gr: dict, budget: int) -> str:
    lines: list[str] = []
    score = gr.get("score")
    max_score = gr.get("max_score") or None
    exec_time = gr.get("execution_time")
    if score is not None:
        if max_score is not None:
            lines.append(f"Gradescope Score: {score}/{max_score}")
        else:
            lines.append(f"Gradescope Score: {score}")
    if exec_time is not None:
        lines.append(f"Execution Time: {exec_time}")
    tests = gr.get("tests") or []
    if tests:
        lines.append("Tests:")
        for t in tests:
            name = t.get("name", "(unnamed)")
            status = t.get("status", "unknown")
            tscore = t.get("score")
            tmax = t.get("max_score")
            header = f"- [{status}] {name}"
            if tscore is not None and tmax is not None:
                header += f" — {tscore}/{tmax}"
            elif tscore is not None:
                header += f" — {tscore}"
            lines.append(header)
            out = t.get("output")
            if isinstance(out, str) and out.strip():
                # indent output and truncate per-test to keep readable
                out_trunc = _truncate(out.strip(), max(200, min(1200, budget // max(1, len(tests)))))
                for ln in out_trunc.splitlines():
                    lines.append(f"  > {ln}")
    return "\n".join(lines)

def _parse_junit(xml_text: str) -> list[dict]:
    tests: list[dict] = []
    if not xml_text:
        return tests
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return tests

    for tc in root.iter("testcase"):
        classname = tc.attrib.get("classname", "")
        name = tc.attrib.get("name", "")
        time = tc.attrib.get("time", "")
        status = "passed"
        msg = ""
        err = tc.find("error")
        if err is not None:
            status = "error"
            msg = (err.attrib.get("message") or (err.text or "")).strip()
        fail = tc.find("failure")
        if fail is not None:
            status = "failed"
            msg = (fail.attrib.get("message") or (fail.text or "")).strip()
        skip = tc.find("skipped")
        if skip is not None:
            status = "skipped"
            if not msg:
                msg = (skip.attrib.get("message") or (skip.text or "")).strip()
        tests.append({
            "classname": classname,
            "name": name,
            "time": time,
            "status": status,
            "message": msg,
        })
    return tests

def _format_junit_section(junit_xml: str, budget: int) -> str:
    cases = _parse_junit(junit_xml)
    if not cases:
        return ""
    lines: list[str] = [f"JUnit Testcases ({len(cases)}):"]
    per_test_budget = max(120, min(800, budget // max(1, len(cases))))
    for c in cases:
        label = f"{c.get('classname','')}::{c.get('name','')}".strip(":")
        status = (c.get("status") or "unknown").upper()
        time = c.get("time") or ""
        header = f"- [{status}] {label}"
        if time:
            header += f" ({time}s)"
        lines.append(header)
        msg = c.get("message") or ""
        if msg:
            for ln in (msg if isinstance(msg, str) else str(msg)).splitlines():
                lines.append(f"  > {ln}")
    return "\n".join(lines)

def FormatAutograderResults(results: dict, limit: int = 12000) -> str:
    """Produce a compact, readable summary for the prompt, prioritizing test info."""
    parts: list[str] = []
    # Top-level return code / notes
    rc = results.get("returncode")
    note = results.get("note")
    if rc is not None:
        parts.append(f"Return code: {rc}")
    if note:
        parts.append(f"Note: {note}")

    # Prefer explicit gradescope-style results if available
    gr = results.get("gradescope_results")
    if isinstance(gr, dict):
        parts.append(_format_gradescope_section(gr, budget=limit // 2))
    elif isinstance(results.get("tests"), list):
        parts.append(_format_gradescope_section(results, budget=limit // 2))

    # Include explicit JUnit testcases list if present so users can see every test
    junit_xml = results.get("junit_xml") or ""
    junit_section = _format_junit_section(junit_xml, budget=limit // 2)
    if junit_section:
        parts.append(junit_section)

    # Add stdout/stderr tails
    stdout = results.get("stdout") or ""
    stderr = results.get("stderr") or ""
    if stdout:
        parts.append("Stdout (tail):\n" + _truncate(stdout, 2000))
    if stderr:
        parts.append("Stderr (tail):\n" + _truncate(stderr, 2000))

    # Fallback to raw JSON when little content was collected
    summary = "\n\n".join(p for p in parts if p)
    if not summary.strip():
        raw = json.dumps(results, indent=2)
        return _truncate(raw, limit)
    return _truncate(summary, limit)

def run_assignment_autograder(assignment_dir: Path, autograder_zip: Path) -> tuple[str, dict]:
    results = run_autograder_zip(
        zip_path=str(autograder_zip),
        student_dir=str(assignment_dir),
        timeout=180,
    )
    return FormatAutograderResults(results), results

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Claude review with autograder context.")
    parser.add_argument("--assignment", default="A4", help="Assignment folder inside assignment-examples/")
    parser.add_argument("--skip-upload-tests", action="store_true", help="Skip uploading autograder test files.")
    return parser.parse_args()

#--------- Claude Feedback ---------#
def ClaudeFeedback ( file_ids: list[str], prompt_text: str ) :
    content = [ { "type": "text", "text": prompt_text } ]

    # Add document block for each file id
    for f in file_ids:
        content.append({
            "type": "document",
            "source": { "type": "file", "file_id": f }
        })

    response = client.beta.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1200,
        messages=[{"role": "user", "content": content}],
        betas=["files-api-2025-04-14"],
    )

    return response

#--------- Delete All Uploaded Files ---------#
def DeleteAllFiles () :
    files_to_delete = []
    files = client.beta.files.list(extra_headers={"anthropic-beta": "files-api-2025-04-14"})
    for page in files:
        files_to_delete.append([page.filename, page.id])

    for f in files_to_delete:
        result = client.beta.files.delete(f[1],extra_headers={"anthropic-beta": "files-api-2025-04-14"})
        print(f"Filename: {f[0]}, Result: {result}")

#--------- Main ---------#
if __name__ == "__main__":
    args = parse_args()

    assignment_path = Path("assignment-examples") / args.assignment
    if not assignment_path.exists() or not assignment_path.is_dir():
        raise SystemExit(f"Assignment directory not found: {assignment_path}")

    autograder_zip = next(assignment_path.glob("*.zip"), None)
    if not autograder_zip:
        raise SystemExit(f"No autograder zip found in {assignment_path}")

    print(f"Running autograder for {assignment_path}...")
    autograder_results_text, raw_results = run_assignment_autograder(assignment_path, autograder_zip)
    print("Autograder completed with return code:", raw_results.get("returncode"))

    # Upload student code
    file_ids = UploadFiles(assignment_path, "*.py")
    print("Uploaded student files:", file_ids)

    if args.skip_upload_tests:
        test_file_ids: list[str] = []
    else:
        print("Uploading autograder tests for reference...")
        test_file_ids = UploadAutograderTests(autograder_zip)
        print("Uploaded autograder test files:", test_file_ids)

    # Upload full autograder results as a document so Claude can access 100% of details
    try:
        results_file_id = UploadAutograderResults(raw_results)
        print("Uploaded autograder results file:", results_file_id)
    except Exception as e:
        print("Warning: failed to upload autograder results file:", e)
        results_file_id = None

    all_file_ids = file_ids + test_file_ids + ([results_file_id] if results_file_id else [])

    print(autograder_results_text)

    # Build Prompt
    prompt = build_codeassist_prompt(
        assignment_description="",
        language="Python 3.11",
        autograder_results=autograder_results_text,
        past_coding_insights=[]
    )

    # Ask Claude
    response = ClaudeFeedback( all_file_ids, prompt )
    print(response)

    # Delete Uploaded Files
    DeleteAllFiles()
