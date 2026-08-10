# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI 穿搭图片服务的 Flask 后端，提供两个接口：
- `POST /api/validate-image`：图片审核（是否服装/人像）
- `POST /api/skill/image`：图片编辑 / 合并（LangChain Agent 自主选工具）

依赖阿里云 DashScope 的 Qwen 多模态模型；密钥从 `.env` 的 `DASHSCOPE_API_KEY` 读取（`load_dotenv()`）。

## Commands

```bash
# 安装依赖（Python 3.13，虚拟环境 .venv）
.venv/Scripts/python.exe -m pip install -r requirements.txt

# 启动服务（监听 0.0.0.0:5000，debug 模式）
.venv/Scripts/python.exe server.py
```

项目无测试。

## Architecture

代码按 **Web / Service / AI / Utils / Config** 五层拆成扁平模块，依赖方向单向：`routes → services → ai_core / image_utils → config`。

- **server.py**（入口）：创建 Flask app + 注册 `routes.bp` 蓝图 + `app.run()`，无业务逻辑。
- **routes.py**（Web 层）：`Blueprint("api")`，两个 HTTP 路由。只做参数解析、缺失校验（file/instruction）、`jsonify` 组装 `code` 字段。
- **services.py**（Service 层）：`validate_image(image_bytes)`（`detect_image → describe_image → judge_image`）、`skill_image(instruction, image_bytes)`（写临时文件 `aiwear_<uuid>.bin` → `invoke_agent` → `finally` 清理）。返回 `(result, http_code)`。
- **ai_core.py**（AI 能力层）：所有大模型调用。`describe_image`（qwen-vl-max）、`judge_image`（qwen-plus）、`edit_image_tool`（`@tool`，qwen-image-2.0）、模块级单例 `skill_image_agent = create_agent(model=ChatTongyi(qwen-plus, temperature=0.1), tools=[edit_image_tool], system_prompt=...)`、`invoke_agent(instruction, p) -> dict`。`skill_image_agent` 创建失败（如密钥缺失）时置 `None`。
- **image_utils.py**（工具层，纯函数）：`detect_image(image_bytes) -> (format, mime) | None`（PIL 校验）、`build_data_url(image_bytes, mime)`。
- **config.py**（配置）：`load_dotenv()` + `DASHSCOPE_API_KEY = os.getenv(...)`。

`/api/skill/image` 数据流：路由校验 `instruction`+`file`（合并功能尚未实现，当前仅编辑单张）→ `services.skill_image` 写临时文件 → 拼 prompt（含 `image_path`，让大模型按路径选工具）→ `ai_core.invoke_agent` → 返回 `{"code", "success", "url", "message"}`。

模型清单：
- `qwen-vl-max` — 图片描述（`describe_image`）
- `qwen-plus` — 判定与 Agent 推理（`judge_image` + Agent，temperature=0 / 0.1）
- `qwen-image-2.0` — 图像编辑（`edit_image_tool`）

## Gotchas

- **依赖版本不一致（重要）**：`requirements.txt` 声明 `langchain==1.2.7`、`langchain-core==1.2.7`，但当前可运行环境是被 `pip install -U langgraph` 强升过的（langgraph 1.2.10、langchain-core 1.5.3），以此修复 `langchain.agents.create_agent` / deepagents 导入时 `langgraph.runtime` 缺 `ExecutionInfo` 的报错。**直接从 requirements.txt 重建环境会复现该导入错误**。改动依赖时需把 langgraph/langchain-core 版本与 langchain 对齐。
- `requirements.txt` 里的 `torch`、`transformers`、`deepagents`、`redis`、`sympy` 均未被代码 import（疑似遗留/规划中），别假设它们已接入。
- **Agent 模型必须 `qwen-plus`**：`qwen3.8-max` 不是有效模型名，ChatTongyi 调用必报 400 `url error`。
- **`create_agent` 不能用 `response_format`**：ChatTongyi 的 `tool_choice` 与 DashScope 不兼容，报 `tool_choice is one of the strings that should be [none, auto]`。结果从工具返回的 ToolMessage（`{"success","url"}` JSON）里解析，最后一条消息用 `https?://` 正则兜底。
- **编辑图片的 MIME 不能硬编码**：用 PIL 识别真实格式（`image_utils.detect_image`）拼 data URL，PNG 标成 jpeg 会被模型以 `url error` 拒绝。
- 全项目注释、docstring、系统提示词、`docs/api.md` 均为中文；用 `print` 而非 logger；无类型注解。
- 只支持单个全局 `DASHSCOPE_API_KEY`，无 per-user 密钥/轮换。
- 新增/改动接口时同步更新 `docs/api.md`。
