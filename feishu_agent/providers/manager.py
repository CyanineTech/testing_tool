from typing import List, Optional, Sequence

from feishu_agent.config import Settings, load_settings
from feishu_agent.providers.base import LlmProvider, ProviderRequest, ProviderResult
from feishu_agent.providers.claude_code import ClaudeCodeProvider
from feishu_agent.providers.copilot_cli import CopilotCliProvider
from feishu_agent.providers.openai_sdk import OpenAIProvider


SETTINGS: Optional[Settings] = None


def _resolve_settings(settings: Optional[Settings] = None) -> Settings:
    if settings is not None:
        return settings

    global SETTINGS
    if SETTINGS is None:
        SETTINGS = load_settings()
    return SETTINGS


class ProviderManager:
    def __init__(self, providers: Optional[Sequence[LlmProvider]] = None, settings: Optional[Settings] = None) -> None:
        resolved_settings = _resolve_settings(settings)
        if providers is None:
            provider_settings = resolved_settings if isinstance(resolved_settings, Settings) else None
            provider_map = {
                "openai_sdk": OpenAIProvider(settings=provider_settings),
                "copilot_cli": CopilotCliProvider(),
                "claude_code": ClaudeCodeProvider(),
            }
            ordered = []
            for name in (
                resolved_settings.provider.mode,
                resolved_settings.provider.fallback_mode,
                "claude_code",
            ):
                provider = provider_map.get(name)
                if provider and provider not in ordered:
                    ordered.append(provider)
            self.providers = ordered
        else:
            self.providers = list(providers)

    def select_provider(self) -> Optional[LlmProvider]:
        for provider in self.providers:
            if provider.available():
                return provider
        return None

    def run_review(self, request: ProviderRequest) -> ProviderResult:
        provider = self.select_provider()
        if provider is None:
            return ProviderResult(
                provider_name="none",
                summary="当前没有可用的本机 AI CLI provider。",
                next_steps=(),
                confidence="low",
            )
        return provider.run(request)
