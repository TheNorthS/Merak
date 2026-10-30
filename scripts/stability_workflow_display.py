"""Open the isolated project normally and inspect the real workflow controls."""

import asyncio
import json
from pathlib import Path
import time

from scripts.stability_package_runtime import write_json


async def show_project(runtime, project: Path) -> None:
    await runtime.desktop.evaluate(
        "(async () => { await window.merakIDE.appState.set('projectPath', PROJECT); "
        "setTimeout(() => location.reload(), 50); return true; })()".replace("PROJECT", json.dumps(str(project)))
    )
    await asyncio.sleep(2)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            opened = await runtime.desktop.evaluate("""(() => {
                const button = Array.from(document.querySelectorAll('button')).find(item =>
                    item.textContent.trim() === '工作流' || item.getAttribute('title') === '工作流'
                    || item.getAttribute('aria-label') === '工作流');
                if (!button) return false;
                button.click(); return true;
            })()""", timeout=5)
            if opened:
                return
        except (RuntimeError, TimeoutError):
            pass
        await asyncio.sleep(1)
    raise RuntimeError("Packaged renderer could not open the project's workflow panel")


async def verify_terminal_display(runtime, status: str, output: Path) -> dict:
    await asyncio.sleep(5)
    controls = await runtime.desktop.evaluate("""(() => {
        const buttons = Array.from(document.querySelectorAll('button')).map(item => item.textContent.trim());
        return {stop_visible: buttons.includes('停止'), resume_visible: buttons.includes('恢复执行'),
            interrupted_visible: document.body.innerText.includes('已中断'),
            completed_visible: document.body.innerText.includes('已完成'),
            password_form: !!document.querySelector('input[type=password]')};
    })()""")
    accepted = not controls["stop_visible"] and not controls["password_form"]
    if status in {"incomplete", "failed", "cancelled"}:
        accepted = accepted and controls["resume_visible"]
    receipt = {"accepted": accepted, "backend_status": status, **controls}
    write_json(output / "workflow-display.json", receipt)
    return receipt
