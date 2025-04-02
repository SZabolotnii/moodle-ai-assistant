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
        
        if not self.api_key:
            print("УВАГА: Змінна оточення ANTHROPIC_API_KEY не знайдена")
    
    async def is_available(self) -> bool:
        """Перевірка доступності API ключа Claude."""
        return self.api_key is not None
    
    async def generate_response(self, prompt: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Генерація відповіді з використанням API Claude."""
        if not self.api_key:
            return "Помилка: API ключ для Claude не налаштовано. Додайте ANTHROPIC_API_KEY у файл .env."
        
        headers = {
            "x-api-key": self.api_key,
            "content-type": "application/json",
            "anthropic-version": "2023-06-01"
        }
        
        # Підготовка системного промпту на основі контексту
        system_prompt = "Ви корисний асистент для навчальної платформи Moodle. Відповідайте українською мовою, якщо явно не зазначено інше."
        
        if context:
            if "system_prompt" in context:
                system_prompt = context["system_prompt"]
            else:
                # Додавання контекстної інформації
                context_text = []
                if "course" in context:
                    context_text.append(f"Інформація про курс: {context['course']}")
                if "assignments" in context:
                    context_text.append(f"Завдання курсу: {context['assignments']}")
                if "students" in context:
                    context_text.append(f"Студенти курсу: {context['students']}")
                if "user_role" in context:
                    context_text.append(f"Роль користувача: {context['user_role']}")
                if "mode" in context:
                    context_text.append(f"Режим: {context['mode']}")
                
                if context_text:
                    system_prompt += "\n\n" + "\n".join(context_text)
        
        data = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "system": system_prompt,
            "max_tokens": 4000
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
                
                # Отримання текстової відповіді з JSON-відповіді Claude API
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