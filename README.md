# fossic-ai-proxy

一个面向翻译场景的 LLM API 代理系统，兼容 OpenAI `/v1/chat/completions` 接口。

## 组成

### [proxy-server](./proxy-server/)

核心代理服务。接收客户端请求，按租户注入系统提示词和术语表，转发到上游 LLM，记录用量。

### [terms-fetcher](./terms-fetcher/)

附属服务。定期从 [ParaTranz](https://paratranz.cn) 翻译平台拉取术语，写入 `proxy-server/glossary/` 供代理热加载。

## 启动

```bash
# 配置
cp proxy-server/config.yaml.example proxy-server/config.yaml
cp terms-fetcher/config.yaml.example terms-fetcher/config.yaml
# 编辑两个 config.yaml，填入 API Key

docker compose up -d
```
