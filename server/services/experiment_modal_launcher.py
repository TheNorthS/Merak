"""Generate the isolated Python entrypoint executed by Modal."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_LAUNCHER = '''import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import modal

app = modal.App(__APP_NAME__)
volume = modal.Volume.from_name(__VOLUME__, create_if_missing=True)
image = modal.Image.from_registry(__IMAGE__, add_python="3.11").add_local_dir(
    __SNAPSHOT__, remote_path="/workspace", copy=True
)

@app.function(
    gpu=__GPU__,
    timeout=__TIMEOUT__,
    image=image,
    volumes={"/merak-output": volume},
)
def execute():
    env = os.environ.copy()
    env.update(__ENV__)
    destination = Path("/merak-output") / __REMOTE_OUTPUT__ / "__ATTEMPT__"
    destination.mkdir(parents=True, exist_ok=True)
    log_path = destination / "train.log"
    if __HAS_PREFLIGHT__:
        preflight = subprocess.run(
            __PREFLIGHT__, shell=True, cwd="/workspace", env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        print(preflight.stdout or "", end="", flush=True)
        (destination / "preflight.log").write_text(preflight.stdout or "", encoding="utf-8")
        if preflight.returncode != 0:
            (destination / "status.json").write_text(
                json.dumps({"exit_code": preflight.returncode, "error": "Modal preflight failed"}),
                encoding="utf-8",
            )
            volume.commit()
            return {"exit_code": preflight.returncode, "error": "Modal preflight failed"}
    stop_telemetry = threading.Event()

    def emit_gpu_telemetry():
        while not stop_telemetry.wait(10):
            try:
                query = subprocess.run(
                    ["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used,memory.total,temperature.gpu", "--format=csv,noheader,nounits"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5,
                )
                gpus = []
                for line in (query.stdout or "").splitlines():
                    values = [item.strip() for item in line.split(",")]
                    if len(values) == 5:
                        gpus.append({
                            "index": int(values[0]),
                            "utilization_percent": int(values[1]),
                            "memory_used_mb": int(values[2]),
                            "memory_total_mb": int(values[3]),
                            "temperature_c": int(values[4]),
                        })
                print("MERAK_GPU:" + json.dumps({"gpus": gpus}), flush=True)
            except Exception as exc:
                print("MERAK_GPU:" + json.dumps({"gpus": [], "error": str(exc)}), flush=True)

    process = subprocess.Popen(
        __COMMAND__, shell=True, cwd="/workspace", env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    telemetry = threading.Thread(target=emit_gpu_telemetry, daemon=True)
    telemetry.start()
    last_commit = time.time()
    with log_path.open("a", encoding="utf-8") as log_handle:
        if process.stdout:
            for line in process.stdout:
                print(line, end="", flush=True)
                log_handle.write(line)
                log_handle.flush()
                if time.time() - last_commit >= 30:
                    volume.commit()
                    last_commit = time.time()
    exit_code = process.wait()
    stop_telemetry.set()
    telemetry.join(timeout=2)
    for relative in ("experiments/results", "experiments/logs"):
        source = Path("/workspace") / relative
        if source.exists():
            shutil.copytree(source, destination / relative, dirs_exist_ok=True)
    (destination / "status.json").write_text(
        json.dumps({"exit_code": exit_code, "finished_at": time.time()}), encoding="utf-8"
    )
    volume.commit()
    return {"exit_code": exit_code, "result_path": str(destination)}

@app.local_entrypoint()
def main():
    result = execute.remote()
    print("MERAK_RESULT:" + json.dumps(result), flush=True)
'''


def build_modal_launcher(
    spec: Any, snapshot_dir: Path, app_name: str, attempt_number: int
) -> str:
    replacements = {
        "__APP_NAME__": repr(app_name),
        "__VOLUME__": repr(spec.modal_volume),
        "__IMAGE__": repr(spec.modal_image),
        "__SNAPSHOT__": repr(str(snapshot_dir.resolve())),
        "__GPU__": repr(spec.gpu_type),
        "__TIMEOUT__": str(max(60, int(spec.timeout_seconds))),
        "__ENV__": repr(spec.env_vars),
        "__REMOTE_OUTPUT__": repr(spec.run_id),
        "__ATTEMPT__": f"attempt-{attempt_number:02d}",
        "__HAS_PREFLIGHT__": repr(bool(spec.preflight_command)),
        "__PREFLIGHT__": repr(spec.preflight_command),
        "__COMMAND__": repr(spec.command),
    }
    source = _LAUNCHER
    for marker, value in replacements.items():
        source = source.replace(marker, value)
    return source
