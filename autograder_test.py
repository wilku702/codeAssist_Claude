import subprocess, json, tempfile, shutil, sys, os
from pathlib import Path
from typing import Optional, Iterable

def _run(cmd, cwd: Path, timeout: int, env: Optional[dict] = None):
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )

def _make_exec(path: Path):
    if path.exists():
        try: path.chmod(path.stat().st_mode | 0o111)
        except Exception: pass

def _find_singleton_root(work: Path) -> Path:
    entries = [p for p in work.iterdir()]
    return entries[0] if (len(entries) == 1 and entries[0].is_dir()) else work

def _find_first(paths: Iterable[Path]) -> Optional[Path]:
    return next((p for p in paths if p.exists()), None)

def _install_requirements(root: Path, timeout: int, result: dict):
    candidates = list(root.glob("requirements*.txt")) + list(root.glob("requirements*.in"))
    if not candidates:
        candidates += list(root.glob("*/*/requirements*.txt")) + list(root.glob("*/*/requirements*.in"))
    req = _find_first(sorted(candidates, key=lambda p: len(p.parts)))
    if req:
        pip_cmd = [sys.executable, "-m", "pip", "install", "-r", str(req)]
    else:
        pip_cmd = [sys.executable, "-m", "pip", "install", "gradescope-utils", "pytest"]

    pip = _run(pip_cmd, cwd=root, timeout=timeout, env=os.environ.copy())
    result["pip_returncode"] = pip.returncode
    result["pip_stdout"] = pip.stdout[-4000:]
    result["pip_stderr"] = pip.stderr[-4000:]

def _collect_artifacts(root: Path, result: dict):
    js = list(root.rglob("results.json"))
    if js:
        try: result["gradescope_results"] = json.loads(js[0].read_text(errors="ignore"))
        except Exception as e: result["gradescope_results_error"] = str(e)
    xml = list(root.rglob("report.xml"))
    if xml:
        try: result["junit_xml"] = xml[0].read_text(errors="ignore")[-20000:]
        except Exception as e: result["junit_xml_error"] = str(e)

def _copy_student(src_dir: Path, dst_root: Path):
    for p in src_dir.rglob("*"):
        if p.is_file():
            dest = dst_root / p.relative_to(src_dir)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)

def _discover_tests(root: Path):
    """
    Return (tests_dir, test_files)
    - If a tests dir exists (shallowest), return it and empty file list.
    - Else return None and a non-empty list of discovered test files.
    """
    tests_dirs = sorted([p for p in root.rglob("tests") if p.is_dir()], key=lambda p: len(p.parts))
    if tests_dirs:
        return tests_dirs[0], []

    # No tests dir; collect explicit test files
    files = set()
    for pattern in ("test_*.py", "*_test.py"):
        for f in root.rglob(pattern):
            if f.is_file():
                files.add(f)
    # Prefer shallower files first for determinism
    files = sorted(files, key=lambda p: len(p.parts))
    return None, files

def run_autograder_zip(zip_path: str,
                       student_dir: Optional[str] = None,
                       timeout: int = 180) -> dict:
    work = Path(tempfile.mkdtemp(prefix="grader_"))
    result = {"returncode": None, "stdout": "", "stderr": ""}

    try:
        # 1) Unzip
        _run(["unzip", "-q", zip_path, "-d", str(work)], cwd=work, timeout=timeout, env=os.environ.copy())
        root = _find_singleton_root(work)

        # 2) Copy student code (optional)
        if student_dir:
            _copy_student(Path(student_dir), root)

        # 3) Install deps
        _install_requirements(root, timeout, result)

        # 4) Prefer entrypoints
        run_autograder = _find_first(sorted(root.rglob("run_autograder"), key=lambda p: len(p.parts)))
        setup_sh       = _find_first(sorted(root.rglob("setup.sh"), key=lambda p: len(p.parts)))
        run_tests_py   = _find_first(sorted(root.rglob("run_tests.py"), key=lambda p: len(p.parts)))

        # Ensure imports see the workspace
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root) + (os.pathsep + env.get("PYTHONPATH", ""))

        if run_autograder:
            _make_exec(run_autograder)
            proc = _run([str(run_autograder)], cwd=run_autograder.parent, timeout=timeout, env=env)
            result.update({"returncode": proc.returncode, "stdout": proc.stdout[-8000:], "stderr": proc.stderr[-8000:]})
            _collect_artifacts(root, result)
            return result

        if setup_sh and run_tests_py:
            _make_exec(setup_sh)
            s1 = _run(["bash", str(setup_sh)], cwd=setup_sh.parent, timeout=timeout, env=env)
            if s1.returncode != 0:
                result.update({"returncode": s1.returncode, "stdout": s1.stdout[-8000:], "stderr": s1.stderr[-8000:], "note": "setup.sh failed"})
                _collect_artifacts(root, result)
                return result
            t1 = _run([sys.executable, str(run_tests_py)], cwd=run_tests_py.parent, timeout=timeout, env=env)
            result.update({"returncode": t1.returncode, "stdout": t1.stdout[-8000:], "stderr": t1.stderr[-8000:]})
            _collect_artifacts(root, result)
            return result

        # 5) Fallback: discover tests anywhere; run them explicitly
        tests_dir, test_files = _discover_tests(root)
        if tests_dir:
            pytest_cwd = tests_dir
            cmd = ["pytest", "-q", "--disable-warnings", "--junitxml", "report.xml"]
        elif test_files:
            pytest_cwd = root
            # Pass explicit file list so pytest definitely runs something
            cmd = ["pytest", "-q", "--disable-warnings", "--junitxml", "report.xml"] + [str(p) for p in test_files]
        else:
            result.update({
                "returncode": 5,
                "stdout": "",
                "stderr": "No tests directory or test files found (patterns: tests/, test_*.py, *_test.py)."
            })
            return result

        proc = _run(cmd, cwd=pytest_cwd, timeout=timeout, env=env)
        result.update({"returncode": proc.returncode, "stdout": proc.stdout[-8000:], "stderr": proc.stderr[-8000:]})
        _collect_artifacts(root, result)
        return result

    finally:
        shutil.rmtree(work, ignore_errors=True)

# -------- Example --------
if __name__ == "__main__":
    # works for A1/A2/A3… just change the paths you pass
    res = run_autograder_zip(
        zip_path="assignment-examples/A2/A2.zip",
        student_dir="assignment-examples/A2",  # optional
        timeout=180
    )
    print(json.dumps(res, indent=2)[:20000])