"""Prepare and finalize one model-owned node around an isolated invocation."""

from __future__ import annotations

import json
from pathlib import Path
from ..contracts.entrypoints import parse_python_entrypoint
from ..agent import ModelRole, model_router
from ..agent.engine import agent_engine
from ..agent.prompts import (
    MERAK_SYSTEM_PROMPT,
    SLASH_COMMANDS,
)
from ..services.project_memory import project_memory
from ..services.skill_orchestrator import skill_orchestrator
from ..services.skill_registry import skill_registry
from .engine_context import LITERATURE_SOURCE_TOOLS, logger
from .effort_config import build_effort_prompt_section
from .node_agent_events import NodeAgentEventObserver
from .node_execution_context import NodeExecutionContext


class NodeExecutionComplete(Exception):
    def __init__(self, result: str):
        self.result = result


async def prepare_skill(ctx: NodeExecutionContext) -> None:
    ctx.opts = ctx.opts or {}
    ctx.project_path = ctx.run.project_path
    ctx.skill_plan = skill_orchestrator.select(
        ctx.node.id,
        ctx.node.skill,
        ctx.project_path,
        {**ctx.opts, "assurance": ctx.assurance, "effort": ctx.effort},
    )
    ctx.skill_trace_path = skill_orchestrator.record(
        ctx.project_path, ctx.run.id, ctx.skill_plan
    )
    await ctx.host._emit(
        ctx.run,
        "skill_plan_selected",
        {
            "node_id": ctx.node.id,
            "primary": ctx.skill_plan.primary,
            "specialists": ctx.skill_plan.specialists,
            "validators": ctx.skill_plan.validators,
            "registry_total": ctx.skill_plan.registry_total,
            "trace_path": str(ctx.skill_trace_path),
            "execution_kind": ctx.skill_plan.execution_kind,
            "runtime_service": ctx.skill_plan.runtime_service,
            "policy_required": ctx.skill_plan.policy_required,
        },
    )
    ctx.owner_skill_prompt = skill_orchestrator.render_owner(ctx.skill_plan)
    ctx.system_prompt = MERAK_SYSTEM_PROMPT
    if ctx.owner_skill_prompt:
        ctx.system_prompt += "\n\n" + ctx.owner_skill_prompt
    ctx.system_prompt += "\n\n" + skill_orchestrator.render_context(ctx.skill_plan)
    if not skill_registry.get_skill(ctx.skill_plan.primary):
        cmd_config = SLASH_COMMANDS.get(ctx.node.skill, {})
        if cmd_config.get("system_prompt_append"):
            ctx.system_prompt += (
                "\n\n## Current Task\n" + cmd_config["system_prompt_append"]
            )
    ctx.system_prompt += "\n\n" + ctx.host._canonical_output_contract_prompt(
        ctx.node.id, ctx.project_path
    )
    ctx.system_prompt += "\n\n" + build_effort_prompt_section(ctx.effort, ctx.assurance)
    if ctx.node.id == "exp-design":
        from ..contracts.evaluation import evaluation_authoring_contract
        ctx.system_prompt += "\n\n" + evaluation_authoring_contract()
        from ..contracts.implementation_readiness import readiness_instruction
        ctx.system_prompt += "\n\n" + readiness_instruction()
        from ..services.scheduler_authoring_contract import scheduler_authoring_instruction
        ctx.system_prompt += scheduler_authoring_instruction()


async def apply_runtime_options(ctx: NodeExecutionContext) -> None:
    if ctx.wandb:
        ctx.system_prompt += "\n\n## W&B Logging\nWhen the accepted implementation produces numeric computational runs, log declared metrics/estimands, configuration, provenance, and artifacts to Weights & Biases. Do not force W&B into physical, qualitative, or formal protocol steps that it cannot represent."
    if ctx.compact:
        ctx.system_prompt += "\n\n## Compact Mode\nBe concise. Only output final results, no intermediate reasoning. Skip verbose explanations."
    ctx.run_experiment = ctx.opts.get("run_experiment") is True
    ctx.gpu_info = ctx.opts.get("gpu_info", "")
    ctx.max_retries = ctx.opts.get("max_retries", 3)
    ctx.implementation_entrypoint = "experiments/src/train.py"
    ctx.implementation_family = "machine_learning"
    ctx.blueprint_path = (
        Path(ctx.project_path) / "experiments" / "IMPLEMENTATION_BLUEPRINT.json"
    )
    if ctx.blueprint_path.is_file():
        try:
            blueprint = json.loads(ctx.blueprint_path.read_text(encoding="utf-8-sig"))
            if isinstance(blueprint, dict):
                try:
                    declared_entrypoint = parse_python_entrypoint(
                        blueprint.get("entrypoint")
                    )
                except ValueError:
                    declared_entrypoint = None
                if declared_entrypoint and declared_entrypoint.path.as_posix().startswith("experiments/src/"):
                    ctx.implementation_entrypoint = declared_entrypoint.path.as_posix()
                ctx.implementation_family = (
                    str(
                        blueprint.get("implementation_family")
                        or ctx.implementation_family
                    )
                    .strip()
                    .casefold()
                )
        except (OSError, UnicodeError, json.JSONDecodeError):
            ctx.implementation_entrypoint = "experiments/src/run_analysis.py"
            ctx.implementation_family = "computational_general"
    ctx.ref_paper = ctx.opts.get("ref_paper", "")
    ctx.base_repo = ctx.opts.get("base_repo", "")


async def apply_research_options(ctx: NodeExecutionContext) -> None:
    ctx.research_strategy = ctx.host._normalize_research_strategy(
        ctx.opts.get("research_strategy", {})
    )
    if ctx.research_strategy:
        ctx.system_prompt += "\n\n" + ctx.host._build_research_strategy_prompt(
            ctx.research_strategy, ctx.node.id
        )
    ctx.research_mode = str(ctx.opts.get("research_mode") or "from_scratch")
    if ctx.research_mode == "paper_code_innovation":
        from .research_mode import build_innovation_system_prompt

        ctx.system_prompt += "\n\n" + build_innovation_system_prompt(
            ctx.node.id, ctx.project_path, ctx.opts
        )
    else:
        if ctx.ref_paper:
            ctx.system_prompt += f"\n\n## Optional Method/Writing Reference\nPath: {ctx.ref_paper}\nUse it only as a structural reference; it does not replace literature retrieval or novelty screening."
        if ctx.base_repo:
            ctx.system_prompt += f"\n\n## Optional Baseline Code\nPath: {ctx.base_repo}\nTreat the implementation as evidence to inspect, not as proof of a scientific claim."
    ctx.explicit_inputs = [
        entry
        for entry in ctx.run.input_baseline.get("entries") or []
        if isinstance(entry, dict) and entry.get("path")
    ]
    if ctx.explicit_inputs:
        input_lines = [
            f"- {entry['path']} ({entry.get('kind', 'file')}, sha256={str(entry.get('sha256') or '')[:16]})"
            for entry in ctx.explicit_inputs
        ]
        ctx.system_prompt += (
            "\n\n## Researcher-Selected Workflow Inputs\nThe researcher explicitly selected the following project artifacts. Read them before automatic discovery and treat their frozen hashes as authoritative input for this run:\n"
            + "\n".join(input_lines)
            + "\nDo not silently replace, rename, or delete these inputs. If the task requires changing one, report the conflict and require a new run so the updated file receives a new input snapshot."
        )
    if ctx.node.id in {"paper", "review", "audit", "compile", "ppt"}:
        from ..services.paper_budget import paper_budget_service

        budget = paper_budget_service.normalize(
            ctx.opts.get("target_pages", 0),
            ctx.opts.get("target_page_tolerance", 1),
            str(ctx.opts.get("target_venue") or ""),
        )
        budget_prompt = paper_budget_service.prompt(budget)
        if budget_prompt:
            ctx.system_prompt += "\n\n" + budget_prompt
    if not ctx.run_experiment:
        ctx.system_prompt += "\n\n## 研究执行模式：只实现与静态核验\n**用户选择不运行研究执行。** 你的任务是：\n1. 按研究类型生成完整的计算实现、分析协议、形式化检查器或可执行研究代码到 experiments/src/\n2. 检查语法、逻辑、依赖、研究设计和入口可达性\n3. 验证配置、路径、参数、分析单位、估计目标和证伪条件能够衔接\n4. **不要实际运行训练、数值实验、物理/临床流程或分析命令**\n5. 输出静态审查结果和预期执行方式\n6. 为主结论、机制必要性/敏感性、稳健性与失败分析定义领域适配的可替换数据 schema。\n   选择固定基准轨道时，完整分析已注册结果；科学正文应如实解释模拟/simulation/synthetic\n   数据生成方法、固定配置、统计定义和结论边界，不能仅用末尾披露替代可复现方法。\n   内部路径、运行身份和 preview 状态只保留在机器侧车，不增加水印或警告框；\n   论文组装器在 Conclusion 后、参考文献前加入一段统一仿真研究说明。"
    else:
        if ctx.gpu_info:
            if ctx.implementation_family == "machine_learning":
                ctx.system_prompt += f"\n\n## 计算环境\n用户的 GPU 环境: {ctx.gpu_info}\n请据此配置 batch size、模型规模和内存预算；显存不足时降低批量或采用梯度累积。"
            else:
                ctx.system_prompt += f"\n\n## 计算环境\n用户提供的计算环境: {ctx.gpu_info}\n仅按实际算法、模拟或验证需求配置并行度、内存和运行预算，不得引入无关的训练参数。"
        ctx.system_prompt += f"\n\n## 实验运行控制\n- 最大重试次数: {ctx.max_retries}（如果实验运行 {ctx.max_retries} 次都失败，跳过此节点并报告错误）"
        if ctx.gpu_target == "local":
            ctx.system_prompt += f"\n- 执行位置: 本地计算环境\n- 使用运行时调度器执行 `python {ctx.implementation_entrypoint}`\n- 只有实现和配置明确要求 CUDA 时才启用 GPU；不得把非 GPU 研究强行改写为训练任务"
        elif ctx.gpu_target == "remote" and ctx.ssh_server_id:
            ctx.system_prompt += f"\n\n## 远程实验执行配置\n- GPU Target: Remote SSH\n- Server ID: {ctx.ssh_server_id}\n\n**实验执行流程（严格遵循）：**\n1. 在本地 `experiments/src/` 编写实验代码（使用 Write 工具）\n2. 使用 `ssh_sync` 工具将本地代码同步到远程服务器\n3. 使用 `ssh_deploy` 工具在远程启动实验\n4. 使用 `ssh_exec` 工具监控实验状态\n5. 实验完成后，用 `ssh_exec` 将结果拉回本地\n\n**禁止**直接在远程服务器上通过 ssh_exec 写代码。"
        elif ctx.gpu_target == "vast":
            ctx.system_prompt += "\n- 执行位置: Vast.ai（自动分配 GPU 实例）"
        elif ctx.gpu_target == "modal":
            ctx.system_prompt += "\n- 执行位置: Modal serverless"
    if (
        ctx.node.id == "exp-design"
        and ctx.opts.get("staged_experiment_implementation") is True
    ):
        ctx.system_prompt += "\n\n## Staged implementation compiler — primary design pass\nThis primary session owns only EXPERIMENT_PLAN.md, RUN_SPEC.json,\nMETHOD_CONTRACT.json, configs/main.yaml, and IMPLEMENTATION_BLUEPRINT.json.\nDo not create or edit experiments/src/ in this session. After the frozen blueprint\nis written, the workflow launches isolated data, method, execution, evaluation,\nand integration implementation sessions. The integration session writes IMPLEMENTATION_EVIDENCE_PATCH.json; only the runtime\nmay finalize METHOD_CONTRACT.status after a passing integration verdict."
    try:
        from ..services.research_workflow_contract import (
            research_workflow_contract_service,
        )

        ctx.system_prompt += "\n\n" + research_workflow_contract_service.prompt(
            ctx.project_path, ctx.node.id, ctx.direction, ctx.opts
        )
    except Exception as exc:
        logger.warning(
            "Research contract prompt unavailable", node=ctx.node.id, error=str(exc)
        )


async def append_project_contract(ctx: NodeExecutionContext) -> None:
    from ..services.research_delivery_prompt import research_delivery_instruction
    ctx.system_prompt += research_delivery_instruction(ctx.opts)
    if ctx.node.id == 'ppt':
        from ..services.slide_authoring_contract import loaded_talk_instruction
        ctx.system_prompt += loaded_talk_instruction()
    ctx.system_prompt += f"\n\n## 项目路径与目录约定\n当前研究项目在: {ctx.project_path}\n\n**严格遵循以下目录约定，所有文件必须写入对应目录：**\n- `literature/` — 文献综述、BibTeX、下载的论文 PDF\n- `ideas/` — idea 列表、新颖性报告\n- `experiments/src/` — 实验代码\n- `experiments/configs/` — 实验配置（YAML/JSON）\n- `experiments/logs/` — 训练日志\n- `experiments/results/` — 真实实验结果数据、分析报告\n- `experiments/results/templates/` — 未运行实验时的空白计划数据 schema；所有测量字段必须由带溯源的真实运行结果填写\n- `paper/` — LaTeX 论文（main.tex, sections/）\n- `paper/tables/` — 论文表格源文件；计划结果表固定为 paper/tables/planned_result_templates.tex\n- `figures/plots/` — 数据图表（matplotlib 生成）\n- `figures/diagrams/` — 框架图（mermaid/tikz）\n- `slides/` — Beamer/PPT 演示文稿\n- `NARRATIVE_REPORT.md` — 工作流叙事报告，固定写在项目根目录\n- `misc/` — 不属于上述类别的文件\n\n**重要规则：**\n- 除 `NARRATIVE_REPORT.md` 外，**禁止**在项目根目录直接创建文件，其他输出必须放入对应子目录\n- **必须使用 `Write` 工具写入文件**，不要使用 Bash 的 echo/cat 写文件（Windows 不兼容）\n- 如果文件内容很长，也用 `Write`，不要拆分成多次 Bash 命令\n- 创建目录用 `Write` 写一个文件即可（会自动创建父目录）\n- 读取前先使用节点输入中提供的“已发现文件”清单；不在清单中的文件先用 Glob 发现，禁止猜测路径后逐个 Read\n- 特别禁止把 experiments/results/templates/ 下的文件误读成 experiments/results/ 根目录文件，或把 paper/tables/ 下的文件误读成 paper/ 根目录文件"
    ctx.memory_context = project_memory.get_context_for_agent(ctx.project_path)
    if ctx.memory_context:
        ctx.system_prompt += f"\n\n{ctx.memory_context}"


async def open_primary_session(ctx: NodeExecutionContext) -> None:
    ctx.recovery_session_id = ctx.host._interrupted_primary_session_id(
        ctx.node, ctx.run
    )
    ctx.session = None
    ctx.session_rehydrated = False
    if ctx.recovery_session_id:
        from .primary_session_resume import restore_primary_session
        ctx.session = restore_primary_session(agent_engine,
            ctx.recovery_session_id, ctx.project_path, system_prompt=ctx.system_prompt
        )
        ctx.session_rehydrated = ctx.session is not None
    if ctx.session is None:
        ctx.session = agent_engine.create_session(
            system_prompt=ctx.system_prompt, role=ModelRole.EXECUTOR
        )
    ctx.session.project_path = ctx.project_path
    ctx.session.readonly_roots = skill_orchestrator.readonly_reference_roots(
        ctx.skill_plan.primary
    )
    ctx.session.context_key = f"skill-chain:{ctx.skill_plan.primary}"
    ctx.session.workflow_node_id = ctx.node.id
    ctx.session.tool_policy = "workflow_artifacts"
    ctx.host._configure_agent_limits(
        ctx.session, ctx.node.id, ctx.effort, ctx.project_path
    )
    ctx.node.session_id = ctx.session.id
    if ctx.session_rehydrated:
        await ctx.host._emit(
            ctx.run,
            "agent_session_rehydrated",
            {
                "node_id": ctx.node.id,
                "skill": ctx.skill_plan.primary,
                "session_id": ctx.session.id,
                "recovery_count": ctx.session.recovery_count,
                "message": "已恢复原 Agent 会话；先核对已有产物与工具结果，再继续未完成的工作。",
            },
        )


async def prepare_primary_message(ctx: NodeExecutionContext) -> None:
    skill_orchestrator.mark_execution(
        ctx.project_path,
        ctx.run.id,
        ctx.node.id,
        ctx.skill_plan.primary,
        "running",
        role="primary",
        session_id=ctx.session.id,
        policy_loaded=bool(ctx.owner_skill_prompt),
        execution_kind=ctx.skill_plan.execution_kind,
    )
    await ctx.host._emit(
        ctx.run,
        "skill_invocation_started",
        {
            "node_id": ctx.node.id,
            "skill": ctx.skill_plan.primary,
            "role": "primary",
            "session_id": ctx.session.id,
        },
    )
    ctx.user_message = ctx.host._build_node_input(ctx.node, ctx.direction, ctx.run)
    if ctx.session_rehydrated:
        ctx.user_message = (
            "Resume the interrupted workflow-node attempt from the durable transcript. Inspect the latest canonical artifacts before acting. Do not repeat completed searches, writes, deployments, or experiments; continue only the unfinished work and then verify the required outputs.\n\n"
            + ctx.user_message
        )
    if ctx.revision_context:
        ctx.user_message += (
            "\n\n## Independent Acceptance Gate: Mandatory Revision\n"
            + ctx.revision_context.strip()
        )
    if ctx.run.checkpoint_feedback and ctx.run.checkpoint_node_id == ctx.node.id:
        ctx.user_message += (
            "\n\n## 人工检查点反馈（必须优先遵循）\n"
            + ctx.run.checkpoint_feedback.strip()
            + "\n请把这些调整意见落实到当前节点产物中；若与原计划冲突，以该反馈为准。"
        )
        ctx.run.checkpoint_feedback = ""
        ctx.run.checkpoint_node_id = ""


async def configure_reviewer_session(ctx: NodeExecutionContext) -> None:
    if ctx.node.skill == "/auto-review-loop":
        reviewer_sys = MERAK_SYSTEM_PROMPT
        if ctx.owner_skill_prompt:
            reviewer_sys += "\n\n" + ctx.owner_skill_prompt
        reviewer_sys += "\n\n" + skill_orchestrator.render_context(ctx.skill_plan)
        reviewer_sys += "\n\nYou are a rigorous scientific reviewer for a top venue appropriate to the manuscript's declared research domain.\nYour task: critically review the research paper, identify weaknesses, and iteratively improve it.\n\nAvailable tools: Read (read files), Write (overwrite file), Edit (targeted edits), Glob (list files).\n\nReview process:\n1. Read paper/main.tex and the frozen research/evidence contracts.\n2. Assign an Overall Score (1-10) with strengths, weaknesses, and concrete action items.\n3. If score < 6 or the verdict is not ready/almost, make evidence-preserving revisions,\n   then re-read and re-score. Never improve a score by strengthening an unsupported claim.\n4. Repeat for at most 3 internal rounds.\n5. Persist review-stage/REVIEW_STATE.json. It must contain final_score,\n   final_verdict, reviewer_model, executor_model, and a non-empty rounds array. Every\n   round records score, verdict, strengths, weaknesses, and action_items.\n6. Output the same final score/verdict only after the JSON state has been written.\n\nA score printed in prose is not accepted as review evidence. Unresolved critical\nscientific issues must remain visible in the state and keep the verdict below almost."
        from ..services.research_workflow_contract import (
            research_workflow_contract_service,
        )

        reviewer_sys += "\n\n" + research_workflow_contract_service.prompt(
            ctx.project_path, ctx.node.id, ctx.direction, ctx.opts
        )
        if ctx.research_strategy:
            reviewer_sys += "\n\n" + ctx.host._build_research_strategy_prompt(
                ctx.research_strategy, ctx.node.id
            )
        if ctx.research_mode == "paper_code_innovation":
            from .research_mode import build_innovation_system_prompt

            reviewer_sys += "\n\n" + build_innovation_system_prompt(
                ctx.node.id, ctx.project_path, ctx.opts
            )
        from ..services.paper_budget import paper_budget_service

        reviewer_budget = paper_budget_service.normalize(
            ctx.opts.get("target_pages", 0),
            ctx.opts.get("target_page_tolerance", 1),
            str(ctx.opts.get("target_venue") or ""),
        )
        if reviewer_budget:
            reviewer_sys += "\n\n" + paper_budget_service.prompt(reviewer_budget)
        from ..agent import Message as _Msg

        ctx.session.messages = [m for m in ctx.session.messages if m.role != "system"]
        ctx.session.messages.insert(0, _Msg(role="system", content=reviewer_sys))
        try:
            reviewer = model_router.get_provider(ModelRole.REVIEWER)
            executor_provider = model_router.get_provider(ModelRole.EXECUTOR)
            if reviewer is not executor_provider:
                ctx.session.model_role = ModelRole.REVIEWER
        except RuntimeError:
            pass


async def attach_observer(ctx: NodeExecutionContext) -> None:
    ctx.observer = NodeAgentEventObserver(
        ctx.host,
        ctx.run,
        ctx.node,
        ctx.session,
        skill_orchestrator,
        set(LITERATURE_SOURCE_TOOLS.values()),
    )
    ctx.search_tool_trace = ctx.observer.state.search_tool_trace
    ctx.flush_agent_text = ctx.observer.flush


async def resolve_tools(ctx: NodeExecutionContext) -> None:
    ctx.disabled_tools = ctx.host._workflow_disabled_tools(ctx.opts)
    ctx.all_tool_names = list(agent_engine._tools.keys())
    ctx.blocked_execution_tools = {"Bash", "ssh_exec", "ssh_deploy", "ssh_sync"}
    if ctx.node.skill == "/auto-review-loop":
        ctx.enabled_tools = [
            tool_name
            for tool_name in ("Read", "Write", "Edit", "Glob", "Grep", "reviewer_api")
            if tool_name in ctx.all_tool_names and tool_name not in ctx.disabled_tools
        ]
    else:
        declared_tools = skill_registry.resolve_allowed_tools(
            ctx.skill_plan.primary, ctx.all_tool_names
        )
        stage_required_tools = ctx.host._workflow_stage_required_tools(
            ctx.node, ctx.project_path, ctx.skill_plan, ctx.opts
        )
        missing_required_tools = sorted(stage_required_tools - set(ctx.all_tool_names))
        if missing_required_tools:
            raise RuntimeError(
                f"WORKFLOW_TOOL_CONTRACT_ERROR: node {ctx.node.id} cannot produce its canonical artifacts because required runtime tools are unavailable: {', '.join(missing_required_tools)}"
            )
        allowed = {*declared_tools, *stage_required_tools}
        ctx.enabled_tools = [
            tool_name
            for tool_name in ctx.all_tool_names
            if (not declared_tools or tool_name in allowed)
            and tool_name not in ctx.disabled_tools
        ]
        if ctx.node.id != "exp-run" or not ctx.run_experiment:
            ctx.enabled_tools = [
                t for t in ctx.enabled_tools if t not in ctx.blocked_execution_tools
            ]
        ctx.enabled_tools = ctx.host._filter_literature_source_tools(
            ctx.node.id, ctx.opts, ctx.enabled_tools
        )
    ctx.source_tool_contract = ctx.host._literature_source_tool_contract(
        ctx.node.id, ctx.opts
    )
    await ctx.host._emit(
        ctx.run,
        "workflow_tool_contract_resolved",
        {
            "node_id": ctx.node.id,
            "owner_skill": ctx.skill_plan.primary,
            "enabled_tools": ctx.enabled_tools,
            "selected_sources": list(ctx.source_tool_contract),
            "source_tools": ctx.source_tool_contract,
        },
    )
    ctx.search_context = await ctx.host._ensure_stage_search_evidence(
        ctx.run, ctx.node, ctx.direction, ctx.opts, ctx.enabled_tools
    )
    if ctx.search_context:
        ctx.user_message += (
            "\n\n## Platform-observed source retrieval\nMERAK executed the selected source tools before synthesis. Use these results for the current stage and do not claim that retrieval was skipped.\n"
            + ctx.search_context
        )


async def finalize_primary(ctx: NodeExecutionContext) -> None:
    await ctx.flush_agent_text(True)
    ctx.search_evidence_path = ctx.host._persist_search_evidence(
        ctx.run, ctx.node, ctx.opts, ctx.enabled_tools, ctx.search_tool_trace
    )
    if ctx.search_evidence_path:
        await ctx.host._emit(
            ctx.run,
            "literature_search_evidence",
            {
                "node_id": ctx.node.id,
                "artifact": str(ctx.search_evidence_path),
                "selected_sources": list(ctx.source_tool_contract),
            },
        )
    incomplete = ctx.completion_mode == "artifact_incomplete"
    skill_orchestrator.mark_execution(
        ctx.project_path,
        ctx.run.id,
        ctx.node.id,
        ctx.skill_plan.primary,
        "incomplete" if incomplete else "completed",
        role="primary",
        session_id=ctx.session.id,
        output=ctx.result,
        policy_loaded=bool(ctx.owner_skill_prompt),
        execution_kind=ctx.skill_plan.execution_kind,
        model_provider=ctx.observer.state.model_provider_used,
        model_name=ctx.observer.state.model_name_used,
        completion_mode=ctx.completion_mode,
    )
    await ctx.host._emit(
        ctx.run,
        "skill_invocation_incomplete" if incomplete else "skill_invocation_completed",
        {
            "node_id": ctx.node.id,
            "skill": ctx.skill_plan.primary,
            "role": "primary",
            "session_id": ctx.session.id,
            "completion_mode": ctx.completion_mode,
        },
    )
    if incomplete:
        return
    if ctx.node.id == "narrative":
        from ..services.scientific_narrative import scientific_narrative_service
        scientific_narrative_service.record_existing(ctx.project_path, generator="model-authored:narrative-node")
    await ctx.host._execute_stage_delegates(
        node=ctx.node,
        run=ctx.run,
        direction=ctx.direction,
        effort=ctx.effort,
        assurance=ctx.assurance,
        opts=ctx.opts,
    )
