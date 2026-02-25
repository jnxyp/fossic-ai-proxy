# fossic-ai-proxy

一个轻量级 LLM API 代理，为每个用户注入指定的系统提示词，兼容 OpenAI `/v1/chat/completions` 接口。

## 功能

- 按用户 API Key 路由到不同上游 LLM
- 强制注入系统提示词（覆盖客户端传入的 system message）
- 按用户限制可用模型
- 支持流式（SSE）和非流式响应
- 系统提示词支持内联配置或外部 `.txt` 文件

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

users:
  - key: "sk-your-client-key"       # 分发给客户端的 Key（自定义）
    name: "alice"
    upstream_id: "openai-main"
    allowed_models:
      - "gpt-4o-mini"
    system_prompt: "你是 Alice 的专属助手，请用正式语气回答。"
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
| `id` | 上游唯一标识，供 user 引用 |
| `url` | 完整的上游接口地址 |
| `api_key` | 上游 API Key |
| `available_models` | 该上游支持的模型列表 |

### 用户（users）

| 字段 | 说明 |
|------|------|
| `key` | 分发给客户端的 API Key |
| `name` | 用户名（仅用于日志标识） |
| `upstream_id` | 对应上游的 `id` |
| `allowed_models` | 该用户允许使用的模型，必须是上游 `available_models` 的子集 |
| `system_prompt` | 内联系统提示词 |
| `system_prompt_file` | 从 `prompts/` 目录读取提示词文件（`.txt`），与 `system_prompt` 二选一 |

### 使用提示词文件

将 `.txt` 文件放入 `prompts/` 目录，在配置中引用文件名：

```yaml
users:
  - key: "sk-user-bob"
    name: "bob"
    upstream_id: "openai-main"
    allowed_models:
      - "gpt-4o"
    system_prompt_file: "bob.txt"   # 对应 prompts/bob.txt
```

`prompts/` 目录通过 volume 挂载到容器，修改文件后重启容器生效：

```bash
docker compose restart
```

---

## 多用户 / 多上游示例

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

users:
  - key: "sk-client-alice"
    name: "alice"
    upstream_id: "openai"
    allowed_models:
      - "gpt-4o-mini"
    system_prompt_file: "alice.txt"

  - key: "sk-client-bob"
    name: "bob"
    upstream_id: "deepseek"
    allowed_models:
      - "deepseek-chat"
      - "deepseek-reasoner"
    system_prompt: "You are Bob's assistant."
```

---

## 客户端接入

将原来指向 OpenAI 的 `base_url` 改为代理地址，`api_key` 换成分配给该用户的 Key，其余代码不变。

**Python（openai SDK）**

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://your-server:18080/v1",
    api_key="sk-client-alice",
)

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "你好"}],
)
print(response.choices[0].message.content)
```

**curl**

```bash
curl http://your-server:18080/v1/chat/completions \
  -H "Authorization: Bearer sk-client-alice" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "你好"}]
  }'
```

---

## 错误码

| 状态码 | 原因 |
|--------|------|
| `401` | API Key 无效 |
| `400` | 未传 `model` 字段，或 model 不在允许列表中 |
| 上游状态码 | 上游返回的原始错误，响应体透传 |

---

## 目录结构

```
fossic-ai-proxy/
├── main.py              # FastAPI 入口
├── proxy.py             # 请求转发（流式 / 非流式）
├── injector.py          # 系统提示词注入与模型校验
├── config.py            # 配置加载
├── config.yaml          # 运行配置（不入库）
├── config.yaml.example  # 配置示例
├── prompts/             # 提示词文件目录
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```
