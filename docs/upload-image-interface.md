# 图片上传向量化接口对接文档（Java 端）

> 给 Java 后端调用 Python 服务的接口规范。用于图片入库时：生成文字描述 + 提取 512 维向量 + 存入 Redis。

---

## 一、接口基本信息

| 项目 | 内容 |
|------|------|
| 接口地址 | `POST /api/upload-image` |
| 请求协议 | HTTP/1.1 |
| 请求头 | `Content-Type: application/json`（推荐）或 `multipart/form-data` |
| 调用方 | Java 后端（服务间调用，非浏览器） |
| 图片大小上限 | 10 MB |
| 响应格式 | `application/json; charset=utf-8` |

---

## 二、请求参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `ossUrl` | string | 是 | 图片在 OSS 上的访问地址（必须 `http/https` 开头） |
| `userId` | string | 是 | 所属用户 ID（字符串） |

> 参数可通过 **JSON body** 或 **form** 任意一种方式传递，二选一。

### 请求示例 1：JSON body（推荐）

```bash
curl -X POST http://<python服务地址>:5000/api/upload-image \
  -H "Content-Type: application/json" \
  -d '{
        "ossUrl": "https://your-bucket.oss-cn-hangzhou.aliyuncs.com/images/a1b2c3.jpg",
        "userId": "1001"
      }'
```

### 请求示例 2：form（application/x-www-form-urlencoded 或 multipart）

```bash
curl -X POST http://<python服务地址>:5000/api/upload-image \
  -d "ossUrl=https://your-bucket.oss-cn-hangzhou.aliyuncs.com/images/a1b2c3.jpg&userId=1001"
```

---

## 三、响应

### 3.1 成功响应（HTTP 200）

```json
{
  "description": "一件红色的短袖T恤平铺在灰色背景上。\n红色，T恤，短袖，灰色背景",
  "embeddingDim": 512,
  "imageId": "0fd1dbfa39734ba4bec65e26ec9ecfa1",
  "success": true
}
```

### 3.2 失败响应

```json
{
  "success": false,
  "message": "缺少 ossUrl, userId 参数"
}
```

---

## 四、字段说明

| 字段 | 类型 | 必返回 | 说明 |
|------|------|--------|------|
| `success` | bool | 是 | 是否处理成功 |
| `description` | string | 成功时 | 图片文字描述：一句话概括 + `\n` 换行 + 逗号分隔的关键词 |
| `embeddingDim` | int | 成功时 | 向量维度，恒为 `512` |
| `imageId` | string | 成功时 | 图片唯一 ID（32 位 hex），即后续 Redis 中查询图片的标识 |
| `message` | string | 失败时 | 失败原因 |

> 注意：**成功响应不含 `code` 字段**，请以 HTTP 状态码 + `success` 字段判断结果。

---

## 五、HTTP 状态码

| 状态码 | 含义 | 说明 |
|--------|------|------|
| `200` | 成功 | `success: true` |
| `400` | 参数错误 | 缺少 `ossUrl`/`userId`；或 `ossUrl` 指向的内容不是有效图片 |
| `500` | 服务异常 | 图片下载失败、qwen 模型调用失败、CLIP 向量提取失败、Redis 写入失败 |

---

## 六、服务端处理流程

```
接收 ossUrl + userId
   │
   ▼
① 下载 ossUrl 图片（校验 scheme / 10MB 上限 / 超时）
   │
   ▼
② qwen-vl-max（langchain）生成文字描述
   │       格式：一句话\n关键词1，关键词2，...
   ▼
③ CLIP 模型提取 512 维向量（L2 归一化）
   │
   ▼
④ 生成 imageId（uuid4().hex），全部信息写入 Redis
   │
   ▼
返回 { description, embeddingDim, imageId, success }
```

---

## 七、Redis 存储约定（供 Java 端读取）

Python 服务写入 Redis（database 0），Java 端可按 `imageId` 查询后续使用：

### Key 1：图片完整信息

```
Key  : aiwear:image:{imageId}
Type : Hash
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_id` | string | 用户 ID |
| `oss_url` | string | OSS 图片地址 |
| `description` | string | 完整描述（含 `\n` 换行） |
| `keywords` | string | 关键词行（换行后的部分） |
| `embedding` | string | **JSON 数组字符串**，512 个浮点数（round 到 6 位），`JSON.parse` 得到 `double[]` |
| `embedding_dim` | string | 向量维度 `"512"` |
| `created_at` | string | ISO 8601 时间，如 `2026-08-15T06:34:01.748552+00:00` |

### Key 2：用户图片索引

```
Key  : aiwear:user:{userId}:images
Type : Set（集合，自动去重、无序）
```

集合内每个元素是一个 `imageId`（string）。用于按用户拉取全部图片 ID。

### 常用 Redis 指令

```bash
redis-cli -h 106.15.225.16 -p 6379 -n 0

# 取单张图片完整信息
HGETALL aiwear:image:0fd1dbfa39734ba4bec65e26ec9ecfa1

# 单独取向量
HGET aiwear:image:0fd1dbfa39734ba4bec65e26ec9ecfa1 embedding

# 取某用户全部图片 ID
SMEMBERS aiwear:user:1001:images
```

---

## 八、注意事项

1. **`ossUrl` 必须能公网/内网直连下载**，Python 服务会直接 `GET` 该地址；OSS 私有桶需带签名参数（`?Expires=...&Signature=...`）或放内网可访问地址。
2. **首次请求延迟**：Python 服务刚启动后的第一个请求，需要加载 CLIP 模型（约 5~30 秒），之后常驻内存，单请求延迟主要为 qwen-vl-max 调用时间（约 2~5 秒）。若 Java 侧有超时限制，建议首次调用前预热一次。
3. **`imageId` 由 Python 服务生成**（uuid4 hex），Java 端如需关联业务数据，可自行在业务表保存该 `imageId`。
4. **embedding 已做 L2 归一化**，Java 端做余弦相似度时直接点积即可。
5. 图片描述为模型生成，非精确结果；如业务对描述要求严格，建议 Java 端校验后使用。
