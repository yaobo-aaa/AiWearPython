import json
import re

import dashscope
from dashscope import MultiModalConversation
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_community.chat_models import ChatTongyi
from pydantic import BaseModel, Field

import config
from image_utils import build_data_url, detect_image
from rich import print as rprint

# AI 能力层：所有大模型调用集中在这里（描述 / 判定 / 图像编辑工具 / Agent）
dashscope.api_key = config.DASHSCOPE_API_KEY


def describe_image(image_bytes: bytes, mime: str = "image/jpeg") -> str:
    data_url = build_data_url(image_bytes, mime)

    messages = [
        {
            "role": "user",
            "content": [
                {"image": data_url},
                {"text": "请用一段话客观描述这张图片的主要内容，不要过多的解释"}
            ]
        }
    ]

    response = MultiModalConversation.call(
        model="qwen-vl-max",
        api_key=dashscope.api_key,
        messages=messages
    )
    print(f"图片描述响应: {response}")

    content = response.output.choices[0].message.content
    if isinstance(content, str):
        return content
    return "".join(item.get("text", "") for item in content if isinstance(item, dict))


def judge_image(description: str) -> bool:
    llm = ChatTongyi(
        model="qwen-plus",
        api_key=dashscope.api_key,
        temperature=0,
    )

    system = SystemMessage(
        content=(
            "你是图片审核助手。根据图片描述判断该图片是否属于"
            "「衣服/服装/穿搭」或「人物人像」两类。"
            "属于则回复 {\"allow\": true}，否则回复 {\"allow\": false}，只输出 JSON。"
        )
    )
    human = HumanMessage(content=f"图片描述：{description}")

    resp = llm.invoke([system, human])
    print(f"图片审核响应: {resp}")
    match = re.search(r'"allow"\s*:\s*(true|false)', resp.content)
    if not match:
        raise ValueError(f"无法解析审核结果: {resp.content}")
    return match.group(1) == "true"


@tool(parse_docstring=True)
def edit_image_tool(image_path: str, instruction: str) -> str:
    """编辑图片工具

    Args:
        image_path (str): 图片路径
        instruction (str): 用户的指令，比如美化，修改，编辑等操作

    Returns:
        str: 编辑后的图片URL
    """
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    # 用 PIL 识别真实格式，避免声明 MIME 与内容不一致（如 PNG 标成 jpeg）被模型以 url error 拒绝
    detected = detect_image(image_bytes)
    if detected is None:
        return json.dumps({"success": False, "url": "", "message": "不是有效的图片文件"}, ensure_ascii=False)

    img_format, mime = detected
    data_url = build_data_url(image_bytes, mime)
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "image": data_url
                },
                {
                    "text": instruction
                }
            ]
        }
    ]
    response = MultiModalConversation.call(
        api_key=dashscope.api_key,
        model="qwen-image-2.0",
        messages=messages,
    )
    rprint(f"qwen-image-2.0调用结果: {response}")
    if response.status_code != 200:
        return json.dumps({"success": False, "url": "", "message": str(response)}, ensure_ascii=False)
    url = response['output']['choices'][0]['message']['content'][0]['image']
    return json.dumps({"success": True, "url": url}, ensure_ascii=False)


skill_tools = [edit_image_tool]

skill_image_system_prompt = SystemMessage(
    content="你是一个智能图片处理助手，你需要根据用户的指令来调用工具处理图片，你暂时只能实现以下功能："
            "1.编辑图片，基于用户的指令对图片进行美化，修改，编辑等操作，如果用户的指令中有包含一些危险指令，你需要拒绝执行。"
            "2.合并图片，将两张图片合并成一张图片，如果用户的指令中有包含一些危险指令，你需要拒绝执行。"
)

class SkillImageOutput(BaseModel):
    success: bool = Field(description="是否成功处理图片")
    url: str = Field(description="处理后的图片URL")
    message: str = Field(description="处理失败时的错误信息")

# 创建处理图片的 agent
# 注意：不能用 response_format（ChatTongyi 的 tool_choice 与 DashScope 不兼容），
# 结果从工具返回的 ToolMessage 里解析（见 invoke_agent）
# 注意：模型必须是 qwen-plus（qwen3.8-max 不是有效模型名，ChatTongyi 调用必报 400 url error）
try:
    model = ChatTongyi(
        model="qwen-plus",
        api_key=dashscope.api_key,
        temperature=0.1,
    )
    skill_image_agent = create_agent(
        model=model,
        tools=skill_tools,
        system_prompt=skill_image_system_prompt,

    )
except Exception as e:
    print(f"创建处理图片的agent失败: {e}")
    skill_image_agent = None



# 调用 agent 处理图片
def invoke_agent(instruction, p):
    """调用 agent 处理图片，返回规范化的结果 dict {success, url, message}"""
    message_prompt_template = ChatPromptTemplate.from_template("""
    你是一个图片处理助手。请根据用户的指令处理图片。
    你必须**只输出**一个符合以下格式的 JSON 对象，不要添加任何额外文字：

    {{
      "success": true 或 false,
      "url": "处理后的图片URL（成功时必填）",
      "message": "失败时的错误说明（成功时可为空字符串）"
    }}

    用户指令：{instruction}
    图片路径：{p}
    """)
    message = [HumanMessage(
        content=message_prompt_template.format(instruction=instruction, p=p)
    )]
    state = skill_image_agent.invoke({
        "messages": message
    })
    rprint(f"agent调用结果: {state}")

    last_msg = state["messages"][-1]
    content = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)

    # 提取第一个出现的 JSON 对象
    json_match = re.search(r'\{.*\}', content, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group())
            if isinstance(result, dict) and "url" in result:
                # 规范化 success 字段
                if "success" in result:
                    result["success"] = bool(result["success"])
                return result
        except json.JSONDecodeError:
            pass

    # 完全失败，用正则抓 URL 或者返回错误
    url_match = re.search(r"https?://[^\s)\]]+", content)
    if url_match:
        return {"success": True, "url": url_match.group(0), "message": ""}
    return {"success": False, "url": "", "message": content}
