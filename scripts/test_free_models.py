import asyncio
import sys
import os
import httpx

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.core.config import settings
from agents.client import LLMClient

async def get_free_models():
    async with httpx.AsyncClient() as client:
        response = await client.get("https://openrouter.ai/api/v1/models")
        data = response.json()
        free_models = []
        for model in data.get("data", []):
            pricing = model.get("pricing", {})
            # Pricing values are strings like "0" or "0.0"
            prompt_price = float(pricing.get("prompt", -1))
            comp_price = float(pricing.get("completion", -1))
            if prompt_price == 0.0 and comp_price == 0.0:
                free_models.append(model["id"])
        return free_models

async def get_opencode_models(api_key: str):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                "https://api.opencode.ai/v1/models",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            data = response.json()
            return [m["id"] for m in data.get("data", [])]
        except Exception:
            return []

async def test_model(client, model_id):
    try:
        response = await client._get_client()
        resp = await response.post(
            "/chat/completions",
            json={
                "model": model_id,
                "messages": [{"role": "user", "content": "Say 'hello' in one word."}],
                "max_tokens": 10
            },
            timeout=5
        )
        resp.raise_for_status()
        try:
            resp.json()
        except Exception:
            return f"FAILED (200 OK, but not JSON: {resp.text[:100]})"
        return "SUCCESS"
    except httpx.HTTPStatusError as e:
        return f"FAILED (HTTP {e.response.status_code}: {e.response.text[:100]})"
    except Exception as e:
        return f"FAILED ({type(e).__name__})"

async def main():
    print("\n=== OPENCODE MODELS ===")
    oc_key = settings.opencode_api_key
    if not oc_key:
        print("No OpenCode API key found.")
    else:
        oc_models = [
            "meta-llama-3.1-8b-instruct-free",
            "qwen-2.5-coder-32b-instruct-free",
            "meta-llama-3.1-70b-instruct-free",
            "qwen-2.5-72b-instruct-free"
        ]
        print(f"Testing {len(oc_models)} OpenCode models from configs/models.yaml...\n")
        oc_client = LLMClient(api_key=oc_key, base_url="https://api.opencode.ai/v1")
        for model_id in oc_models:
            print(f"Testing {model_id:<50} ...")
            sys.stdout.flush()
            result = await test_model(oc_client, model_id)
            print(result)
            sys.stdout.flush()
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())
