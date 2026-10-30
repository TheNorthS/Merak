"""Capability evidence consists of reached operations, never variable names or prose."""
import ast
import re


def source_capabilities(source: str) -> dict[str, bool]:
    tree = ast.parse(source)
    calls = {
        ast.unparse(node.func).casefold() for node in ast.walk(tree) if isinstance(node, ast.Call)
    }
    def calls_matching(pattern: str) -> bool:
        return any(re.search(pattern, name) for name in calls)

    return {
        "data_loading": calls_matching(r"(?:dataloader|dataset|dictreader|load_(?:\w+_)?(?:data|manifest)|read_(?:csv|parquet|json)|(?:np|numpy)\.load)$"),
        "model_forward": calls_matching(r"(?:^model|\.forward|predict|\.apply)$"),
        "objective": calls_matching(r"(?:loss|criterion|cross_entropy|objective|nt_xent)$"),
        "optimization": calls_matching(r"(?:\.backward|optimizer\.step|train_on_batch|\.fit)$"),
        "evaluation": calls_matching(r"(?:^evaluate(?:_\w+)?|\.predict|^predict|accuracy|auroc|f1_score|mean_squared_error|compute_metrics)$"),
        "persistence": calls_matching(r"(?:torch\.save|save_checkpoint|\.to_csv|\.to_parquet|json\.dump|\.write_text|\.write_bytes|np\.save|numpy\.save)$"),
        "iteration": any(isinstance(node, (ast.For, ast.AsyncFor, ast.While, ast.comprehension)) for node in ast.walk(tree)),
    }
