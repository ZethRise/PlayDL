import asyncio
from pathlib import Path


class CommandError(RuntimeError):
    pass


DEFAULT_COMMAND_TIMEOUT = 900


async def run_command(
    command: str,
    cwd: Path | None = None,
    timeout: int = DEFAULT_COMMAND_TIMEOUT,
) -> str:
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise CommandError(f"Command timed out after {timeout}s: {command}") from exc

    if process.returncode != 0:
        message = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
        raise CommandError(message or f"Command failed with exit code {process.returncode}")
    return stdout.decode(errors="replace").strip()


async def run_process(
    args: list[str],
    cwd: Path | None = None,
    timeout: int = DEFAULT_COMMAND_TIMEOUT,
) -> str:
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        command = " ".join(args)
        raise CommandError(f"Command timed out after {timeout}s: {command}") from exc

    if process.returncode != 0:
        message = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
        raise CommandError(message or f"Command failed with exit code {process.returncode}")
    return stdout.decode(errors="replace").strip()
