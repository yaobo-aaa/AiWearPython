import io
import threading

from PIL import Image

import config

# 能力层：CLIP 图片向量提取
# 模型加载 598MB 权重较慢，采用懒加载单例避免拖慢服务启动；
# Flask threaded=True，用 Lock 双重检查防止并发首请求重复加载（内存翻倍）。
_model = None
_processor = None
_lock = threading.Lock()


def _load():
    """首次调用时加载 CLIP 模型与处理器（延迟导入 torch/transformers）。"""
    global _model, _processor
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        from transformers import CLIPModel, CLIPProcessor

        # 目录只有 pytorch_model.bin，不能传 use_safetensors=True（会直接 OSError），
        # 默认 None 会自动回退到 .bin 权重。
        _model = CLIPModel.from_pretrained(config.CLIP_MODEL_DIR)
        _model.eval()
        _processor = CLIPProcessor.from_pretrained(config.CLIP_MODEL_DIR)


def embed_image(image_bytes: bytes) -> list:
    """提取图片的 CLIP 512 维特征向量（L2 归一化，便于后续余弦相似度检索）。

    Args:
        image_bytes: 图片原始字节

    Returns:
        list[float]：长度 512 的归一化向量
    """
    _load()
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    inputs = _processor(images=image, return_tensors="pt")

    import torch

    with torch.inference_mode():
        # get_image_features 返回 BaseModelOutputWithPooling，
        # pooler_output 在方法内部已投影为 512 维，不要用 image_embeds。
        features = _model.get_image_features(**inputs).pooler_output
    vec = features.squeeze(0).cpu().numpy().tolist()

    # L2 归一化
    norm = sum(x * x for x in vec) ** 0.5
    if norm:
        vec = [x / norm for x in vec]
    return vec
