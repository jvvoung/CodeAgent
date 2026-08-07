import os
import asyncio
from collections.abc import AsyncIterator

import httpx


class OllamaClient:
    def __init__(self, base: str | None = None) -> None:
        self.base = (base or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{self.base}/api/tags")
            response.raise_for_status()
            return sorted(model["name"] for model in response.json().get("models", []))

    async def model_capabilities(self, model: str) -> list[str]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self.base}/api/show", json={"model": model})
            response.raise_for_status()
            return response.json().get("capabilities", [])

    async def list_model_details(self) -> list[dict]:
        names = await self.list_models()
        capabilities = await asyncio.gather(
            *(self.model_capabilities(name) for name in names), return_exceptions=True
        )
        return [
            {
                "name": name,
                "capabilities": value if isinstance(value, list) else [],
                "supports_tools": isinstance(value, list) and "tools" in value,
            }
            for name, value in zip(names, capabilities)
        ]

    async def chat(self, model: str, messages: list[dict], tools: list[dict]) -> dict:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=5)) as client:
            response = await client.post(
                f"{self.base}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "tools": tools,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 1536},
                },
            )
            if response.is_error:
                try:
                    detail = response.json().get("error", response.text)
                except ValueError:
                    detail = response.text
                raise RuntimeError(f"Ollama 요청 오류: {detail or response.status_code}")
            return response.json()["message"]

    async def chat_stream(self, model: str, messages: list[dict]) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=5)) as client:
            async with client.stream(
                "POST", f"{self.base}/api/chat", json={"model": model, "messages": messages, "stream": True}
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        yield line
