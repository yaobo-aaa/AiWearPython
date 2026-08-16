import os
import re
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


# ---- 图片检索（文搜图 / 图搜图）----
# 阈值规则：文搜图稍高、图搜图稍低（两套相似度的数值域不同，各自独立可调）。
TEXT_SEARCH_THRESHOLD = 0.10   # 文搜图：关键词命中率/字符 bigram 相似度阈值（实测正确命中≥0.167，误报≤0.053）
IMAGE_SEARCH_THRESHOLD = 0.50  # 图搜图：CLIP 向量余弦阈值（实测同图≈1.0，跨图0.48~0.56，0.5 可滤掉最弱跨图）
MAX_SEARCH_RESULTS = 20        # 单次返回条数上限

_PUNCT_RE = re.compile(r"[\s，,。.、；;：:·\"“”‘’()（）\[\]{}《》〈〉<>?？!！~—…\-–/\\|_+*=@#$%^&]+")


def _char_bigrams(s: str) -> set:
    """字符 bigram 集合（中文无需分词，直接按字符滑窗）。"""
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _text_tokens(s: str) -> set:
    """粗分词：连续 CJK 字符段 + 连续字母/数字串（如 T恤 -> {T, 恤}）。"""
    return set(re.findall(r"[一-鿿]+|[A-Za-z0-9]+", s))


def _dice(a: set, b: set) -> float:
    """Dice 系数：2*|交集|/(|A|+|B|)，范围 [0,1]，对空集返回 0。"""
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


def _split_terms(s: str) -> list:
    """把关键词行按中文标点拆成术语列表（如"旗袍，花卉图案" -> ["旗袍","花卉图案"]）。"""
    return [t for t in re.split(r"[,，、;；。]+", s or "") if t]


def text_similarity(query: str, description: str, keywords: str = "", extra_terms=()) -> float:
    """query 与图片文本描述的中文文本相似度。

    描述为 qwen 生成的中文（一句话 + 关键词行）。项目未装分词/文本向量依赖：
    - 主信号「关键词命中率」：图片的每个关键词术语，被 query 或扩展词（extra_terms，
      即 qwen 语义扩展的同义词/属性词，如"男人"->"男性"）命中即记 1 分，除以术语总数。
      短关键词查询由它驱动，同义词经扩展后也能命中（"男性"命中"青年男性"）；
    - 辅信号「字符 bigram Dice」：兜底整句/相似句子的查询。
    取两者较大值。
    """
    q = _PUNCT_RE.sub("", (query or "").lower())
    full_text = _PUNCT_RE.sub("", (f"{description}\n{keywords}" or "").lower())
    if not q or not full_text:
        return 0.0

    # query 自身 + qwen 扩展词，去空、去重
    related = []
    for r in [q] + [_PUNCT_RE.sub("", (t or "").lower()) for t in extra_terms]:
        if r and r not in related:
            related.append(r)

    kw_score = 0.0
    terms = _split_terms(keywords)
    if terms:
        hits = 0
        for t in terms:
            for r in related:
                # 只匹配「扩展词是图片关键词术语的子串/等值」，如"男性" in "青年男性"。
                # 反向（"女性" in "女性旗袍"）会因 颜色/人群 等短术语误命中长扩展词，产生噪声，不做。
                if len(r) >= 2 and r in t:
                    hits += 1
                    break
        kw_score = hits / len(terms)

    bigram_score = _dice(_char_bigrams(q), _char_bigrams(full_text))
    return max(kw_score, bigram_score)


def _dot(a: list, b: list) -> float:
    """点积。存储与查询向量均已 L2 归一化，点积即余弦相似度。"""
    return sum(x * y for x, y in zip(a, b))


def search_image(user_id, query: str, image_bytes: bytes | None):
    """图库检索：按 file/query 判断图搜图或文搜图。返回 (data, code, message)。

    data 形如 [{"filePath": oss_url, "similarity": float}, ...]，按相似度降序。
    参数缺失返回 (None, 400, message)。
    """
    # 先校验查询条件，再查库
    if image_bytes is None and not query:
        return None, 400, "缺少查询条件：file 与 query 至少传一个"

    image_ids = redis_store.get_user_image_ids(str(user_id))
    metas = [(iid, redis_store.get_image_meta(iid)) for iid in image_ids]
    metas = [(iid, m) for iid, m in metas if m]

    # 库里没有该用户的图：直接空结果，避免无谓加载 CLIP 模型（首载约 30s）
    if not metas:
        return [], 200, "查询成功"

    results = []
    if image_bytes is not None:
        # 图搜图：CLIP 提取查询图片向量，与库内图片向量做余弦
        query_vec = clip_core.embed_image(image_bytes)
        threshold = IMAGE_SEARCH_THRESHOLD
        for iid, meta in metas:
            stored = meta.get("embedding") or []
            if not stored:
                continue
            sim = _dot(query_vec, stored)
            print(f"图搜图相似度: {sim}")
            if sim >= threshold:
                results.append((meta.get("oss_url", ""), sim))
    else:
        # 文搜图：qwen 语义扩展 query（解决"男人"vs"青年男性"这类同义词），再与文本描述比对
        try:
            expanded = ai_core.expand_search_query(query)
        except Exception as e:
            print(f"检索词扩展失败，回退原词: {e}")
            expanded = [query]
        threshold = TEXT_SEARCH_THRESHOLD
        for iid, meta in metas:
            sim = text_similarity(
                query, meta.get("description", ""), meta.get("keywords", ""),
                extra_terms=expanded,
            )
            print(f"文搜图相似度: {sim}")
            if sim >= threshold:
                results.append((meta.get("oss_url", ""), sim))

    results.sort(key=lambda x: x[1], reverse=True)
    results = results[:MAX_SEARCH_RESULTS]
    data = [{"filePath": url, "similarity": round(sim, 4)} for url, sim in results]
    return data, 200, "查询成功"
