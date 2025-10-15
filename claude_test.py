import argparse
import json
import os
import tempfile
import zipfile
from pathlib import Path

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

def FormatAutograderResults(results: dict, limit: int = 12000) -> str:
    """
    Serialize autograder output for the prompt, keeping the message compact.
    """
    serialized = json.dumps(results, indent=2)
    if len(serialized) <= limit:
        return serialized
    return serialized[:limit] + "\n... [truncated]"

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

    all_file_ids = file_ids + test_file_ids

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
