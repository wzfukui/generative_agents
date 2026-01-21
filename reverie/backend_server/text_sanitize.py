import re


def world_sanitize(text: str) -> str:
  if not text:
    return text
  sanitized = re.sub(r"\([^)]*\)", "", text)
  sanitized = re.sub(r"（[^）]*）", "", sanitized)
  sanitized = re.sub(
    r"[^，。！？、]*\b(?:College|Dorm|University)\b[^，。！？、]*",
    "",
    sanitized,
  )
  sanitized = re.sub(r"\s{2,}", " ", sanitized).strip()
  return sanitized
