from typing import List, Dict, Optional
from datetime import datetime, timedelta
from enum import Enum, auto

class Priority(Enum):
    SAFETY_KILLSWITCH = auto()
    APPROVAL = auto()
    FAILED_PRECONDITION = auto()
    EFFECT_AMBIGUITY = auto()
    BLOCKER = auto()
    GOAL_ANCHOR_DRIFT = auto()
    COMPLETED_BACKGROUND_WORK = auto()
    STALE_CRITICAL_BELIEF = auto()
    USER_INTERVENTION = auto()
    DEADLINE_BUDGET = auto()
    NORMAL_PROGRESS = auto()
    OPTIONAL_LEARNING = auto()

class AttentionItem:
    def __init__(
        self,
        source: str,
        reason: str,
        priority: Priority,
        expiry: Optional[datetime] = None,
        run_id: Optional[str] = None,
        acknowledged: bool = False,
    ):
        self.source = source
        self.reason = reason
        self.priority = priority
        self.expiry = expiry
        self.run_id = run_id
        self.acknowledged = acknowledged

    def is_expired(self) -> bool:
        return self.expiry is not None and datetime.now() > self.expiry

class AttentionSchema:
    def __init__(self, max_items: int = 100):
        self.max_items = max_items
        self.items: List[AttentionItem] = []

    def add_item(self, item: AttentionItem) -> None:
        self.items.append(item)
        if len(self.items) > self.max_items:
            self._compact()

    def _compact(self) -> None:
        # Remove expired and acknowledged items first
        self.items = [item for item in self.items if not (item.is_expired() or item.acknowledged)]

        # If still over limit, keep the highest-priority items. Lower
        # Priority.value means higher priority (SAFETY_KILLSWITCH=1 first).
        if len(self.items) > self.max_items:
            self.items.sort(key=lambda x: x.priority.value)
            self.items = self.items[:self.max_items]

    def get_highest_priority(self) -> Optional[AttentionItem]:
        if not self.items:
            return None
        return min(self.items, key=lambda x: x.priority.value)

    def acknowledge(self, source: str) -> None:
        for item in self.items:
            if item.source == source:
                item.acknowledged = True

class GlobalWorkspace:
    def __init__(self, attention_schema: AttentionSchema):
        self.attention_schema = attention_schema
        self.context: Dict[str, str] = {}

    def update_context(self, key: str, value: str) -> None:
        self.context[key] = value

    def get_relevant_context(self) -> Dict[str, str]:
        highest_priority = self.attention_schema.get_highest_priority()
        if highest_priority is None:
            return {}
        
        relevant_context = {
            "attention_source": highest_priority.source,
            "attention_reason": highest_priority.reason,
            "attention_priority": highest_priority.priority.name,
        }
        relevant_context.update(self.context)
        return relevant_context