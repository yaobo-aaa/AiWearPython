import os
import tempfile
import uuid

import ai_core
from image_utils import detect_image

# Service 层：业务编排，把 Web 层给到的参数组合成一次完整的业务调用


def validate_image(image_bytes):
    """图片审核：非图片返回 400，否则描述 + 判定。返回 (result, http_code)。"""
    detected = detect_image(image_bytes)
    if detected is None:
        return {"allow": False, "msg": "不是有效的图片文件"}, 400
    _, mime = detected
    description = ai_core.describe_image(image_bytes, mime)
    allow = ai_core.judge_image(description)
    return {"allow": allow}, 200


def skill_image(instruction, image_bytes_list):
    """图片编辑/合并：写临时文件 -> 调 agent -> 清理。返回 (result, http_code)。"""
    if ai_core.skill_image_agent is None:
        return {"success": False, "url": "", "message": "Agent 未启用"}, 500

    paths = []
    try:
        # 将图片临时保存到服务器（编辑 1 张 / 合并 2 张）
        tmp_dir = tempfile.gettempdir()
        for image_bytes in image_bytes_list:
            p = os.path.join(tmp_dir, f"aiwear_{uuid.uuid4().hex}.bin")
            with open(p, "wb") as f:
                f.write(image_bytes)
            paths.append(p)

        result = ai_core.invoke_agent(instruction, paths)
        ok = result.get("success") in (True, "true", "True")
        return {
            "success": ok,
            "url": result.get("url", ""),
            "message": result.get("message"),
        }, 200 if ok else 400
    except Exception as e:
        print(f"处理图片失败: {e}")
        return {"success": False, "url": "", "message": str(e)}, 500
    finally:
        for p in paths:
            if os.path.exists(p):
                os.unlink(p)
