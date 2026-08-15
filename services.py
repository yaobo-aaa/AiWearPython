import os
import tempfile
import uuid
from urllib.parse import urlparse

import requests

import ai_core
import clip_core
import redis_store
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


MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10MB


def download_image(oss_url: str) -> bytes:
    """下载 OSS 图片：校验 scheme（SSRF 防护）、超时、体积上限。返回图片 bytes。"""
    scheme = urlparse(oss_url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"ossUrl 必须是 http/https 地址: {oss_url}")
    resp = requests.get(oss_url, timeout=(10, 30))
    resp.raise_for_status()
    if len(resp.content) > MAX_IMAGE_BYTES:
        raise ValueError(f"图片超过大小上限 {MAX_IMAGE_BYTES} 字节")
    return resp.content


def upload_image(oss_url: str, user_id: str):
    """图片上传向量化：下载 -> 校验 -> qwen 描述 -> CLIP 向量 -> Redis 存储。返回 (result, http_code)。"""
    try:
        image_bytes = download_image(oss_url)
        detected = detect_image(image_bytes)
        if detected is None:
            return {"success": False, "message": "不是有效的图片文件"}, 400
        _, mime = detected

        full_description = ai_core.describe_image_lc(image_bytes, mime).strip()
        parts = full_description.split("\n", 1)
        description = parts[0]
        keywords = parts[1].strip() if len(parts) > 1 else ""

        embedding = clip_core.embed_image(image_bytes)
        image_id = uuid.uuid4().hex
        redis_store.save_image_meta(
            image_id=image_id,
            user_id=user_id,
            oss_url=oss_url,
            description=full_description,
            keywords=keywords,
            embedding=embedding,
            embedding_dim=len(embedding),
        )
        return {
            "description": full_description,
            "embeddingDim": len(embedding),
            "imageId": image_id,
            "success": True,
        }, 200
    except Exception as e:
        print(f"upload-image 处理失败: {e}")
        return {"success": False, "message": str(e)}, 500
