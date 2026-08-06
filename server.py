import base64
import io
import os
import re

import dashscope
from dashscope import MultiModalConversation
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from langchain_community.chat_models import ChatTongyi
from langchain_core.messages import HumanMessage, SystemMessage
from PIL import Image


# 读取 .env 中的配置
load_dotenv()
dashscope.api_key = os.getenv("DASHSCOPE_API_KEY", "")

app = Flask(__name__)


def describe_image(image_bytes: bytes, mime: str = "image/jpeg") -> str:

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime};base64,{image_b64}"

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



@app.route("/api/validate-image", methods=["POST"])
def validate_image_api():
    try:
        file = request.files.get("file")
        if file is None or file.filename == "":
            return jsonify({"code": 400, "allow": False, "msg": "缺少 file 参数"}), 400

        image_bytes = file.read()

        # 闸门：校验字节真的是可解码的图片，防止非图片文件/伪造扩展名混过审核
        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                img_format = img.format or "JPEG"
                img.verify()
        except Exception:
            return jsonify({"code": 400, "allow": False, "msg": "不是有效的图片文件"}), 400

        # 用识别出的真实格式拼 data URL，避免扩展名与内容不一致
        mime = f"image/{img_format.lower()}"

        description = describe_image(image_bytes, mime)
        allow = judge_image(description)

        return jsonify({"code": 200, "allow": allow})
    except Exception as e:
        return jsonify({"code": 500, "allow": False, "msg": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
