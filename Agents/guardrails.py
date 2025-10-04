def sanitize_input(text: str) -> str:
    """Basic guardrail to prevent malicious or irrelevant input."""
    banned = ["delete", "drop", "sudo", "hack", "rm -rf", "password", "api_key"]
    for word in banned:
        if word.lower() in text.lower():
            raise ValueError("⚠️ Unsafe or disallowed input detected.")
    return text.strip()
