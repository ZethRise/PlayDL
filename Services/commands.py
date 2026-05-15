import asyncio
from pathlib import Path


class CommandError(RuntimeError):
    pass


async def run_command(command: str, cwd: Path | None = None) -> str:
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        message = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
        raise CommandError(message or f"Command failed with exit code {process.returncode}")
    return stdout.decode(errors="replace").strip()


async def run_process(args: list[str], cwd: Path | None = None) -> str:
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        message = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
        raise CommandError(message or f"Command failed with exit code {process.returncode}")
    return stdout.decode(errors="replace").strip()
