import json
from pathlib import Path

import pytest

from server.services.experiment_health import ExperimentHealthMonitor, HealthPolicy
from server.services.remote_experiment_runtime import (
    ExperimentRuntime,
    ProjectSnapshot,
    RunManifestStore,
    RuntimeOutcome,
    RuntimeSpec,
)
from server.services.sftp_service import SFTPService, sftp_service
from server.services.ssh_manager import SSHServerConfig, ssh_manager


class _RemoteHandle:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def seek(self, offset: int):
        self.offset = offset

    async def read(self, size: int = -1):
        if size < 0:
            size = len(self.data) - self.offset
        value = self.data[self.offset:self.offset + size]
        self.offset += len(value)
        return value


class _Attrs:
    def __init__(self, size: int):
        self.size = size


class _MemorySFTP:
    def __init__(self, files=None, corrupt_upload=False):
        self.files = dict(files or {})
        self.corrupt_upload = corrupt_upload

    async def stat(self, path):
        if path not in self.files:
            raise FileNotFoundError(path)
        return _Attrs(len(self.files[path]))

    def open(self, path, _mode):
        return _RemoteHandle(self.files[path])

    async def makedirs(self, _path, exist_ok=True):
        return None

    async def put(self, local_path, remote_path, preserve=True):
        data = Path(local_path).read_bytes()
        self.files[remote_path] = b"corrupt" if self.corrupt_upload else data

    def exit(self):
        return None


@pytest.mark.asyncio
async def test_sftp_incremental_offsets_and_truncation(monkeypatch):
    service = SFTPService()
    remote = _MemorySFTP({"/run/train.log": b"abc\nxyz"})

    async def get_sftp(_server_id):
        return remote

    monkeypatch.setattr(service, "_get_sftp", get_sftp)
    first, offset = await service.read_bytes("server", "/run/train.log", 0, max_bytes=4)
    second, offset = await service.read_bytes("server", "/run/train.log", offset, max_bytes=10)
    assert first == b"abc\n"
    assert second == b"xyz"
    assert offset == 7

    remote.files["/run/train.log"] = b"new"
    restarted, offset = await service.read_bytes("server", "/run/train.log", offset, max_bytes=10)
    assert restarted == b"new"
    assert offset == 3


@pytest.mark.asyncio
async def test_sftp_upload_rejects_hash_mismatch(tmp_path, monkeypatch):
    source = tmp_path / "train.py"
    source.write_text("print('trusted')\n", encoding="utf-8")
    service = SFTPService()
    remote = _MemorySFTP(corrupt_upload=True)

    async def get_sftp(_server_id):
        return remote

    monkeypatch.setattr(service, "_get_sftp", get_sftp)
    with pytest.raises(OSError, match="Hash mismatch"):
        await service.upload_file("server", source, "/run/train.py")


@pytest.mark.asyncio
async def test_ssh_lifecycle_syncs_tails_and_collects_verified_results(tmp_path, monkeypatch):
    (tmp_path / "train.py").write_text("print('ok')\n", encoding="utf-8")
    runtime = ExperimentRuntime()
    events = []
    offsets = []

    async def emit(event, payload):
        events.append((event, payload))

    async def noop(*_args, **_kwargs):
        return None

    async def precheck(_spec):
        return {"gpu": {"available": True, "gpus": [{"index": 0}]}}

    async def resolve(*_args):
        return "/remote/base"

    async def upload_directory(*_args, **_kwargs):
        return {"file_count": 1, "bytes": 12, "verified": True}

    async def upload_file(*_args, **_kwargs):
        return {"status": "uploaded"}

    async def read_bytes(_server, _path, offset, max_bytes):
        offsets.append(offset)
        if offset == 0:
            chunk = b'{"step": 1, "train/loss": 1.0}\n'
            return chunk, len(chunk)
        return b"", offset

    async def exists(*_args):
        return True

    async def read_file(*_args, **_kwargs):
        return json.dumps({"exit_code": 0})

    async def download_directory(*args, **_kwargs):
        remote_dir = str(args[1])
        return {
            "status": "downloaded",
            "file_count": 1,
            "bytes": 10,
            "verified": True,
            "remote_dir": remote_dir,
        }

    async def download_file(*_args, **_kwargs):
        return {"status": "downloaded", "verified": True}

    async def execute(_server, command, timeout=30):
        if "nohup setsid" in command:
            return "4321\n", "", 0
        return "", "", 0

    async def gpu_status(_server):
        return {"available": True, "gpus": [{"index": 0, "utilization_percent": 80}]}

    monkeypatch.setattr(runtime, "_ensure_ssh_connection", noop)
    monkeypatch.setattr(runtime, "_ssh_precheck", precheck)
    monkeypatch.setattr(runtime, "_resolve_remote_path", resolve)
    monkeypatch.setattr(sftp_service, "upload_directory", upload_directory)
    monkeypatch.setattr(sftp_service, "upload_file", upload_file)
    monkeypatch.setattr(sftp_service, "read_bytes", read_bytes)
    monkeypatch.setattr(sftp_service, "exists", exists)
    monkeypatch.setattr(sftp_service, "read_file", read_file)
    monkeypatch.setattr(sftp_service, "download_directory", download_directory)
    monkeypatch.setattr(sftp_service, "download_file", download_file)
    monkeypatch.setattr(ssh_manager, "execute", execute)
    monkeypatch.setattr(ssh_manager, "get_gpu_status", gpu_status)

    outcome = await runtime.run(RuntimeSpec(
        run_id="ssh-success",
        project_path=str(tmp_path),
        command="python train.py",
        backend="ssh_remote",
        server_id="verified-server",
        timeout_seconds=30,
        poll_interval_seconds=0.5,
    ), emit)

    assert outcome.status == "completed"
    assert offsets[0] == 0 and offsets[1] > 0
    assert any(event == "experiment_log" for event, _ in events)
    manifest = json.loads(Path(outcome.manifest_path).read_text(encoding="utf-8"))
    attempt = manifest["attempts"][0]
    assert attempt["transfers"]["results"]["verified"] is True
    assert attempt["transfers"]["logs"]["verified"] is True


@pytest.mark.asyncio
async def test_ssh_safe_stop_targets_process_group(monkeypatch):
    commands = []

    async def execute(_server, command, timeout=10):
        commands.append(command)
        return "", "", 0

    async def not_alive(_server, _pid):
        return False

    monkeypatch.setattr(ssh_manager, "execute", execute)
    monkeypatch.setattr(ExperimentRuntime, "_remote_process_alive", staticmethod(not_alive))
    await ExperimentRuntime._safe_stop_ssh("server", 9876)
    assert "kill -TERM -- -9876" in commands[0]
    assert not any("KILL" in command for command in commands)


@pytest.mark.asyncio
async def test_collection_failure_invalidates_remote_success(tmp_path, monkeypatch):
    runtime = ExperimentRuntime()
    spec = RuntimeSpec(
        run_id="collection-failure",
        project_path=str(tmp_path),
        command="python train.py",
        backend="ssh_remote",
        server_id="server",
    )
    store = RunManifestStore(tmp_path, spec.run_id)
    store.initialize(spec)
    store.begin_attempt(spec, "b" * 64)
    live_log = store.root / "attempt-01" / "train.log"
    live_log.parent.mkdir(parents=True, exist_ok=True)
    live_log.write_text("finished\n", encoding="utf-8")

    async def download_directory(_server, remote_dir, _local_dir, verify=True):
        if remote_dir.endswith("results"):
            raise OSError("result hash mismatch")
        return {"status": "downloaded", "file_count": 1, "bytes": 1, "verified": True}

    async def download_file(*_args, **_kwargs):
        return {"status": "downloaded"}

    monkeypatch.setattr(sftp_service, "download_directory", download_directory)
    monkeypatch.setattr(sftp_service, "download_file", download_file)
    outcome = await runtime._collect_and_finalize_ssh(
        spec,
        store,
        1,
        "completed",
        0,
        [],
        ExperimentHealthMonitor(HealthPolicy()),
        live_log,
        "/remote/workspace",
        "/remote/train.log",
        "",
        None,
    )

    assert outcome.status == "failed"
    assert "Artifact collection failed" in outcome.error
    assert any(item["kind"] == "artifact_collection_failed" for item in outcome.anomalies)


class _Response:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


class _FakeVastClient:
    def __init__(self):
        self.deleted = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, *_args, **_kwargs):
        return _Response(200, {"offers": [{
            "id": 77,
            "dph_total": 0.5,
            "gpu_name": "RTX 4090",
        }]})

    async def put(self, *_args, **_kwargs):
        return _Response(201, {"new_contract": 1234})

    async def delete(self, path, **_kwargs):
        self.deleted.append(path)
        return _Response(200)


@pytest.mark.asyncio
async def test_vast_instance_is_destroyed_when_remote_setup_fails(tmp_path, monkeypatch):
    import httpx

    fake_client = _FakeVastClient()
    monkeypatch.setenv("VASTAI_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: fake_client)
    runtime = ExperimentRuntime()

    async def wait_for_ssh(*_args, **_kwargs):
        return "vast.example", 22022

    async def fail_ssh(*_args, **_kwargs):
        raise RuntimeError("snapshot upload failed")

    async def disconnect(*_args, **_kwargs):
        return None

    monkeypatch.setattr(runtime, "_wait_for_vast_ssh", wait_for_ssh)
    monkeypatch.setattr(runtime, "_run_ssh", fail_ssh)
    monkeypatch.setattr(ssh_manager, "disconnect", disconnect)
    spec = RuntimeSpec(
        run_id="vast-cleanup",
        project_path=str(tmp_path),
        command="python train.py",
        backend="vast_ai",
        timeout_seconds=600,
        max_remote_cost_usd=10,
        vast_max_hourly_usd=1,
    )
    store = RunManifestStore(tmp_path, spec.run_id)
    store.initialize(spec)
    store.begin_attempt(spec, "c" * 64)
    snapshot = ProjectSnapshot(spec, store).build()

    with pytest.raises(RuntimeError, match="snapshot upload failed"):
        await runtime._run_vast(spec, store, snapshot, 1, None)
    assert fake_client.deleted == ["https://console.vast.ai/api/v0/instances/1234/"]


class _ModalStdout:
    def __init__(self, process, lines):
        self.process = process
        self.lines = list(lines)

    async def readline(self):
        if self.lines:
            return self.lines.pop(0)
        self.process.returncode = 0
        return b""


class _ModalProcess:
    def __init__(self, lines):
        self.pid = 321
        self.returncode = None
        self.stdout = _ModalStdout(self, lines)

    async def wait(self):
        self.returncode = 0
        return 0

    def terminate(self):
        self.returncode = 143

    def kill(self):
        self.returncode = 137


@pytest.mark.asyncio
async def test_modal_streams_gpu_metrics_and_recovers_volume(tmp_path, monkeypatch):
    import server.services.remote_experiment_runtime as runtime_module

    (tmp_path / "train.py").write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setenv("MODAL_TOKEN_ID", "token-id")
    monkeypatch.setenv("MODAL_TOKEN_SECRET", "token-secret")
    monkeypatch.setattr(runtime_module.shutil, "which", lambda _name: "modal")
    process = _ModalProcess([
        b'MERAK_GPU:{"gpus":[{"index":0,"utilization_percent":91}]}\n',
        b'{"step":1,"train/loss":0.9}\n',
        b'MERAK_RESULT:{"exit_code":0}\n',
    ])

    async def create_process(*_args, **_kwargs):
        return process

    recovered = []

    async def recover(*_args, **_kwargs):
        recovered.append(True)

    monkeypatch.setattr(runtime_module.asyncio, "create_subprocess_exec", create_process)
    runtime = ExperimentRuntime()
    monkeypatch.setattr(runtime, "_recover_modal_volume", recover)
    events = []

    async def emit(event, payload):
        events.append((event, payload))

    outcome = await runtime.run(RuntimeSpec(
        run_id="modal-success",
        project_path=str(tmp_path),
        command="python train.py",
        backend="modal",
        timeout_seconds=30,
        poll_interval_seconds=0.5,
    ), emit)

    assert outcome.status == "completed"
    assert recovered == [True]
    resource_events = [payload for event, payload in events if event == "experiment_resources"]
    assert resource_events[0]["gpus"][0]["utilization_percent"] == 91
    assert outcome.metrics["train/loss"] == 0.9


@pytest.mark.asyncio
async def test_active_ssh_attempt_is_reattached_without_duplicate_launch(tmp_path, monkeypatch):
    (tmp_path / "train.py").write_text("print('ok')\n", encoding="utf-8")
    runtime = ExperimentRuntime()
    spec = RuntimeSpec(
        run_id="ssh-reattach",
        project_path=str(tmp_path),
        command="python train.py",
        backend="ssh_remote",
        server_id="reattach-server",
        timeout_seconds=30,
        poll_interval_seconds=0.5,
    )
    store = RunManifestStore(tmp_path, spec.run_id)
    snapshot = ProjectSnapshot(spec, store).build()
    store.initialize(spec)
    store.begin_attempt(spec, snapshot["snapshot_hash"])
    store.update_attempt(1, status="monitor", pid=777, remote={
        "server_id": spec.server_id,
        "workspace": "/remote/workspace",
        "log_path": "/remote/train.log",
        "status_path": "/remote/status.json",
    })
    store.update(status="monitor", snapshot_hash=snapshot["snapshot_hash"])
    monkeypatch.setitem(ssh_manager._configs, spec.server_id, SSHServerConfig(
        id=spec.server_id,
        name="reattach",
        host="example.invalid",
    ))

    async def ensure(*_args, **_kwargs):
        return None

    async def monitor(*_args, **_kwargs):
        return RuntimeOutcome(
            run_id=spec.run_id,
            backend="ssh_remote",
            status="completed",
            manifest_path=str(store.path),
        )

    monkeypatch.setattr(runtime, "_ensure_ssh_connection", ensure)
    monkeypatch.setattr(runtime, "_monitor_ssh_process", monitor)
    events = []

    async def emit(event, payload):
        events.append((event, payload))

    outcome = await runtime.run(spec, emit)
    assert outcome.status == "completed"
    assert any(event == "experiment_reattached" for event, _ in events)
    assert len(store.load()["attempts"]) == 1
