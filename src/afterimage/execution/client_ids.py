def client_order_id(session_id: str, intent_hash: str, attempt: int = 1) -> str:
    if attempt not in (1, 2, 3):
        raise ValueError("execution attempts are bounded to initial plus two reprices")
    return f"afterimage-{session_id.replace('-', '')[:8]}-{intent_hash[:12]}-{attempt}"
