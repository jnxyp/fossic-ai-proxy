from __future__ import annotations

from fastapi import HTTPException

from config import UserConfig


def inject(body: dict, user: UserConfig) -> dict:
    """
    1. 校验 model 字段存在，且在 user.allowed_models ∩ upstream.available_models 中
    2. 移除所有 role=system 的 message
    3. 在 messages 头部插入用户配置的 system_prompt
    返回修改后的 body（浅拷贝，messages 列表为新对象）
    """
    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="Field 'model' is required.")

    if model not in user.allowed_models:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model}' is not in your allowed_models: {user.allowed_models}",
        )

    if model not in user.upstream.available_models:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model}' is not available in upstream '{user.upstream_id}'.",
        )

    messages = [m for m in body.get("messages", []) if m.get("role") != "system"]

    if user.system_prompt:
        messages = [{"role": "system", "content": user.system_prompt}] + messages

    if user.glossary:
        user_text = " ".join(
            m["content"] for m in messages
            if m.get("role") == "user" and isinstance(m.get("content"), str)
        )
        matches = user.glossary.find_matches(user_text)
        if matches:
            glossary_msg = user.glossary.build_system_message(matches)
            # 插入在主 system prompt 之后，对话消息之前
            insert_pos = 1 if user.system_prompt else 0
            messages.insert(insert_pos, {"role": "system", "content": glossary_msg})

    result = {**body, "messages": messages}
    if user.disable_thinking:
        result["enable_thinking"] = False
    return result
