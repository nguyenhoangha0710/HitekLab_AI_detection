"""Rule Engine cua AI Service.

Nhan ket qua detection + tracking theo tung frame, kiem tra zone/rule va sinh
AI Event gui sang Zone Service (/api/ai-events). Truoc day logic nay chay trong
JavaScript tren trinh duyet; nay chay phia server nen canh bao van duoc tao du
khong co ai mo dashboard.
"""

from .config_provider import StaticConfigProvider, ZoneServiceConfigProvider
from .engine import RuleEngine, RuleEngineSettings
from .models import RuleConfig, ZoneConfig
from .publisher import AiEventPublisher, InMemoryPublisher

__all__ = [
    "AiEventPublisher",
    "InMemoryPublisher",
    "RuleConfig",
    "RuleEngine",
    "RuleEngineSettings",
    "StaticConfigProvider",
    "ZoneConfig",
    "ZoneServiceConfigProvider",
]
