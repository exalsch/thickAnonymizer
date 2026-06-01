def build_prompt(text: str, categories: list[str], custom_instruction: str = "") -> str:
    cats = ", ".join(categories)
    extra = f"\nAdditional guidance: {custom_instruction}" if custom_instruction.strip() else ""
    return (
        "You extract sensitive data spans from text.\n"
        f"Categories to find: {cats}.{extra}\n"
        "Return ONLY a JSON array of objects with keys \"type\" (one of the "
        "categories) and \"text\" (the exact substring, copied verbatim from the "
        "input). Do not include offsets. If nothing is found, return [].\n"
        "----- INPUT -----\n"
        f"{text}\n"
        "----- END INPUT -----"
    )
