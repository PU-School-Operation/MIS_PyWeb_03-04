import os
from pathlib import Path
from google import genai
from google.genai import types

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_local_env_file(env_path):
    if not env_path.exists():
        return

    with env_path.open("r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key and key not in os.environ:
                os.environ[key] = value


def _get_gemini_api_key():
    return (
        os.getenv("GOOGLE_API_KEY")
        or os.getenv("google_API_key")
        or os.getenv("google_api_key")
    )


def _get_gemini_model():
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def ai_config(token=4960):
    return types.GenerateContentConfig(max_output_tokens=token)


def create_client():
    _load_local_env_file(BASE_DIR / ".env")

    api_key = _get_gemini_api_key()
    if not api_key:
        raise RuntimeError(
            "找不到 Gemini API Key，請確認專案根目錄的 .env 是否設定 GOOGLE_API_KEY"
        )

    return genai.Client(api_key=api_key)


def ask_gemini(question, token=1024, model=None):
    client = create_client()
    response = client.models.generate_content(
        model=model or _get_gemini_model(),
        contents=question,
        config=ai_config(token),
    )
    return response.text or ""


def main():
    response1 = ask_gemini("靜宜資管有什麼特色", token=4960)
    print("--- 第一輪回應 ---")
    print(response1)

    response2 = ask_gemini("可否提供該科系相關的笑話", token=4960)
    print("\n--- 第二輪回應 ---")
    print(response2)


if __name__ == "__main__":
    main()
