from __future__ import annotations

from fastapi import HTTPException

from config import TenantConfig


def inject(body: dict, tenant: TenantConfig) -> dict:
    """
    1. 校验 model 字段存在，且在 tenant.allowed_models ∩ upstream.available_models 中
    2. 移除所有 role=system 的 message
    3. 在 messages 头部插入 tenant 配置的 system_prompt
    返回修改后的 body（浅拷贝，messages 列表为新对象）
    """
    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="Field 'model' is required.")

    if model not in tenant.allowed_models:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model}' is not in your allowed_models: {tenant.allowed_models}",
        )

    if model not in tenant.upstream.available_models:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model}' is not available in upstream '{tenant.upstream_id}'.",
        )

    raw_messages = body.get("messages", [])

    if tenant.max_user_messages is not None:
        user_msg_count = sum(1 for m in raw_messages if m.get("role") == "user")
        if user_msg_count > tenant.max_user_messages:
            raise HTTPException(
                status_code=400,
                detail=f"Too many user messages: {user_msg_count} (max {tenant.max_user_messages}).",
            )

    if tenant.max_chars is not None:
        total_chars = sum(len(m.get("content", "")) for m in raw_messages if isinstance(m.get("content"), str))
        if total_chars > tenant.max_chars:
            raise HTTPException(
                status_code=400,
                detail=f"Request too long: {total_chars} chars (max {tenant.max_chars}).",
            )

    messages = [m for m in raw_messages if m.get("role") != "system"]

    if tenant.system_prompt:
        messages = [{"role": "system", "content": tenant.system_prompt}] + messages

    if tenant.glossary:
        user_text = " ".join(
            m["content"] for m in messages
            if m.get("role") == "user" and isinstance(m.get("content"), str)
        )
        matches = tenant.glossary.find_matches(user_text)
        if matches:
            glossary_msg = tenant.glossary.build_system_message(matches)
            # 插入在主 system prompt 之后，对话消息之前
            insert_pos = 1 if tenant.system_prompt else 0
            messages.insert(insert_pos, {"role": "system", "content": glossary_msg})

    # 移除 Anthropic 格式的 thinking 字段，统一转换为 enable_thinking
    result = {k: v for k, v in body.items() if k not in ("messages", "thinking")}
    result["messages"] = messages

    if tenant.disable_thinking is not None:
        # 配置强制覆盖
        result["enable_thinking"] = not tenant.disable_thinking
    else:
        # 透传客户端设置：解析 thinking: {type: "enabled"/"disabled"}
        thinking = body.get("thinking")
        if isinstance(thinking, dict):
            result["enable_thinking"] = thinking.get("type") == "enabled"
        elif "enable_thinking" in body:
            result["enable_thinking"] = body["enable_thinking"]

    return result
