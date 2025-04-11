#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Автоматичне тестування MCP сервера для Moodle
Перевіряє наявність/відсутність дозволів наданих Адміном Moodle для API_MOODLE_TOKEN
"""

import asyncio
import json
import argparse
import sys
import os
import httpx
from mcp_python import MCPClient, MCPClientConfig
from typing import Dict, Any, List, Tuple, Optional
from dotenv import load_dotenv

# Завантажуємо змінні середовища
load_dotenv()

# Отримуємо токен з .env файлу
MOODLE_API_TOKEN = os.getenv("API_MOODLE_TOKEN")
if not MOODLE_API_TOKEN:
    print("Помилка: API_MOODLE_TOKEN не знайдено в .env файлі")
    sys.exit(1)

# Кольори для виводу в консоль
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

class MoodleTokenPermissionTester:
    """Клас для тестування дозволів API токена Moodle через MCP сервер"""

    def __init__(self, mcp_url: str, moodle_api_token: str, moodle_base_url: str = "http://78.137.2.119:2929"):
        self.mcp_url = mcp_url
        self.token = moodle_api_token
        self.moodle_base_url = moodle_base_url
        self.client = None
        self.is_authenticated = False
        self.is_teacher = False
        self.user_info = None
        
        # Результати тестів
        self.permission_results = {}
        self.api_methods = {
            "core_webservice_get_site_info": "Базова інформація про сайт",
            "core_user_get_users_by_field": "Отримання інформації про користувачів",
            "core_course_get_courses": "Отримання списку курсів",
            "core_course_get_contents": "Отримання вмісту курсів",
            "core_enrol_get_enrolled_users": "Отримання учасників курсу",
            "mod_assign_get_assignments": "Отримання завдань курсу",
            "mod_assign_get_submissions": "Отримання зданих робіт",
            "mod_assign_get_submission_status": "Отримання статусу здачі робіт",
            "gradereport_user_get_grade_items": "Отримання оцінок",
            "core_calendar_get_calendar_events": "Отримання подій календаря",
            "mod_forum_add_discussion": "Додавання обговорень на форум",
            "core_course_edit_section": "Редагування розділів курсу",
            "core_role_assign_get_user_roles": "Отримання ролей користувача"
        }

    async def connect(self):
        """Підключення до MCP сервера"""
        print(f"{Colors.HEADER}Підключення до MCP сервера на {self.mcp_url}...{Colors.ENDC}")
        try:
            config = MCPClientConfig(base_url=self.mcp_url)
            self.client = MCPClient(config=config)
            await self.client.connect()
            print(f"{Colors.GREEN}З'єднання з MCP сервером встановлено успішно!{Colors.ENDC}")
            return True
        except Exception as e:
            print(f"{Colors.FAIL}Помилка підключення до MCP сервера: {str(e)}{Colors.ENDC}")
            return False

    async def authenticate_with_token(self):
        """Аутентифікація через токен API"""
        print(f"{Colors.HEADER}Аутентифікація з використанням API токена...{Colors.ENDC}")
        try:
            result = await self.client.invoke_tool("set_token", {
                "token": self.token
            })
            
            if "успішно" in result.lower():
                self.is_authenticated = True
                # Отримаємо інформацію про користувача
                user_info = await self.client.get_resource("user://info")
                self.user_info = user_info
                self.is_teacher = "Викладач" in user_info
                
                print(f"{Colors.GREEN}Аутентифікація успішна!{Colors.ENDC}")
                print(f"{Colors.BLUE}Роль користувача: {'Викладач' if self.is_teacher else 'Студент'}{Colors.ENDC}")
                return True
            else:
                print(f"{Colors.FAIL}Помилка аутентифікації: {result}{Colors.ENDC}")
                return False
        except Exception as e:
            print(f"{Colors.FAIL}Помилка при аутентифікації: {str(e)}{Colors.ENDC}")
            return False

    async def direct_api_test(self, method: str, params: Dict[str, Any] = None) -> Tuple[bool, Any]:
        """Прямий тест API методу Moodle"""
        if params is None:
            params = {}
            
        try:
            url = f"{self.moodle_base_url}/webservice/rest/server.php"
            request_params = {
                "wstoken": self.token,
                "wsfunction": method,
                "moodlewsrestformat": "json"
            }
            
            request_params.update(params)
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=request_params, timeout=10.0)
                data = response.json()
                
                # Перевірка на помилки у відповіді Moodle
                if isinstance(data, dict) and "exception" in data:
                    error_msg = data.get("message", "Помилка Moodle API")
                    if "access control" in error_msg.lower() or "permission" in error_msg.lower():
                        return False, "Немає дозволу"
                    return False, error_msg
                
                return True, data
        except Exception as e:
            return False, f"Помилка запиту: {str(e)}"

    async def test_api_permission(self, method: str, params: Dict[str, Any] = None) -> bool:
        """Тестування дозволів для конкретного API методу"""
        if params is None:
            params = {}
            
        description = self.api_methods.get(method, method)
        print(f"{Colors.HEADER}Тестування методу {method} ({description})...{Colors.ENDC}")
        
        success, result = await self.direct_api_test(method, params)
        if success:
            print(f"{Colors.GREEN}✓ Дозвіл надано{Colors.ENDC}")
            self.permission_results[method] = {
                "status": "granted",
                "description": description
            }
            return True
        else:
            error_msg = str(result)
            if "Немає дозволу" in error_msg or "required capability" in error_msg:
                print(f"{Colors.FAIL}✗ Дозвіл відсутній{Colors.ENDC}")
                self.permission_results[method] = {
                    "status": "denied",
                    "description": description,
                    "error": error_msg
                }
            else:
                print(f"{Colors.WARNING}? Невідома помилка: {error_msg}{Colors.ENDC}")
                self.permission_results[method] = {
                    "status": "error",
                    "description": description,
                    "error": error_msg
                }
            return False

    async def get_course_id_for_testing(self) -> Optional[int]:
        """Отримати ID курсу для тестування"""
        try:
            success, result = await self.direct_api_test("core_course_get_courses")
            if success and isinstance(result, list) and len(result) > 0:
                return result[0]["id"]
        except Exception:
            pass
            
        return None

    async def run_all_tests(self):
        """Запуск всіх тестів на перевірку дозволів"""
        print(f"{Colors.BOLD}Початок тестування дозволів для API токена Moodle...{Colors.ENDC}")
        
        # Базові тести, які не потребують додаткових параметрів
        await self.test_api_permission("core_webservice_get_site_info")
        await self.test_api_permission("core_course_get_courses")
        
        # Отримаємо ID курсу для подальших тестів
        course_id = await self.get_course_id_for_testing()
        if course_id:
            print(f"{Colors.BLUE}Знайдено курс для тестування з ID: {course_id}{Colors.ENDC}")
            
            # Тести, які потребують ID курсу
            await self.test_api_permission("core_course_get_contents", {"courseid": course_id})
            await self.test_api_permission("core_enrol_get_enrolled_users", {"courseid": course_id})
            await self.test_api_permission("mod_assign_get_assignments", {"courseids[0]": course_id})
            
            # Тести для отримання завдань і потім тестування роботи з завданнями
            success, assignments_data = await self.direct_api_test("mod_assign_get_assignments", {"courseids[0]": course_id})
            assignment_id = None
            if success and "courses" in assignments_data:
                for course in assignments_data["courses"]:
                    if course["id"] == course_id and "assignments" in course and len(course["assignments"]) > 0:
                        assignment_id = course["assignments"][0]["id"]
                        break
            
            if assignment_id:
                print(f"{Colors.BLUE}Знайдено завдання для тестування з ID: {assignment_id}{Colors.ENDC}")
                await self.test_api_permission("mod_assign_get_submissions", {"assignmentids[0]": assignment_id})
                await self.test_api_permission("mod_assign_get_submission_status", {"assignid": assignment_id})
            
            # Тест для оцінок
            await self.test_api_permission("gradereport_user_get_grade_items", {"courseid": course_id})
            
            # Тест для редагування розділів (тільки для викладачів)
            if self.is_teacher:
                await self.test_api_permission("core_course_edit_section", {"courseid": course_id, "sectionid": 0, "name": "Test Section"})
                
                # Пошук ID форуму оголошень для тесту
                success, course_content = await self.direct_api_test("core_course_get_contents", {"courseid": course_id})
                forum_id = None
                if success:
                    for section in course_content:
                        for module in section.get("modules", []):
                            if module.get("modname") == "forum" and (
                                "announcement" in module.get("name", "").lower() or
                                "news" in module.get("name", "").lower() or
                                "оголошення" in module.get("name", "").lower()
                            ):
                                forum_id = module.get("instance")
                                break
                        if forum_id:
                            break
                
                if forum_id:
                    print(f"{Colors.BLUE}Знайдено форум оголошень з ID: {forum_id}{Colors.ENDC}")
                    await self.test_api_permission("mod_forum_add_discussion", {
                        "forumid": forum_id,
                        "subject": "Test Subject",
                        "message": "Test Message"
                    })
        
        # Тест календаря
        from datetime import datetime
        now = datetime.now()
        await self.test_api_permission("core_calendar_get_calendar_events", {
            "events": {
                "timestart": int(datetime(now.year, now.month, 1).timestamp()),
                "timeend": int(datetime(now.year, now.month + 1 if now.month < 12 else 1, 1).timestamp())
            }
        })
        
        # Тест на отримання ролей
        success, site_info = await self.direct_api_test("core_webservice_get_site_info")
        if success and "userid" in site_info:
            user_id = site_info["userid"]
            await self.test_api_permission("core_role_assign_get_user_roles", {"userid": user_id})
            await self.test_api_permission("core_user_get_users_by_field", {"field": "id", "values[0]": user_id})
                
        self.print_results_summary()
        return self.permission_results

    def print_results_summary(self):
        """Вивід підсумкової таблиці результатів"""
        print("\n" + "="*80)
        print(f"{Colors.BOLD}ПІДСУМОК ТЕСТУВАННЯ ДОЗВОЛІВ API ТОКЕНА{Colors.ENDC}")
        print("="*80)
        
        granted = [method for method, result in self.permission_results.items() if result["status"] == "granted"]
        denied = [method for method, result in self.permission_results.items() if result["status"] == "denied"]
        errors = [method for method, result in self.permission_results.items() if result["status"] == "error"]
        
        print(f"\n{Colors.GREEN}Надані дозволи ({len(granted)}):{Colors.ENDC}")
        for method in granted:
            print(f"  ✓ {method} - {self.permission_results[method]['description']}")
        
        print(f"\n{Colors.FAIL}Відсутні дозволи ({len(denied)}):{Colors.ENDC}")
        for method in denied:
            print(f"  ✗ {method} - {self.permission_results[method]['description']}")
            
        if errors:
            print(f"\n{Colors.WARNING}Помилки при тестуванні ({len(errors)}):{Colors.ENDC}")
            for method in errors:
                print(f"  ? {method} - {self.permission_results[method]['description']}")
                print(f"    Помилка: {self.permission_results[method]['error']}")
        
        print("\n" + "="*80)
        print(f"Загальний результат: {len(granted)} надано, {len(denied)} відмовлено, {len(errors)} помилок")
        print("="*80 + "\n")
        
        if len(granted) == 0:
            print(f"{Colors.FAIL}УВАГА! Токен не має жодних дозволів для API Moodle.{Colors.ENDC}")
            print(f"{Colors.FAIL}Зверніться до адміністратора Moodle для надання необхідних дозволів.{Colors.ENDC}")
        elif len(denied) > 0:
            print(f"{Colors.WARNING}Деякі функції можуть бути недоступні через відсутність дозволів.{Colors.ENDC}")
            print(f"{Colors.WARNING}Для повної функціональності MCP сервера потрібні всі дозволи.{Colors.ENDC}")
            
    def save_results_to_file(self, filename: str = "moodle_token_permissions.json"):
        """Збереження результатів у файл JSON"""
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump({
                    "token": self.token[:5] + "*****",  # Маскуємо токен для безпеки
                    "is_teacher": self.is_teacher,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "results": self.permission_results
                }, f, ensure_ascii=False, indent=2)
            print(f"{Colors.GREEN}Результати збережено у файл: {filename}{Colors.ENDC}")
            return True
        except Exception as e:
            print(f"{Colors.FAIL}Помилка збереження результатів: {str(e)}{Colors.ENDC}")
            return False

async def main():
    parser = argparse.ArgumentParser(description="Тестування дозволів API токена Moodle через MCP сервер")
    parser.add_argument("--token", required=True, help="API токен Moodle для тестування")
    parser.add_argument("--mcp-url", default="http://localhost:6277", help="URL MCP сервера (за замовчуванням: http://localhost:6277)")
    parser.add_argument("--moodle-url", default="http://78.137.2.119:2929", help="Базовий URL Moodle (за замовчуванням: http://78.137.2.119:2929)")
    parser.add_argument("--output", default="moodle_token_permissions.json", help="Файл для збереження результатів (за замовчуванням: moodle_token_permissions.json)")
    
    args = parser.parse_args()
    
    tester = MoodleTokenPermissionTester(
        mcp_url=args.mcp_url,
        moodle_api_token=args.token,
        moodle_base_url=args.moodle_url
    )
    
    if await tester.connect():
        if await tester.authenticate_with_token():
            await tester.run_all_tests()
            tester.save_results_to_file(args.output)
        else:
            print(f"{Colors.FAIL}Не вдалося автентифікуватися з наданим токеном.{Colors.ENDC}")
    else:
        print(f"{Colors.FAIL}Не вдалося підключитися до MCP сервера.{Colors.ENDC}")

if __name__ == "__main__":
    asyncio.run(main())