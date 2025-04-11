#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пряме тестування дозволів API токена Moodle
"""

import asyncio
import json
import os
import sys
import httpx
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

class MoodlePermissionTester:
    """Клас для прямого тестування дозволів API токена Moodle"""

    def __init__(self, token: str, base_url: str = "http://78.137.2.119:2929"):
        self.token = token
        self.base_url = base_url
        
    async def test_api_method(self, method: str, params: Dict[str, Any] = None) -> Tuple[bool, Any]:
        """Тестування API методу"""
        if params is None:
            params = {}
            
        try:
            url = f"{self.base_url}/webservice/rest/server.php"
            request_params = {
                "wstoken": self.token,
                "wsfunction": method,
                "moodlewsrestformat": "json"
            }
            request_params.update(params)
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=request_params, timeout=10.0)
                data = response.json()
                
                if isinstance(data, dict) and "exception" in data:
                    return False, data.get("message", "Помилка Moodle API")
                return True, data
                
        except Exception as e:
            return False, str(e)

    async def run_tests(self):
        """Запуск всіх тестів"""
        print(f"{Colors.HEADER}Початок тестування API токена Moodle...{Colors.ENDC}")
        
        # Тест базової інформації
        print(f"\n{Colors.BOLD}1. Тестування базової інформації{Colors.ENDC}")
        success, result = await self.test_api_method("core_webservice_get_site_info")
        if success:
            print(f"{Colors.GREEN}✓ Базовий доступ: OK{Colors.ENDC}")
            print(f"Сайт: {result.get('sitename')}")
            print(f"Користувач: {result.get('fullname')} (ID: {result.get('userid')})")
        else:
            print(f"{Colors.FAIL}✗ Помилка базового доступу: {result}{Colors.ENDC}")
            return
        
        # Тест доступу до курсів
        print(f"\n{Colors.BOLD}2. Тестування доступу до курсів{Colors.ENDC}")
        success, result = await self.test_api_method("core_course_get_courses")
        if success:
            print(f"{Colors.GREEN}✓ Доступ до курсів: OK{Colors.ENDC}")
            if isinstance(result, list):
                print(f"Знайдено курсів: {len(result)}")
                for course in result[:3]:  # Показуємо перші 3 курси
                    print(f"- {course.get('fullname')} (ID: {course.get('id')})")
        else:
            print(f"{Colors.FAIL}✗ Помилка доступу до курсів: {result}{Colors.ENDC}")

async def main():
    tester = MoodlePermissionTester(MOODLE_API_TOKEN)
    await tester.run_tests()

if __name__ == "__main__":
    asyncio.run(main()) 