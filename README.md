# fossic-ai-proxy

一个轻量级 LLM API 代理，为每个租户注入指定的系统提示词，兼容 OpenAI `/v1/chat/completions` 接口。

## 功能

- 按租户 API Key 路由到不同上游 LLM
- 强制注入系统提示词（覆盖客户端传入的 system message）
- 每个租户支持多个 API Key
- 按租户限制可用模型
- 支持流式（SSE）和非流式响应
- 系统提示词支持内联配置或外部 `.txt` 文件
- 动态术语表注入：仅将原文中出现的术语作为单独 system message 发送，节省 token

## 快速开始

### 1. 克隆项目

```bash
git clone <repo-url>
cd fossic-ai-proxy
```

### 2. 创建配置文件

```bash
cp config.yaml.example config.yaml
```

编辑 `config.yaml`：

```yaml
upstreams:
  - id: "openai-main"
    url: "https://api.openai.com/v1/chat/completions"
    api_key: "sk-xxxxxxxx"          # 你的上游 API Key
    available_models:
      - "gpt-4o"
      - "gpt-4o-mini"

tenants:
  - keys:
      - "sk-translator-xxx"         # 分发给客户端的 Key（可配置多个）
    name: "translator"
    upstream_id: "openai-main"
    allowed_models:
      - "gpt-4o-mini"
    system_prompt_file: "starsector-zh.txt"   # prompts/ 目录下的提示词文件
    glossary_file: "starsector-terms.csv"     # glossary/ 目录下的术语表
```

### 3. 启动

```bash
docker compose up -d
```

服务运行在 `http://localhost:18080`。

---

## 配置说明

### 上游（upstreams）

| 字段 | 说明 |
|------|------|
| `id` | 上游唯一标识，供 tenant 引用 |
| `url` | 完整的上游接口地址 |
| `api_key` | 上游 API Key |
| `available_models` | 该上游支持的模型列表 |

### 租户（tenants）

| 字段 | 说明 |
|------|------|
| `keys` | 分发给客户端的 API Key 列表（一个或多个） |
| `name` | 租户名称（仅用于日志标识） |
| `upstream_id` | 对应上游的 `id` |
| `allowed_models` | 该租户允许使用的模型，必须是上游 `available_models` 的子集 |
| `system_prompt` | 内联系统提示词 |
| `system_prompt_file` | 从 `prompts/` 目录读取提示词文件（`.txt`），与 `system_prompt` 二选一 |
| `glossary_file` | 从 `glossary/` 目录读取术语表（`.csv`），可选 |

### 使用提示词文件

将 `.txt` 文件放入 `prompts/` 目录，在配置中引用文件名：

```yaml
tenants:
  - keys:
      - "sk-translator-xxx"
    name: "translator"
    upstream_id: "openai-main"
    allowed_models:
      - "gpt-4o-mini"
    system_prompt_file: "starsector-zh.txt"   # 对应 prompts/starsector-zh.txt
```

### 使用术语表

将 `.csv` 文件放入 `glossary/` 目录，在配置中引用文件名。CSV 格式为：

```
英文原文,中文译文,类型,同义/别名（换行分隔）,备注说明
```

```yaml
tenants:
  - keys:
      - "sk-translator-xxx"
    name: "translator"
    upstream_id: "openai-main"
    allowed_models:
      - "gpt-4o-mini"
    system_prompt_file: "starsector-zh.txt"
    glossary_file: "starsector-terms.csv"     # 对应 glossary/starsector-terms.csv
```

每次请求时，代理会扫描用户输入，仅将命中的术语作为单独的 system message 发送，未命中的术语不占用 token。

`prompts/` 和 `glossary/` 目录通过 volume 挂载到容器，修改文件后重启容器生效：

```bash
docker compose restart
```

---

## 多租户 / 多上游示例

不同租户使用不同上游，每个租户可配置多个 Key：

```yaml
upstreams:
  - id: "openai"
    url: "https://api.openai.com/v1/chat/completions"
    api_key: "sk-openai-xxx"
    available_models:
      - "gpt-4o"
      - "gpt-4o-mini"

  - id: "deepseek"
    url: "https://api.deepseek.com/v1/chat/completions"
    api_key: "sk-deepseek-xxx"
    available_models:
      - "deepseek-chat"
      - "deepseek-reasoner"

tenants:
  - keys:
      - "sk-translator-a1"
      - "sk-translator-a2"
    name: "translator-a"
    upstream_id: "openai"
    allowed_models:
      - "gpt-4o-mini"
    system_prompt_file: "starsector-zh.txt"
    glossary_file: "starsector-terms.csv"

  - keys:
      - "sk-translator-b"
    name: "translator-b"
    upstream_id: "deepseek"
    allowed_models:
      - "deepseek-chat"
      - "deepseek-reasoner"
    system_prompt_file: "starsector-zh.txt"
    glossary_file: "starsector-terms.csv"
```

---

## 客户端接入

将原来指向 OpenAI 的 `base_url` 改为代理地址，`api_key` 换成分配给该租户的 Key，其余代码不变。

**Python（openai SDK）**

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://your-server:18080/v1",
    api_key="sk-translator-a1",
)

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "The flux level is critical, vent now."}],
)
print(response.choices[0].message.content)
# 幅能水平危急，立即主动排幅。
```

**curl**

```bash
curl http://your-server:18080/v1/chat/completions \
  -H "Authorization: Bearer sk-translator-a1" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "The flux level is critical, vent now."}]
  }'
```

---

## 错误码

| 状态码 | 原因 |
|--------|------|
| `401` | API Key 无效 |
| `400` | 未传 `model` 字段，或 model 不在允许列表中 |
| `403` | Referer 不在允许列表，或请求内容超出服务范围 |
| 上游状态码 | 上游返回的原始错误，响应体透传 |

---

## 目录结构

```
fossic-ai-proxy/
├── main.py              # FastAPI 入口
├── proxy.py             # 请求转发（流式 / 非流式）
├── injector.py          # 系统提示词与术语表注入
├── glossary.py          # 术语表加载与匹配
├── config.py            # 配置加载
├── config.yaml          # 运行配置（不入库）
├── config.yaml.example  # 配置示例
├── prompts/             # 提示词文件目录
│   └── starsector-zh.txt
├── glossary/            # 术语表目录
│   └── starsector-terms.csv
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
