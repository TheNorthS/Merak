import json

import pytest

from server.services.excalidraw_renderer import (
    ExcalidrawSceneError,
    normalize_scene,
)


def test_scene_normalization_binds_shapes_connectors_and_labels() -> None:
    scene = normalize_scene(json.dumps({"elements": [
        {"id": "source", "type": "rectangle", "x": 10, "y": 20, "text": "Input"},
        {"id": "target", "type": "rectangle", "x": 360, "y": 20, "text": "Output"},
        {"id": "flow", "type": "arrow", "startElementId": "source", "endElementId": "target"},
    ]}))

    elements = {item["id"]: item for item in scene["elements"]}
    assert elements["flow"]["startBinding"]["elementId"] == "source"
    assert elements["flow"]["endBinding"]["elementId"] == "target"
    assert elements["source-label"]["containerId"] == "source"
    assert elements["target-label"]["containerId"] == "target"


def test_scene_normalization_rejects_unbound_connector() -> None:
    with pytest.raises(ExcalidrawSceneError, match="needs two points"):
        normalize_scene(json.dumps({"elements": [
            {"id": "flow", "type": "arrow"},
        ]}))
