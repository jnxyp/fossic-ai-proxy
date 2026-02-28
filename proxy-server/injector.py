from __future__ import annotations

from fastapi import HTTPException

from config import AgentConfig, TenantConfig


def inject(body: dict, tenant: TenantConfig, agent: AgentConfig | None = None) -> dict:
    """
    1. 校验请求限制（消息数、字符数）
    2. 移除所有 role=system 的 message
    3. 注入 agent 的 system_prompt 和 glossary
       - glossary_mode="system_message"（默认）：注入为 system message
       - glossary_mode="translation_options"：注入为 translation_options.terms 列表
    4. 强制使用 agent.model，合并 agent.extra_body（agent 优先）
    返回修改后的 body（浅拷贝，messages 列表为新对象）
    """
    agent = agent or tenant.agent
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

    # Glossary injection - compute content regardless of position
    glossary_system_text: str | None = None
    glossary_terms: list[dict] | None = None
    if agent.glossary:
        user_text = " ".join(
            m["content"] for m in messages
            if m.get("role") == "user" and isinstance(m.get("content"), str)
        )
        matches = agent.glossary.find_matches(user_text)
        if matches:
            if agent.glossary_mode == "translation_options":
                # qwen-mt mode: build {source, target} pairs (include all variant forms)
                seen: set[str] = set()
                glossary_terms = []
                for t in matches:
                    for form in t.all_forms():
                        if form not in seen:
                            glossary_terms.append({"source": form, "target": t.chinese})
                            seen.add(form)
            else:
                # Standard mode: inject matched terms as a system message (position will be determined below)
                glossary_system_text = agent.glossary.build_system_message(matches)

    # Insert system_prompt + glossary based on position
    if agent.system_prompt_position == "user_prefix":
        # Prepend to first user message
        parts = [p for p in [agent.system_prompt, glossary_system_text] if p]
        if parts:
            prefix = "\n\n".join(parts)
            for i, msg in enumerate(messages):
                if msg.get("role") == "user" and isinstance(msg.get("content"), str):
                    messages[i] = {**msg, "content": f"{prefix}\n\n{msg['content']}"}
                    break
            else:
                # No user message found - fallback to system message
                if agent.system_prompt:
                    messages = [{"role": "system", "content": agent.system_prompt}] + messages
    else:
        # Default "system" mode: merge system_prompt + glossary into a single system message
        parts = [p for p in [agent.system_prompt, glossary_system_text] if p]
        if parts:
            messages = [{"role": "system", "content": "\n\n".join(parts)}] + messages

    # 从客户端 body 复制其他字段，排除 messages / thinking / model
    result = {k: v for k, v in body.items() if k not in ("messages", "thinking", "model")}
    # agent.extra_body 优先（覆盖同名客户端字段）
    result.update(agent.extra_body)
    # agent.model 强制覆盖
    result["model"] = agent.model
    result["messages"] = messages

    # 将匹配到的术语追加进 translation_options.terms
    if glossary_terms is not None:
        result["translation_options"] = {**result.get("translation_options", {}), "terms": glossary_terms}

    # 移除 Anthropic 格式的 thinking 字段，统一转换为 enable_thinking
    if agent.enable_thinking is not None:
        result["enable_thinking"] = agent.enable_thinking
    else:
        thinking = body.get("thinking")
        if isinstance(thinking, dict):
            result["enable_thinking"] = thinking.get("type") == "enabled"
        elif "enable_thinking" in body:
            result["enable_thinking"] = body["enable_thinking"]

    return result
