"""Run one real SWE-bench Lite sample with the oracle patch.

This is not FixPilot-generated patch evaluation yet. It validates the full
evaluation plumbing for one real SWE-bench instance:

1. clone real GitHub repo
2. checkout base_commit
3. apply SWE-bench test_patch
4. run FAIL_TO_PASS tests before oracle patch
5. apply SWE-bench oracle patch
6. run FAIL_TO_PASS tests again

The result is written to outputs/swebench_oracle/<case_name>/result.json.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "backend" / "test" / "fixtures" / "swebench_lite_rows_sample.json"
OUTPUT_ROOT = ROOT / "outputs" / "swebench_oracle"
DOCKER_IMAGE = "python:3.10-bullseye"


@dataclass
class CommandResult:
    command: list[str]
    exit_code: int
    duration_seconds: float
    stdout_tail: str
    stderr_tail: str


def run_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 600,
    env: dict[str, str] | None = None,
) -> CommandResult:
    started = time.perf_counter()
    process = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    stdout = process.stdout or ""
    stderr = process.stderr or ""
    return CommandResult(
        command=command,
        exit_code=process.returncode,
        duration_seconds=time.perf_counter() - started,
        stdout_tail=stdout[-4000:],
        stderr_tail=stderr[-4000:],
    )


def load_row(index: int) -> dict:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return payload["rows"][index]["row"]


def write_patch(path: Path, content: str) -> None:
    path.write_text(content.replace("\r\n", "\n"), encoding="utf-8")


def remove_tree(path: Path) -> None:
    """Remove a generated repository directory, including read-only git files.

    Git pack/index files can be read-only on Windows after clone or Docker use.
    The runner only calls this for its own output directory, so changing the
    writable bit here keeps repeated benchmark runs reliable without touching
    user-owned project files.
    """

    def make_writable_and_retry(func, failed_path, _exc_info):
        os.chmod(failed_path, stat.S_IWRITE)
        func(failed_path)

    shutil.rmtree(path, onexc=make_writable_and_retry)


def docker_mount_path(path: Path) -> str:
    return str(path.resolve())


def docker_test_command(fail_to_pass: list[str]) -> str:
    tests = " ".join(f'"{item}"' for item in fail_to_pass)
    return (
        "python -m pip install -q --upgrade 'pip<25' && "
        "python -m pip install -q "
        "'setuptools<60' "
        "wheel "
        "'setuptools_scm>=6.2,<8' "
        "'cython==0.29.22' "
        "extension-helpers "
        "pytest "
        "'pytest-astropy>=0.9' "
        "hypothesis "
        "'numpy==1.21.6' "
        "packaging "
        "pyerfa && "
        "CFLAGS='-Wno-error=incompatible-pointer-types -Wno-incompatible-pointer-types' "
        "SETUPTOOLS_USE_DISTUTILS=stdlib "
        "python -m pip install -q --no-build-isolation -e . && "
        f"python -m pytest -q {tests}"
    )


def extract_pytest_summary(output: str) -> str:
    """Extract the final pytest summary line from captured command output."""

    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if " passed in " in stripped or " failed in " in stripped:
            return stripped
    return ""


def run_docker_pytest(repo_dir: Path, fail_to_pass: list[str], timeout: int) -> CommandResult:
    docker_config = ROOT / ".docker-tmp"
    docker_config.mkdir(exist_ok=True)
    env = dict(os.environ)
    env["DOCKER_CONFIG"] = str(docker_config)
    return run_command(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{docker_mount_path(repo_dir)}:/work",
            "-w",
            "/work",
            DOCKER_IMAGE,
            "bash",
            "-lc",
            docker_test_command(fail_to_pass),
        ],
        timeout=timeout,
        env=env,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--keep", action="store_true")
    parser.add_argument(
        "--run-id",
        default="",
        help="Optional suffix for the output directory, useful on Windows when a previous Docker run leaves files locked.",
    )
    args = parser.parse_args()

    row = load_row(args.index)
    instance_id = row["instance_id"]
    case_name = instance_id if not args.run_id else f"{instance_id}_{args.run_id}"
    case_dir = OUTPUT_ROOT / case_name
    repo_dir = case_dir / "repo"
    result_path = case_dir / "result.json"
    case_dir.mkdir(parents=True, exist_ok=True)

    if repo_dir.exists() and not args.keep:
        remove_tree(repo_dir)

    results: dict[str, object] = {
        "instance_id": instance_id,
        "case_name": case_name,
        "repo": row["repo"],
        "base_commit": row["base_commit"],
        "fail_to_pass": json.loads(row["FAIL_TO_PASS"]),
        "steps": {},
        "complete": False,
    }

    try:
        if not repo_dir.exists():
            clone = run_command(
                [
                    "git",
                    "clone",
                    "--filter=blob:none",
                    f"https://github.com/{row['repo']}.git",
                    str(repo_dir),
                ],
                timeout=args.timeout,
            )
            results["steps"]["clone"] = asdict(clone)
            if clone.exit_code != 0:
                raise RuntimeError("git clone failed")

        checkout = run_command(["git", "checkout", row["base_commit"]], cwd=repo_dir)
        results["steps"]["checkout"] = asdict(checkout)
        if checkout.exit_code != 0:
            raise RuntimeError("git checkout failed")

        test_patch_path = case_dir / "test.patch"
        oracle_patch_path = case_dir / "oracle.patch"
        write_patch(test_patch_path, row["test_patch"])
        write_patch(oracle_patch_path, row["patch"])

        apply_test = run_command(["git", "apply", str(test_patch_path)], cwd=repo_dir)
        results["steps"]["apply_test_patch"] = asdict(apply_test)
        if apply_test.exit_code != 0:
            raise RuntimeError("apply test_patch failed")

        baseline = run_docker_pytest(
            repo_dir,
            json.loads(row["FAIL_TO_PASS"]),
            timeout=args.timeout,
        )
        results["steps"]["baseline_fail_to_pass"] = asdict(baseline)

        apply_oracle = run_command(["git", "apply", str(oracle_patch_path)], cwd=repo_dir)
        results["steps"]["apply_oracle_patch"] = asdict(apply_oracle)
        if apply_oracle.exit_code != 0:
            raise RuntimeError("apply oracle patch failed")

        oracle = run_docker_pytest(
            repo_dir,
            json.loads(row["FAIL_TO_PASS"]),
            timeout=args.timeout,
        )
        results["steps"]["oracle_fail_to_pass"] = asdict(oracle)

        baseline_summary = extract_pytest_summary(
            f"{baseline.stdout_tail}\n{baseline.stderr_tail}"
        )
        oracle_summary = extract_pytest_summary(
            f"{oracle.stdout_tail}\n{oracle.stderr_tail}"
        )
        results["complete"] = True
        results["baseline_pytest_summary"] = baseline_summary
        results["oracle_pytest_summary"] = oracle_summary
        results["baseline_failed_as_expected"] = (
            baseline.exit_code != 0 and " failed in " in baseline_summary
        )
        results["oracle_passed"] = (
            oracle.exit_code == 0 and " passed in " in oracle_summary
        )
        return 0 if oracle.exit_code == 0 else 2
    except Exception as exc:
        results["error"] = str(exc)
        return 1
    finally:
        result_path.write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(result_path)


if __name__ == "__main__":
    sys.exit(main())
