"""Model authoring propagates errors; no synthetic replacement after failure."""
from __future__ import annotations

from .run_execution_context import RunExecutionContext


async def run_model_primary(ctx: RunExecutionContext, *, presentation: bool = False) -> None:
    async def operation() -> str:
        return await ctx.host._execute_node(
            ctx.node, ctx.run, ctx.research_direction, ctx.effort, ctx.assurance,
            wandb=False if presentation else ctx.wandb_enabled,
            compact=ctx.compact_mode,
            gpu_target="none" if presentation else ctx.opts.get("gpu_target", "local"),
            ssh_server_id="" if presentation else ctx.opts.get("ssh_server_id", ""),
            opts=ctx.opts,
        )
    # The agent owns the single bounded request retry budget. Starting another
    # whole node here would multiply retries and discard its conversation.
    ctx.result = await ctx.host._execute_with_model_transport_retry(
        run=ctx.run, node_id=ctx.node.id, operation_name=f"node/{ctx.node.id}",
        stage_id=ctx.node.id, operation=operation,
        opts={**ctx.opts, "model_transport_max_attempts": 1},
    )
