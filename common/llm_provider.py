"""
Модуль для взаємодії з різними LLM провайдерами.
Забезпечує єдиний інтерфейс для роботи з різними моделями.
"""
from typing import Dict, Any, List, Optional, Union
import httpx
import json
import os
import asyncio
from abc import ABC, abstractmethod

MAX_PROMPT_LENGTH = 10000
MAX_CONTEXT_SIZE = 100000

class LLMProvider(ABC):
    """Базовий клас для всіх LLM провайдерів."""
    
    def __init__(self, provider_name: str):
        self.provider_name = provider_name
    
    @abstractmethod
    async def generate_response(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Генерація відповіді на основі запиту та контексту."""
        pass
    
    @abstractmethod
    async def is_available(self) -> bool:
        """Перевірка доступності провайдера."""
        pass

class ClaudeProvider(LLMProvider):
    """Провайдер для роботи з Claude від Anthropic."""
    
    def __init__(self, model: str = "claude-3-7-sonnet-latest"):
        super().__init__("claude")
        self.model = model
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        self.api_url = "https://api.anthropic.com/v1/messages"
        self.cache = {}  # Простий кеш відповідей
        
        if not self.api_key:
            print("УВАГА: Змінна оточення ANTHROPIC_API_KEY не знайдена")
    
    async def is_available(self) -> bool:
        """Перевірка доступності API ключа Claude."""
        return self.api_key is not None
    
    async def validate_mcp_access(self, context: Dict[str, Any]) -> bool:
        """Перевірка прав доступу через MCP сервер"""
        if not context:
            return False
            
        # Перевірка необхідних полів у контексті
        required_fields = ["user_role", "mcp_server_url", "mcp_token"]
        if not all(field in context for field in required_fields):
            print("Помилка: Відсутні обов'язкові поля в контексті для MCP")
            return False
            
        return True
    
    async def validate_context(self, context: Dict[str, Any]) -> bool:
        """Валідація даних в контексті"""
        required_fields = ["user_id", "user_role"]
        if not all(field in context for field in required_fields):
            return False
        
        # Додаткові перевірки для MCP
        if context.get("use_mcp", False):
            if not all(field in context for field in ["mcp_server_url", "mcp_token"]):
                return False
        
        return True
    
    async def get_cached_response(self, prompt: str, context: Dict[str, Any]) -> Optional[str]:
        cache_key = f"{prompt}:{json.dumps(context)}"
        return self.cache.get(cache_key)
    
    async def _call_mcp_api(self, function: str, params: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Виклик API через MCP сервер"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{context['mcp_server_url']}/webservice/rest/server.php",
                    params={
                        "wstoken": context["mcp_token"],
                        "wsfunction": function,
                        "moodlewsrestformat": "json",
                        **params
                    }
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            print(f"Помилка виклику MCP API: {e}")
            return {"error": str(e)}
    
    async def generate_response(self, prompt: str, context: Optional[Dict[str, Any]] = None, use_mcp: bool = False, mcp_server_url: Optional[str] = None, mcp_token: Optional[str] = None) -> str:
        """Генерація відповіді з використанням API Claude."""
        print(f"Генерація відповіді для користувача {context.get('user_id')} в режимі {context.get('mode')}")
        if not self.api_key:
            return "Помилка: API ключ для Claude не налаштовано. Додайте ANTHROPIC_API_KEY у файл .env."
        
        # Валідація контексту
        if context and not await self.validate_context(context):
            return "Помилка: Некоректний контекст"
        
        if len(prompt) > MAX_PROMPT_LENGTH:
            return "Помилка: Занадто довгий запит"
        
        if context and len(json.dumps(context)) > MAX_CONTEXT_SIZE:
            return "Помилка: Занадто великий контекст"
        
        # Додавання MCP параметрів до контексту
        if use_mcp and mcp_server_url and mcp_token:
            if not context:
                context = {}
            context.update({
                "use_mcp": True,
                "mcp_server_url": mcp_server_url,
                "mcp_token": mcp_token
            })
        
        # Підготовка системного промпту
        system_prompt = """Ви корисний асистент для навчальної платформи Moodle. 
        Ти отримуєш інформацію про навчальні дисципліни та активність студентів через MCP сервер.
        Для отримання даних використовуй наступні інструменти:
        1. core_course_get_courses - отримання інформації про курси
        2. core_course_get_contents - отримання вмісту курсу
        3. core_enrol_get_enrolled_users - отримання списку студентів
        4. mod_assign_get_assignments - отримання завдань
        5. mod_assign_get_submissions - отримання зданих робіт
        6. gradereport_user_get_grade_items - отримання оцінок
        7. core_user_get_users_by_field - отримання інформації про користувачів
        
        Не використовуй жодних інших джерел для відповіді.
        Відповідайте українською мовою, якщо явно не зазначено інше."""
        
        if context:
            if "system_prompt" in context:
                system_prompt = context["system_prompt"]
            
            # Додавання базової інформації про користувача та курс
            context_text = []
            if "user_role" in context:
                context_text.append(f"Роль користувача: {context['user_role']}")
            if "mode" in context:
                context_text.append(f"Режим: {context['mode']}")
            if "selected_course" in context:
                context_text.append(f"Обраний курс ID: {context['selected_course']}")
            if "selected_course_name" in context:
                context_text.append(f"Назва курсу: {context['selected_course_name']}")
            
            if context_text:
                system_prompt += "\n\n" + "\n".join(context_text)
        
        # Підготовка запиту до Claude
        headers = {
            "x-api-key": self.api_key,
            "content-type": "application/json",
            "anthropic-version": "2023-06-01"
        }
        
        data = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "system": system_prompt,
            "max_tokens": 8000
        }
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self.api_url,
                    headers=headers,
                    json=data
                )
                response.raise_for_status()
                result = response.json()
                
                # Отримання текстової відповіді
                content = result.get("content", [])
                text_chunks = []
                
                for item in content:
                    if item.get("type") == "text":
                        text_chunks.append(item.get("text", ""))
                
                return "".join(text_chunks) if text_chunks else "Помилка: Не вдалося отримати текстову відповідь від Claude API."
                
        except httpx.HTTPStatusError as e:
            error_msg = f"Помилка HTTP при виклику Claude API: {e.response.status_code}"
            try:
                error_data = e.response.json()
                if "error" in error_data:
                    error_msg += f"\nДеталі: {error_data['error'].get('message', '')}"
            except:
                pass
            print(error_msg)
            return f"Помилка генерації відповіді: {error_msg}"
        except Exception as e:
            error_msg = f"Помилка взаємодії з Claude API: {str(e)}"
            print(error_msg)
            return f"Помилка генерації відповіді: {error_msg}"

class LLMProviderFactory:
    """Фабрика для створення екземплярів LLM провайдерів."""
    
    @staticmethod
    async def create_provider(provider_name: str, **kwargs) -> Optional[LLMProvider]:
        """Створення екземпляра LLM провайдера."""
        try:
            if provider_name.lower() == "claude":
                provider = ClaudeProvider(**kwargs)
                if await provider.is_available():
                    return provider
                else:
                    print(f"Провайдер {provider_name} недоступний (відсутній API ключ)")
                    return None
            else:
                print(f"Непідтримуваний провайдер: {provider_name}")
                return None
        except Exception as e:
            print(f"Помилка створення провайдера {provider_name}: {e}")
            return None