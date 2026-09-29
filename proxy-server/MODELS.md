# 翻译模型与路由

2026-09-29（UTC）更新。部署配置 `config.yaml` 含凭据，不进入 Git。

| 租户 | 默认代理 / 模型 | 重复请求加强档 |
|------|-----------------|----------------|
| starsector_translate_qwen | starsector-qwen-max / qwen3.8-max，不思考 | starsector-qwen-max-thinking / 同模型，thinking_budget=2000 |
| starsector_translate_deepseek | starsector-deepseek-chat / deepseek-flash，thinking.type=disabled | starsector-deepseek-reasoner / 同模型，thinking.type=enabled |
| starsector_translate_glm | starsector-glm / glm-5.3，reasoning_effort=low | starsector-glm-thinking / 同模型，reasoning_effort=high |
| starsector_translate_qwen_mt | starsector-qwen-mt-flash / qwen-mt-flash | starsector-qwen-mt-plus / qwen-mt-plus |

Qwen 通用代理使用既有 `aliyun-sig` 新加坡上游；Qwen-MT 使用 `aliyun-us`。通用 Qwen Plus 及旧 qwen-max 配置已移除；Qwen-MT Plus 是独立的专用翻译模型，继续保留。DeepSeek 的代理 ID 为兼容历史保留，实际模型为 V4.1 Flash 的 `deepseek-flash`。

## 配置行为

- Upstream → Agent → Tenant：客户端 `model` 始终被代理配置覆盖。`available_models` 是清单，不会自动发现新模型，也不承担运行时模型校验。
- 同一密钥、同一 IP 的相同 messages 在默认 600 秒内重发，切换到加强代理；这不是上游失败自动重试。
- 每个入口的客户端消息总长度上限为 10000 字符；注入的提示词与术语另外占用上游 token。
- 三条通用模型线路的 `max_tokens` 均为 16384，避免旧 3000 上限截断长译文或思考。上限并非固定消耗量。
- Qwen 使用 `enable_thinking`；DeepSeek 与 GLM 使用 `extra_body.thinking`。配置原生 thinking 时删除客户端的 `enable_thinking`，保留配置优先级。GLM-5.3 始终开启思考。
- 配置了 `reasoning_effort` 时清除客户端 `thinking_budget`；配置了 `thinking_budget` 时清除客户端 `reasoning_effort`，避免 Qwen 参数互斥错误。
- Qwen-MT 保留 `translation_options` 术语注入；MT Plus 保留非流式请求转 SSE。

## 验证和发布

在仓库根目录创建隔离 Python 环境，安装 `proxy-server/requirements.txt` 和 `pytest`，从 `proxy-server/` 执行 `python -X utf8 -m pytest -q`。Python 3.14 使用 `asyncio.run` 驱动测试协程。

发布前备份线上配置和镜像，用候选配置验证 8 个代理的真实翻译，再只重建 `proxy-server`。配置与代码必须配套发布，不能只替换模型名。测试默认/加强档、SSE、占位符、术语、换行、CORS、长度限制；发布后查 Loki。保留旧配置和镜像用于回滚，但旧模型名是否仍受供应商支持须另行验证。

官方资料：[Qwen 模型](https://www.alibabacloud.com/help/en/model-studio/models)、[GLM-5.3](https://docs.z.ai/guides/llm/glm-5.3)、[DeepSeek 更新](https://api-docs.deepseek.com/updates/)。
