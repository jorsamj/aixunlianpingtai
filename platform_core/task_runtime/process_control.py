from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import psutil


def hash_command(argv: Sequence[str | os.PathLike[str]]) -> str:
    if isinstance(argv, (str, bytes)):
        raise TypeError("command must be an argv sequence")
    normalized = [str(value) for value in argv]
    encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


class ProcessIdentityMismatchError(PermissionError):
    """The PID exists but is not the exact process previously bound to a task."""


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    create_time: float
    command_hash: str


@dataclass(frozen=True)
class LaunchedProcess:
    process: subprocess.Popen
    identity: ProcessIdentity


def launch_process(
    argv: Sequence[str | os.PathLike[str]],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    **popen_options,
) -> LaunchedProcess:
    if isinstance(argv, (str, bytes)):
        raise TypeError("command must be an argv sequence")
    command = [str(value) for value in argv]
    if not command:
        raise ValueError("command argv must not be empty")
    if "shell" in popen_options:
        raise TypeError("shell is fixed to false; provide argv")

    options = dict(popen_options)
    options["shell"] = False
    if os.name == "nt":
        options["creationflags"] = int(options.get("creationflags", 0)) | int(
            subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(
        command,
        cwd=None if cwd is None else str(Path(cwd)),
        env=None if env is None else dict(env),
        **options,
    )
    observed = psutil.Process(process.pid)
    identity = ProcessIdentity(
        pid=process.pid,
        create_time=observed.create_time(),
        command_hash=hash_command(command),
    )
    return LaunchedProcess(process, identity)


class ProcessController:
    def inspect(self, identity: ProcessIdentity) -> psutil.Process:
        try:
            process = psutil.Process(int(identity.pid))
            observed_create_time = process.create_time()
            observed_hash = hash_command(process.cmdline())
        except (psutil.NoSuchProcess, psutil.ZombieProcess) as error:
            raise ProcessLookupError(identity.pid) from error
        except psutil.AccessDenied as error:
            raise PermissionError("process identity cannot be inspected") from error
        if (
            abs(observed_create_time - float(identity.create_time)) > 0.01
            or observed_hash != identity.command_hash
        ):
            raise ProcessIdentityMismatchError("process identity does not match")
        return process

    @staticmethod
    def _tree(root: psutil.Process) -> list[psutil.Process]:
        try:
            descendants = root.children(recursive=True)
        except psutil.NoSuchProcess:
            descendants = []
        except psutil.AccessDenied as error:
            # Never pretend an uninspectable tree has no children. That could
            # terminate only the launcher while leaving the real GPU/SDK child
            # alive and make the task look safe to recover.
            raise PermissionError("process tree cannot be inspected") from error
        return [*descendants, root]

    @staticmethod
    def _raise_access_denied(action: str, error: psutil.AccessDenied) -> None:
        raise PermissionError(f"process tree cannot be {action}") from error

    @classmethod
    def _execution_alive(cls, process: psutil.Process) -> bool:
        try:
            return process.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            return False
        except psutil.AccessDenied as error:
            cls._raise_access_denied("verified", error)
        return False

    def suspend_tree(self, identity: ProcessIdentity) -> None:
        root = self.inspect(identity)
        for process in reversed(self._tree(root)):
            if not self._execution_alive(process):
                continue
            try:
                process.suspend()
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied as error:
                self._raise_access_denied("suspended", error)

    def resume_tree(self, identity: ProcessIdentity) -> None:
        root = self.inspect(identity)
        for process in self._tree(root):
            if not self._execution_alive(process):
                continue
            try:
                process.resume()
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied as error:
                self._raise_access_denied("resumed", error)

    def _terminate_verified(
        self,
        processes: list[psutil.Process],
        *,
        timeout: float,
        label: str,
    ) -> None:
        active = [process for process in processes if self._execution_alive(process)]
        if not active:
            return
        for process in active:
            try:
                process.resume()
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied as error:
                self._raise_access_denied(f"resumed before {label} termination", error)
        for process in active:
            try:
                process.terminate()
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied as error:
                self._raise_access_denied(f"{label} terminated", error)
        _, alive = psutil.wait_procs(active, timeout=max(0.1, float(timeout)))
        alive = [process for process in alive if self._execution_alive(process)]
        if alive:
            # Preserve input order. For descendants this guarantees every known
            # executing child is handled before the root is ever touched by the
            # caller. A zombie is already non-executing and will be reaped after
            # its parent exits, so it must not block safe root termination.
            alive_pids = {process.pid for process in alive}
            ordered_alive = [process for process in active if process.pid in alive_pids]
            for process in ordered_alive:
                try:
                    process.kill()
                except psutil.NoSuchProcess:
                    continue
                except psutil.AccessDenied as error:
                    self._raise_access_denied(f"{label} killed", error)
            _, still_alive = psutil.wait_procs(
                ordered_alive,
                timeout=max(0.1, float(timeout)),
            )
            still_alive = [
                process for process in still_alive if self._execution_alive(process)
            ]
            if still_alive:
                raise PermissionError(f"{label} process termination could not be verified")

    def terminate_tree(self, identity: ProcessIdentity, timeout: float = 5.0) -> None:
        try:
            root = self.inspect(identity)
        except ProcessLookupError:
            return
        processes = self._tree(root)
        descendants = [process for process in processes if process.pid != root.pid]

        # The root remains alive until every descendant is verified non-executing.
        # If a child cannot be inspected/terminated, keeping the root alive lets
        # the repository continue proving the old execution exists. Zombie
        # descendants are already non-executing and are reaped when the root exits.
        self._terminate_verified(descendants, timeout=timeout, label="child")
        self._terminate_verified([root], timeout=timeout, label="root")
