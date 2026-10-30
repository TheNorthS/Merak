"""One public label projection shared by deterministic figures and their gate."""

import re
from typing import Any


def public_mechanism_overrides(asset: dict[str, Any], objects: list[dict[str, Any]]) -> dict[str, str]:
    mechanisms = [item for item in (asset.get("method_brief") or {}).get("mechanism_nodes") or []
                  if isinstance(item, dict) and str(item.get("id") or "").strip()]
    labels = {}
    for obj in objects:
        identity = str(obj["id"])
        matches = [item for item in mechanisms if re.match(
            rf"^{re.escape(str(item['id']))}(?:$|[_-])", identity, flags=re.IGNORECASE,
        ) or re.match(rf"^{re.escape(str(item['id']))}\s+", str(obj.get("label") or ""), re.IGNORECASE)]
        if len(matches) != 1:
            continue
        public = " ".join(str(matches[0].get("publication_name") or matches[0].get("name") or "").split())
        if public and public.casefold() != " ".join(str(obj["label"]).split()).casefold():
            labels[identity] = public
    return labels


def public_scene_text(asset: dict[str, Any], obj: dict[str, Any], overrides: dict[str, str]) -> str:
    """Project explicit contract IDs and lifecycle suffixes into provenance, not glyph text."""
    identity = str(obj["id"])
    text = overrides.get(identity) or " ".join(str(obj["label"]).split())
    known_ids = {str(value) for value in asset.get("claim_ids") or []}
    known_ids.update(str(item.get("id") or "") for item in (asset.get("method_brief") or {}).get("mechanism_nodes") or [])
    if known_ids - {""}:
        identifiers = "|".join(re.escape(key) for key in sorted(known_ids - {""}, key=lambda key: (-len(key), key)))
        text = re.sub(rf"^(?:{identifiers})(?:/(?:{identifiers}))*\s+", "", text)
    for key in asset.get("claim_ids") or []:
        text = re.sub(rf"\b{re.escape(str(key))}\s+(?=[A-Za-z])", "", text)
    if obj.get("kind") in {"input", "sample", "population"}:
        # Input availability remains in source mappings and evidence records;
        # the method diagram labels the scientific input, not its acquisition state.
        text = re.sub(r";\s*pending\s*$", "", text, flags=re.IGNORECASE)
    # Preserve the exact authored label in element mappings. This suffix is
    # acquisition bookkeeping, not a mechanism or evidence claim in the diagram.
    return re.sub(r";\s*(?:acquisition|implementation|execution)\s+pending\s*$", "", text, flags=re.IGNORECASE)


def scene_label_parts(text: str) -> tuple[str, str]:
    """Split an authored qualifier or conjunction without removing scientific words."""
    if len(text) > 84:
        for separator in (" with ", " and "):
            if separator not in text:
                continue
            primary, qualifier = text.rsplit(separator, 1)
            if primary and qualifier and len(primary) <= 84:
                return primary, separator.strip() + " " + qualifier
    return text, ""


def projected_public_labels(asset: dict[str, Any]) -> dict[str, str]:
    from .figure_semantic_projection import project_figure_semantics

    objects = project_figure_semantics(asset)["entities_states_transformations"]
    overrides = public_mechanism_overrides(asset, objects)
    return {str(item["id"]): public_scene_text(asset, item, overrides) for item in objects}
