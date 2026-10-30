"""
Skill 输入参数 Schema

每个 skill 声明自己需要的输入参数，供前端动态渲染表单。
当用户单独执行某个 skill 时，按 schema 收集参数。
当 workflow 自动串联时，这些参数由前序节点 output 自动填充。
"""

from typing import Optional


# 字段类型: text, textarea, number, select, multiselect, filepath
SKILL_INPUT_SCHEMAS: dict[str, dict] = {
    # ==================== Literature & Search ====================
    "research-lit": {
        "fields": [
            {"name": "query", "type": "text", "label": "搜索关键词 / 研究方向", "required": True, "placeholder": "e.g. LLM reasoning chain-of-thought"},
            {"name": "max_papers", "type": "number", "label": "最大论文数", "default": 35, "min": 5, "max": 100},
            {"name": "year_from", "type": "number", "label": "起始年份", "default": 2020},
            {"name": "databases", "type": "multiselect", "label": "搜索数据库", "options": ["arxiv", "semantic_scholar", "openalex", "pubmed", "web"], "default": ["arxiv", "semantic_scholar"]},
            {"name": "focus_areas", "type": "text", "label": "关注子领域（逗号分隔）", "placeholder": "e.g. prompting, fine-tuning, evaluation"},
        ],
        "requires": ["query"],
        "atomic": False,
        "atomic_group": None,
    },

    "novelty-check": {
        "fields": [
            {"name": "idea_description", "type": "textarea", "label": "Idea 描述", "required": True, "placeholder": "描述你的研究 idea..."},
            {"name": "related_papers", "type": "textarea", "label": "已知相关论文（可选）", "placeholder": "每行一篇: 标题 (年份)"},
        ],
        "requires": ["idea_description"],
        "atomic": False,
        "atomic_group": None,
    },

    # ==================== Ideation & Method ====================
    "idea-discovery": {
        "fields": [
            {"name": "direction", "type": "text", "label": "研究方向", "required": True},
            {"name": "lit_context", "type": "textarea", "label": "文献背景（可选，或由上一步自动提供）"},
            {"name": "num_ideas", "type": "number", "label": "生成 idea 数量", "default": 10, "min": 3, "max": 30},
            {"name": "constraints", "type": "textarea", "label": "约束条件（资源/时间/设备限制）", "placeholder": "e.g. 只有 1 张 A100, 2 周时间"},
        ],
        "requires": ["direction"],
        "atomic": False,
        "atomic_group": None,
    },

    "experiment-plan": {
        "fields": [
            {"name": "idea", "type": "textarea", "label": "研究 Idea（核心方法描述）", "required": True},
            {"name": "baseline_repo", "type": "text", "label": "Baseline 代码仓库", "placeholder": "https://github.com/..."},
            {"name": "dataset", "type": "text", "label": "数据集", "placeholder": "e.g. CIFAR-10, WMT14, MMLU"},
            {"name": "gpu_type", "type": "select", "label": "GPU 后端", "options": ["local", "remote_ssh", "vast_ai", "modal"], "default": "local"},
            {"name": "time_budget", "type": "text", "label": "时间预算", "placeholder": "e.g. 48h"},
        ],
        "requires": ["idea"],
        "atomic": False,
        "atomic_group": "experiment",  # 与 exp-run 绑定
    },

    # ==================== Experiments & Infra ====================
    "experiment-bridge": {
        "fields": [
            {"name": "experiment_plan", "type": "textarea", "label": "实验方案（或由上一步提供）", "required": True},
            {"name": "server_id", "type": "text", "label": "SSH 服务器 ID（远程执行时）"},
            {"name": "seeds", "type": "text", "label": "随机种子（逗号分隔）", "default": "42,123,456"},
            {"name": "batch_size", "type": "number", "label": "初始 batch size"},
        ],
        "requires": ["experiment_plan"],
        "atomic": False,
        "atomic_group": "experiment",  # 与 exp-design 绑定
    },

    "analyze-results": {
        "fields": [
            {"name": "log_path", "type": "filepath", "label": "实验日志/输出路径", "required": True},
            {"name": "metrics", "type": "text", "label": "关注的 metrics", "placeholder": "accuracy, loss, f1"},
            {"name": "baseline_results", "type": "textarea", "label": "Baseline 结果（对比用）"},
        ],
        "requires": ["log_path"],
        "atomic": False,
        "atomic_group": None,
    },

    "run-experiment": {
        "fields": [
            {"name": "command", "type": "text", "label": "执行命令", "required": True, "placeholder": "python train.py --config config.yaml"},
            {"name": "work_dir", "type": "filepath", "label": "工作目录", "default": "."},
            {"name": "server_id", "type": "text", "label": "SSH 服务器（空=本地）"},
            {"name": "gpu_ids", "type": "text", "label": "GPU ID", "default": "0"},
        ],
        "requires": ["command"],
        "atomic": False,
        "atomic_group": None,
    },

    # ==================== Paper Writing ====================
    "paper-writing": {
        "fields": [
            {"name": "paper_plan", "type": "textarea", "label": "论文大纲或前序结果摘要", "required": True},
            {"name": "venue", "type": "select", "label": "目标 Venue", "options": ["ICLR", "NeurIPS", "ICML", "CVPR", "ACL", "AAAI", "IEEE"], "default": "ICLR"},
            {"name": "target_pages", "type": "number", "label": "建议 PDF 页数", "default": 9, "min": 4, "max": 50},
            {"name": "page_tolerance", "type": "number", "label": "建议浮动范围", "default": 1, "min": 0, "max": 5},
            {"name": "main_tex", "type": "filepath", "label": "已有 main.tex 路径（空=新建）"},
            {"name": "bib_file", "type": "filepath", "label": "references.bib 路径"},
        ],
        "requires": ["paper_plan"],
        "atomic": False,
        "atomic_group": None,
    },

    "paper-write": {
        "fields": [
            {"name": "paper_plan_path", "type": "filepath", "label": "已执行论文计划", "default": "paper/PAPER_PLAN.md"},
            {"name": "venue", "type": "select", "label": "目标 Venue", "options": ["ICLR", "NeurIPS", "ICML", "CVPR", "ACL", "AAAI", "IEEE"], "default": "ICLR"},
            {"name": "target_pages", "type": "number", "label": "建议 PDF 页数", "default": 9, "min": 4, "max": 50},
            {"name": "page_tolerance", "type": "number", "label": "建议浮动范围", "default": 1, "min": 0, "max": 5},
            {"name": "main_tex", "type": "filepath", "label": "已有 main.tex 路径（空=新建）"},
            {"name": "bib_file", "type": "filepath", "label": "references.bib 路径"},
        ],
        "requires": [],
        "atomic": False,
        "atomic_group": None,
    },

    "paper-figure": {
        "fields": [
            {"name": "description", "type": "textarea", "label": "图表描述", "required": True, "placeholder": "e.g. Bar chart comparing accuracy of 4 methods on MMLU"},
            {"name": "figure_type", "type": "select", "label": "图表类型", "options": ["auto", "matplotlib", "rich_svg", "excalidraw", "drawio", "mermaid", "tikz", "gpt_image", "nano_banana"], "default": "auto"},
            {"name": "data_source", "type": "filepath", "label": "数据来源文件（CSV/JSON）"},
            {"name": "output_dir", "type": "filepath", "label": "输出目录", "default": "./figures"},
        ],
        "requires": ["description"],
        "atomic": False,
        "atomic_group": None,
    },

    "rich-svg-figure": {
        "fields": [
            {"name": "description", "type": "textarea", "label": "方法架构目标", "required": True, "placeholder": "说明核心机制、内部计算、控制分支和论文叙事"},
            {"name": "artifact_name", "type": "text", "label": "稳定图名", "required": True, "default": "method_architecture"},
            {"name": "scientific_role", "type": "select", "label": "科研角色", "options": ["method"], "default": "method"},
            {"name": "source_artifacts", "type": "textarea", "label": "架构依据", "placeholder": "每行一个代码、方法契约、公式、协议或实验设计路径"},
            {"name": "output_dir", "type": "filepath", "label": "输出目录", "default": "./figures/diagrams"},
        ],
        "requires": ["description", "artifact_name"],
        "atomic": False,
        "atomic_group": None,
    },

    "model-svg-figure": {
        "fields": [
            {"name": "description", "type": "textarea", "label": "概念图目标", "required": True, "placeholder": "说明单一科学问题、五秒阅读目标和必须表达的事实"},
            {"name": "artifact_name", "type": "text", "label": "稳定图名", "required": True, "default": "method_architecture"},
            {"name": "scientific_role", "type": "select", "label": "科研角色", "options": ["method", "mechanism", "system", "theory", "concept"], "default": "method"},
            {"name": "source_artifacts", "type": "textarea", "label": "科学依据", "placeholder": "每行一个方法契约、公式、协议或实现路径"},
            {"name": "output_dir", "type": "filepath", "label": "输出目录", "default": "./figures/diagrams"},
        ],
        "requires": ["description", "artifact_name"],
        "atomic": False,
        "atomic_group": None,
    },

    "excalidraw-skill": {
        "fields": [
            {
                "name": "description",
                "type": "textarea",
                "label": "科研图目标",
                "required": True,
                "placeholder": "说明图要表达的机制、比较关系及其目标论文小节",
            },
            {
                "name": "artifact_name",
                "type": "text",
                "label": "稳定图名",
                "required": True,
                "placeholder": "e.g. method_architecture",
            },
            {
                "name": "scientific_role",
                "type": "select",
                "label": "科研角色",
                "options": ["method", "protocol", "analysis", "qualitative"],
                "default": "method",
            },
            {
                "name": "source_artifacts",
                "type": "textarea",
                "label": "设计依据",
                "placeholder": "每行一个论文、代码、配置、公式或实验契约路径",
            },
            {
                "name": "output_dir",
                "type": "filepath",
                "label": "输出目录",
                "default": "./figures/diagrams",
            },
        ],
        "requires": ["description", "artifact_name"],
        "atomic": False,
        "atomic_group": None,
    },

    # ==================== Review & Audit ====================
    "auto-review-loop": {
        "fields": [
            {"name": "paper_path", "type": "filepath", "label": "论文 .tex 路径", "required": True},
            {"name": "venue", "type": "select", "label": "目标 Venue 标准", "options": ["ICLR", "NeurIPS", "ICML", "CVPR", "ACL", "AAAI"], "default": "ICLR"},
            {"name": "max_rounds", "type": "number", "label": "最大审稿轮数", "default": 3, "min": 1, "max": 10},
            {"name": "target_score", "type": "number", "label": "目标分数（1-10）", "default": 7},
        ],
        "requires": ["paper_path"],
        "atomic": True,  # 内部循环不可中断
        "atomic_group": None,
    },

    "experiment-audit": {
        "fields": [
            {"name": "paper_path", "type": "filepath", "label": "论文路径", "required": True},
            {"name": "experiment_dir", "type": "filepath", "label": "实验代码/日志目录", "required": True},
            {"name": "claims", "type": "textarea", "label": "论文中的核心声明（可选，自动提取）"},
        ],
        "requires": ["paper_path", "experiment_dir"],
        "atomic": True,  # 5 层审计完整执行
        "atomic_group": None,
    },

    # ==================== Compile & Presentation ====================
    "paper-compile": {
        "fields": [
            {"name": "project_dir", "type": "filepath", "label": "LaTeX 项目目录", "required": True},
            {"name": "main_tex", "type": "text", "label": "主文件名", "default": "main.tex"},
            {"name": "clean_build", "type": "select", "label": "清理编译", "options": ["no", "yes"], "default": "no"},
        ],
        "requires": ["project_dir"],
        "atomic": False,
        "atomic_group": None,
    },

    "paper-talk": {
        "fields": [
            {"name": "paper_path", "type": "filepath", "label": "论文 PDF 或 .tex 路径", "required": True},
            {"name": "duration", "type": "select", "label": "演讲时长", "options": ["5min", "10min", "15min", "20min"], "default": "15min"},
            {"name": "style", "type": "select", "label": "风格", "options": ["beamer", "reveal.js", "pptx"], "default": "beamer"},
        ],
        "requires": ["paper_path"],
        "atomic": False,
        "atomic_group": None,
    },

    # ==================== Patents ====================
    "prior-art-search": {
        "fields": [
            {"name": "invention_description", "type": "textarea", "label": "发明描述", "required": True},
            {"name": "keywords", "type": "text", "label": "关键词", "placeholder": "逗号分隔"},
            {"name": "max_results", "type": "number", "label": "最大结果数", "default": 20},
        ],
        "requires": ["invention_description"],
        "atomic": False,
        "atomic_group": None,
    },

    "claims-drafting": {
        "fields": [
            {"name": "invention_title", "type": "text", "label": "发明名称", "required": True},
            {"name": "key_components", "type": "textarea", "label": "核心组件（每行一个）", "required": True},
            {"name": "method_steps", "type": "textarea", "label": "方法步骤（每行一步）", "required": True},
        ],
        "requires": ["invention_title", "key_components", "method_steps"],
        "atomic": False,
        "atomic_group": "patent_draft",
    },
}


# ==================== 原子组定义 ====================

ATOMIC_GROUPS = {
    "experiment": {
        "name": "实验（设计+执行）",
        "description": "实验设计和实验执行必须连续完成，中间不能手动干预",
        "node_ids": ["exp-design", "exp-run"],
    },
    "patent_draft": {
        "name": "专利撰写",
        "description": "权利要求书和说明书应一起生成",
        "node_ids": ["claims-drafting", "specification-writing"],
    },
}


def get_skill_input_schema(skill_id: str) -> dict:
    """获取 skill 的输入 schema（如果没有定义则返回通用 schema）"""
    if skill_id in SKILL_INPUT_SCHEMAS:
        return SKILL_INPUT_SCHEMAS[skill_id]

    # 通用 fallback schema
    return {
        "fields": [
            {"name": "input", "type": "textarea", "label": "输入内容", "required": True, "placeholder": "描述你想让这个 skill 做什么..."},
        ],
        "requires": ["input"],
        "atomic": False,
        "atomic_group": None,
    }


def get_atomic_group(skill_id: str) -> Optional[str]:
    """获取 skill 所属的原子组"""
    schema = SKILL_INPUT_SCHEMAS.get(skill_id, {})
    return schema.get("atomic_group")


def get_group_members(group_name: str) -> list[str]:
    """获取原子组的所有成员节点"""
    group = ATOMIC_GROUPS.get(group_name)
    if group:
        return group["node_ids"]
    return []


def validate_node_selection(selected_ids: list[str]) -> dict:
    """验证节点选择是否满足原子组约束

    Returns:
        {"valid": bool, "missing": list[str], "message": str}
    """
    missing = []
    for group_name, group_info in ATOMIC_GROUPS.items():
        group_nodes = set(group_info["node_ids"])
        selected_in_group = group_nodes & set(selected_ids)

        if selected_in_group and selected_in_group != group_nodes:
            # 部分选中 → 需要补全
            missing.extend(group_nodes - selected_in_group)

    if missing:
        return {
            "valid": False,
            "missing": missing,
            "message": f"以下节点需要一起执行: {', '.join(missing)}",
        }
    return {"valid": True, "missing": [], "message": ""}
