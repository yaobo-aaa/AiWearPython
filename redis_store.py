import json
from datetime import datetime, timezone

import redis

import config

# 基础设施层：Redis 存储
# redis.Redis 连接是惰性的（首次执行命令才真正连接），导入本模块不会报错。
# 与 Java 端共用 database 0，key 统一加 aiwear: 前缀防冲突。
_redis_client = redis.Redis(
    host=config.REDIS_HOST,
    port=config.REDIS_PORT,
    db=config.REDIS_DB,
    password=config.REDIS_PASSWORD or None,
    socket_timeout=config.REDIS_TIMEOUT,
    socket_connect_timeout=config.REDIS_TIMEOUT,
    decode_responses=True,
)

IMAGE_KEY_PREFIX = "aiwear:image"
USER_IMAGES_KEY_PREFIX = "aiwear:user"
EMBEDDING_DECIMALS = 6


def _image_key(image_id: str) -> str:
    return f"{IMAGE_KEY_PREFIX}:{image_id}"


def _user_images_key(user_id: str) -> str:
    return f"{USER_IMAGES_KEY_PREFIX}:{user_id}:images"


def save_image_meta(image_id, user_id, oss_url, description, keywords, embedding, embedding_dim) -> None:
    """原子写入图片元信息 hash 与该用户图片集合 set（防孤儿 imageId）。

    Args:
        image_id: 图片唯一 ID
        user_id: 所属用户 ID
        oss_url: OSS 图片地址
        description: 完整描述（一句话 + \n + 关键词）
        keywords: 关键词行（换行后的部分，可为空串）
        embedding: 512 维向量
        embedding_dim: 向量维度
    """
    created_at = datetime.now(timezone.utc).isoformat()
    # embedding 存 JSON float 数组，round 到 6 位小数约 4-5KB（float32 有效数字约 7 位，
    # 对余弦相似度损失可忽略）；Java 侧 JSON.parse 直接读取。
    # 不加 TTL：这是持久向量库的引用数据。
    mapping = {
        "user_id": str(user_id),
        "oss_url": oss_url,
        "description": description,
        "keywords": keywords,
        "embedding": json.dumps([round(x, EMBEDDING_DECIMALS) for x in embedding]),
        "embedding_dim": str(embedding_dim),
        "created_at": created_at,
    }
    pipe = _redis_client.pipeline()
    pipe.hset(_image_key(image_id), mapping=mapping)
    pipe.sadd(_user_images_key(user_id), image_id)
    pipe.execute()


def get_user_image_ids(user_id) -> list:
    """读取用户全部图片 ID（Set -> list）。用户无图时返回空列表。"""
    return sorted(_redis_client.smembers(_user_images_key(user_id)) or [])


def get_image_meta(image_id: str) -> dict | None:
    """读取单张图片哈希，embedding 字段反序列化为 float 列表。key 不存在返回 None。"""
    meta = _redis_client.hgetall(_image_key(image_id))
    if not meta:
        return None
    meta = dict(meta)
    embedding_raw = meta.get("embedding")
    if embedding_raw:
        meta["embedding"] = json.loads(embedding_raw)
    return meta
