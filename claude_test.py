import os
from pathlib import Path
from anthropic import Anthropic
from dotenv import load_dotenv
from claude_prompt import build_codeassist_prompt

load_dotenv() # Environment variables
client = Anthropic(
    api_key=os.environ["ANTHROPIC_API_KEY"],   # use ANTHROPIC_API_KEY
)

#--------- Upload Files ----------#
def UploadFiles ( path: str, pattern: str ) :
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
    # Upload student code
    assignment_path = Path("assignment-examples/A4")
    file_ids = UploadFiles(assignment_path, "*.py")
    print(file_ids)

    # Build Prompt
    prompt = build_codeassist_prompt(
        assignment_description="",
        language="Python 3.11",
        autograder_results='{"": ""}',
        past_coding_insights=[]
    )

    # Ask Claude
    response = ClaudeFeedback( file_ids, prompt )
    print(response)

    # Delete Uploaded Files
    DeleteAllFiles()