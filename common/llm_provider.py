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

    async def _call_mcp_api(self, function: str, params: Dict[str, Any], mcp_server_url: str, mcp_token: str) -> Dict[str, Any]:
        """Виклик API Moodle через MCP сервер."""
        try:
            print(f"Виклик Moodle API через MCP: {function} з параметрами {params}")
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{mcp_server_url}/webservice/rest/server.php",
                    params={
                        "wstoken": mcp_token,
                        "wsfunction": function,
                        "moodlewsrestformat": "json",
                        **params
                    }
                )
                response.raise_for_status()
                data = response.json()
                
                # Перевірка на помилки у відповіді Moodle
                if isinstance(data, dict) and "exception" in data:
                    print(f"Помилка Moodle API: {data.get('message', 'Невідома помилка')}")
                    return {"error": data.get('message', 'Невідома помилка Moodle API')}
                
                print(f"Успішна відповідь від MCP API {function}")
                return data
        except Exception as e:
            print(f"Помилка виклику MCP API {function}: {e}")
            return {"error": str(e)}
            
    async def _prepare_mcp_context(self, context: Dict[str, Any], mcp_server_url: str, mcp_token: str) -> str:
        """Підготовка контексту з даними з MCP."""
        # Додаємо в контекст дані про студентів, оцінки і завдання з MCP
        mcp_data = {}
        
        try:
            # Якщо вибрано курс, отримуємо студентів
            if "selected_course" in context or "course" in context:
                course_id = context.get("selected_course") or context.get("course", {}).get("id")
                if course_id:
                    # Отримання студентів курсу
                    students_data = await self._call_mcp_api("core_enrol_get_enrolled_users", 
                                                            {"courseid": course_id}, 
                                                            mcp_server_url, mcp_token)
                    if not isinstance(students_data, dict) or "error" not in students_data:
                        # Фільтруємо тільки студентів
                        students = [user for user in students_data if any(role.get('shortname') == 'student' for role in user.get('roles', []))]
                        mcp_data["students"] = students
                        print(f"Отримано {len(students)} студентів через MCP для курсу {course_id}")
                    
                    # Отримання завдань курсу
                    assignments_data = await self._call_mcp_api("mod_assign_get_assignments", 
                                                               {"courseids[0]": course_id}, 
                                                               mcp_server_url, mcp_token)
                    if not isinstance(assignments_data, dict) or "error" not in assignments_data:
                        if "courses" in assignments_data:
                            for course in assignments_data["courses"]:
                                if str(course.get('id')) == str(course_id):
                                    mcp_data["assignments"] = course.get("assignments", [])
                                    print(f"Отримано {len(mcp_data.get('assignments', []))} завдань через MCP")
        except Exception as e:
            print(f"Помилка при підготовці MCP контексту: {e}")
        
        # Повертаємо форматований контекст для додавання до системного промпту
        if mcp_data:
            mcp_context = "# Дані з Moodle, отримані через MCP:\n\n"
            
            # Додаємо дані про студентів
            if "students" in mcp_data and mcp_data["students"]:
                mcp_context += "## Студенти курсу:\n"
                for i, student in enumerate(mcp_data["students"][:20]):  # Обмежуємо до 20 студентів
                    mcp_context += f"{i+1}. {student.get('fullname', 'Невідомо')} (ID: {student.get('id', 'N/A')}, Email: {student.get('email', 'N/A')})\n"
                if len(mcp_data["students"]) > 20:
                    mcp_context += f"...та ще {len(mcp_data['students']) - 20} студентів.\n"
                mcp_context += f"\nВсього студентів: {len(mcp_data['students'])}\n\n"
            
            # Додаємо дані про завдання
            if "assignments" in mcp_data and mcp_data["assignments"]:
                mcp_context += "## Завдання курсу:\n"
                for i, assignment in enumerate(mcp_data["assignments"]):
                    due_date = "Не встановлено"
                    if assignment.get("duedate") and assignment["duedate"] > 0:
                        from datetime import datetime
                        due_date = datetime.fromtimestamp(assignment["duedate"]).strftime('%d.%m.%Y %H:%M')
                    
                    mcp_context += f"{i+1}. {assignment.get('name', 'Без назви')} (ID: {assignment.get('id', 'N/A')}, Термін: {due_date})\n"
                mcp_context += f"\nВсього завдань: {len(mcp_data['assignments'])}\n\n"
            
            return mcp_context
        
        return ""
    
    async def generate_response(self, prompt: str, context: Optional[Dict[str, Any]] = None, use_mcp: bool = False, mcp_server_url: Optional[str] = None, mcp_token: Optional[str] = None) -> str:
        """Генерація відповіді з використанням API Claude."""
        print(f"Генерація відповіді для користувача {context.get('user_id')} в режимі {context.get('mode')}")
        if not self.api_key:
            return "Помилка: API ключ для Claude не налаштовано. Додайте ANTHROPIC_API_KEY у файл .env."
        
        if len(prompt) > MAX_PROMPT_LENGTH:
            return "Помилка: Занадто довгий запит"
        
        if context and len(json.dumps(context)) > MAX_CONTEXT_SIZE:
            return "Помилка: Занадто великий контекст"
        
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
        Відповідайте українською мовою, якщо явно не зазначено інше.
        
        ВАЖЛИВО: МИ ВЖЕ ОТРИМАЛИ ДЛЯ ТЕБЕ НЕОБХІДНІ ДАНІ З MOODLE. ТОБІ НЕ ПОТРІБНО ВИКЛИКАТИ API НАПРЯМУ.
        НЕ ПИШИ ВИГАДАНИЙ КОД ДЛЯ ВИКЛИКУ API. ВИКОРИСТОВУЙ ЛИШЕ ДАНІ, ЯКІ МИ НАДАЛИ ТОБІ В КОНТЕКСТІ.
        """
        
        # Отримуємо дані з MCP, якщо це потрібно
        mcp_context = ""
        if use_mcp and mcp_server_url and mcp_token:
            try:
                mcp_context = await self._prepare_mcp_context(context, mcp_server_url, mcp_token)
                if mcp_context:
                    system_prompt += "\n\n" + mcp_context
            except Exception as e:
                print(f"Помилка при отриманні даних через MCP: {e}")
        
        if context:
            if "system_prompt" in context:
                # Додаємо базовий системний промпт, потім додаємо користувацький
                base_system = system_prompt
                user_system = context["system_prompt"]
                system_prompt = f"{base_system}\n\n{user_system}"
            
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
        
        # Підготовка повідомлень з історії чату (якщо є)
        messages = []
        if context and "messages" in context and isinstance(context["messages"], list):
            messages = context["messages"]
        elif messages == [] and prompt:
            # Якщо немає історії, створюємо одне повідомлення
            messages = [{"role": "user", "content": prompt}]
            
        # Підготовка запиту до Claude
        headers = {
            "x-api-key": self.api_key,
            "content-type": "application/json",
            "anthropic-version": "2023-06-01"
        }
        
        data = {
            "model": self.model,
            "messages": messages,
            "system": system_prompt,
            "max_tokens": 8000
        }
        
        try:
            print(f"Відправка запиту до Claude API, модель: {self.model}")
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