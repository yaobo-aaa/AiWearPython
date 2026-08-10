# 接口文档

> 本项目所有接口的统一文档。

## 接口列表

| 序号 | 接口地址 | 接口描述 |
|------|----------|----------|
| 1 | `POST /api/validate-image` | 图片上传前审核 |
| 2 | `POST /api/skill/image` | 图片编辑与合并 |

---

## 一、图片上传前审核

### 基本信息

| 项目 | 内容 |
|------|------|
| 接口地址 | `POST /api/validate-image` |
| 接口描述 | 用于判断图片是否属于「衣服/服装/穿搭」或「人物人像」，用于上传前审核 |
| 请求头 | `Content-Type: multipart/form-data` |

### 请求参数

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `file` | file | 是 | 待审核图片文件 |

### 处理流程

1. 读取图片 bytes
2. 调用 `qwen-vl-max` 生成图片文字描述
3. 通过 `LangChain + qwen-plus` 输出“是/否”判断
4. 返回审核结果

### 响应示例

```json
{
  "code": 200,
  "allow": true
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | 业务状态码，`200` 表示请求成功 |
| `allow` | bool | 是否允许上传，`true` 允许 / `false` 拒绝 |

---

## 二、图片编辑与合并

### 基本信息

| 项目 | 内容 |
|------|------|
| 接口地址 | `POST /api/skill/image` |
| 接口描述 | 同一接口支持两种功能：① 按文字指令编辑单张图片；② 按指令合并两张图片（用于「衣服/服装/穿搭」和「人物人像」图片的合成） |
| 请求头 | `Content-Type: multipart/form-data` |

### 功能一：图片编辑（传 `file` + `instruction`）

#### 请求参数

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `file` | file | 是 | 待编辑的原始图片文件 |
| `instruction` | text | 是 | 编辑指令，描述希望对图片进行的修改，如“把背景换成纯白色” |

#### 处理流程

1. 读取图片 bytes 与编辑指令
2. 调用大模型图像编辑能力，按指令生成修改后的图片
3. 返回修改后图片的可访问 URL

#### 响应示例

```json
{
  "code": 200,
  "success": true,
  "url": "https://dashscope-result-hz.oss-cn-hangzhou.aliyuncs.com/7d/78/20260318/45af8005/ad0bb2bc-a5c1-4bcd-8c26-519bba2dd798-1.png?Expires=1774426037&OSSAccessKeyId=LTAI5tKPD3TMqf2Lna1fASuh&Signature=ku%2Fg2VX5LgS77tHShD5F6T%2F9smQ%3D"
}
```

### 功能二：图片合并（传 `file1` + `file2` + `instruction`）

#### 请求参数

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `file1` | file | 是 | 图片1 |
| `file2` | file | 是 | 图片2 |
| `instruction` | text | 是 | 合并指令，描述希望对图片1和图片2进行的合并，如“把图2中的人物合成到图1的场景中” |

#### 处理流程

1. 读取图片1、图片2 bytes 与合并指令
2. 调用大模型图像合并能力，按指令将两张图片合成
3. 返回合并后图片的可访问 URL

#### 响应示例

```json
{
  "code": 200,
  "success": true,
  "url": "https://xxx/edited-image.png"
}
```

### 字段说明（两种功能通用）

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | int | 业务状态码，`200` 成功 / `400` 参数缺失或处理失败 / `500` 服务异常 |
| `success` | bool | 是否成功，`true` 成功 / `false` 失败 |
| `url` | string | 处理后的图片访问链接（带签名，有有效期）；失败时为空字符串 |
| `message` | string | 失败原因；成功时一般不返回 |

> 失败示例（如缺少参数或 agent 拒绝执行）：
>
> ```json
> {
>   "code": 400,
>   "success": false,
>   "url": "",
>   "message": "缺少 instruction 参数"
> }
> ```
