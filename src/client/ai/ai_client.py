from typing import Protocol, Type, Optional, List, Dict
from pydantic import BaseModel


class AIClient(Protocol):
    def generate_session_id(self) -> str: ...

    async def structured_completion(
            self,
            system_message: str,
            user_message: str,
            response_schema: Type[BaseModel],
            session_id: Optional[str] = None,
            allowed_tools: Optional[List[str]] = None,
            base_session_id: Optional[str] = None,
            model: Optional[str] = None,
            hooks: Optional[Dict] = None
    ) -> BaseModel: ...
