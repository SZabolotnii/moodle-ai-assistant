"""
MCP сервер для інтеграції Moodle та Claude.
Забезпечує доступ до функціональності Moodle через протокол MCP.
"""
import os
import httpx
import json
import asyncio
import argparse
from typing import Dict, Any, Tuple, List, Optional
from mcp.server.fastmcp import FastMCP, Context, Image

# Імпорт нашого модуля LLM провайдера
try:
    from common.llm_provider import LLMProviderFactory
except ImportError:
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    from common.llm_provider import LLMProviderFactory


class MoodleMCPServer:
    """MCP сервер для Moodle з підтримкою режимів викладача і студента."""
    
    def __init__(self, base_url: str = "http://78.137.2.119:2929", token: Optional[str] = None):
        """
        Ініціалізація MCP сервера для Moodle.
        
        Args:
            base_url: Базова URL Moodle API
            token: Токен API Moodle (опціонально, також може бути взятий з .env)
        """
        self.base_url = base_url
        self.token = token or os.getenv("API_MOODLE_TOKEN")
        self.username = None
        self.password = None
        self.user_id = None
        self.user_info = None
        self.is_teacher = False  # Прапорець ролі викладача
        self.mode = "analytical"  # Режим роботи: "analytical" або "administrative"
        self.llm_provider = None  # LLM провайдер
        
        # Ініціалізація FastMCP сервера
        self.mcp = FastMCP("moodle-assistant")
        
        # Реєстрація ресурсів і інструментів
        self._register_tools()
        self._register_resources()
        self._register_prompts()
    
    def _register_tools(self):
        """Реєстрація MCP інструментів."""
        
        @self.mcp.tool()
        async def login(username: str, password: str) -> str:
            """Автентифікація в Moodle з використанням логіна та пароля.
            
            Args:
                username: Логін користувача Moodle
                password: Пароль користувача Moodle
            
            Returns:
                Повідомлення про результат автентифікації
            """
            self.username = username
            self.password = password
            
            success, message = await self._authenticate(username, password)
            if success:
                # Отримання інформації про користувача після успішної аутентифікації
                await self._get_user_role()
                return f"Аутентифікація успішна. Ви увійшли як {'викладач' if self.is_teacher else 'студент'}."
            return message
        
        @self.mcp.tool()
        async def set_token(token: str) -> str:
            """Встановлення API токена Moodle.
            
            Args:
                token: API токен Moodle
            
            Returns:
                Повідомлення про результат встановлення токена
            """
            self.token = token
            success, message = await self.is_token_valid()
            if success:
                await self._get_user_info()
                await self._get_user_role()
                return f"Токен встановлено успішно. Ви увійшли як {'викладач' if self.is_teacher else 'студент'}."
            return f"Помилка: Невалідний токен. {message}"
        
        @self.mcp.tool()
        async def set_mode(mode: str) -> str:
            """Встановлення режиму роботи (для викладача).
            
            Args:
                mode: Режим роботи ("analytical" або "administrative")
            
            Returns:
                Повідомлення про результат встановлення режиму
            """
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
            if not self.is_teacher:
                return "Цей інструмент доступний тільки для викладачів"
            
            if mode.lower() not in ["analytical", "administrative"]:
                return f"Помилка: Непідтримуваний режим '{mode}'. Доступні режими: 'analytical', 'administrative'"
            
            self.mode = mode.lower()
            return f"Режим роботи змінено на '{self.mode}'."
        
        @self.mcp.tool()
        async def get_user_courses() -> str:
            """Отримання списку курсів користувача.
            
            Returns:
                Список курсів користувача
            """
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
            if not self.user_id:
                success, message = await self._get_user_info()
                if not success:
                    return message
            
            success, data = await self._call_moodle_api("core_enrol_get_users_courses", {"userid": self.user_id})
            
            if success:
                if not data:
                    return "Курсів не знайдено"
                
                courses = []
                for course in data:
                    courses.append(f"ID: {course['id']}, Назва: {course['fullname']}")
                
                return "\n".join(courses)
            else:
                return f"Помилка: {data}"
        
        @self.mcp.tool()
        async def get_course_content(course_id: int) -> str:
            """Отримання вмісту курсу за його ID.
            
            Args:
                course_id: ID курсу в системі Moodle
            
            Returns:
                Вміст курсу (розділи та активності)
            """
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
            success, data = await self._call_moodle_api("core_course_get_contents", {
                "courseid": course_id
            })
            
            if success:
                if not data:
                    return f"Вміст курсу з ID {course_id} не знайдено або курс порожній"
                
                sections = []
                for section in data:
                    section_info = f"Розділ: {section['name']}"
                    if "modules" in section and section["modules"]:
                        modules = []
                        for module in section["modules"]:
                            module_info = f"  - {module['name']} ({module['modname']})"
                            if module.get('modname') == 'assign':
                                # Додаткова інформація для завдань
                                module_info += f", ID: {module.get('instance')}"
                            modules.append(module_info)
                        section_info += "\n" + "\n".join(modules)
                    else:
                        section_info += "\n  Розділ порожній"
                    
                    sections.append(section_info)
                
                return "\n\n".join(sections)
            else:
                return f"Помилка: {data}"
        
        # --- Інструменти для студента ---
        
        @self.mcp.tool()
        async def get_assignment_status(assignment_id: int) -> str:
            """Отримання статусу завдання для поточного користувача.
            
            Args:
                assignment_id: ID завдання
            
            Returns:
                Статус завдання для користувача
            """
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
            success, data = await self._call_moodle_api("mod_assign_get_submission_status", {
                "assignid": assignment_id
            })
            
            if success:
                result = []
                result.append(f"Статус завдання (ID: {assignment_id}):")
                
                # Основна інформація
                if "laststatus" in data:
                    status = data["laststatus"]
                    status_text = "Не здано"
                    if status == "submitted":
                        status_text = "Здано"
                    elif status == "draft":
                        status_text = "Чернетка"
                    else:
                        status_text = status
                    
                    result.append(f"Статус: {status_text}")
                
                # Інформація про оцінку
                if "feedback" in data and data["feedback"]:
                    feedback = data["feedback"]
                    grade = feedback.get("grade", {}).get("grade")
                    if grade:
                        result.append(f"Оцінка: {grade}")
                    
                    feedback_comments = feedback.get("feedbackcomments", {}).get("text")
                    if feedback_comments:
                        result.append(f"Коментар викладача: {feedback_comments}")
                
                # Час останньої модифікації
                if "submission" in data and data["submission"]:
                    submission = data["submission"]
                    time_modified = submission.get("timemodified")
                    if time_modified:
                        from datetime import datetime
                        time_str = datetime.fromtimestamp(time_modified).strftime('%d.%m.%Y %H:%M')
                        result.append(f"Останнє оновлення: {time_str}")
                
                return "\n".join(result)
            else:
                return f"Помилка: {data}"
        
        @self.mcp.tool()
        async def get_calendar_events(month: int, year: int) -> str:
            """Отримання подій календаря за вказаний місяць і рік.
            
            Args:
                month: Місяць (1-12)
                year: Рік
            
            Returns:
                Події календаря за вказаний період
            """
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
            # Отримання першого і останнього дня місяця
            import calendar
            from datetime import datetime
            
            first_day = int(datetime(year, month, 1).timestamp())
            last_day = int(datetime(year, month, calendar.monthrange(year, month)[1], 23, 59, 59).timestamp())
            
            success, data = await self._call_moodle_api("core_calendar_get_calendar_events", {
                "events": {
                    "timestart": first_day,
                    "timeend": last_day
                }
            })
            
            if success:
                if "events" in data and data["events"]:
                    events = []
                    for event in data["events"]:
                        event_time = datetime.fromtimestamp(event['timestart']).strftime('%d.%m.%Y %H:%M')
                        course_name = event.get('course', {}).get('fullname', 'Невідомо')
                        events.append(f"Дата: {event_time}, Назва: {event['name']}, Курс: {course_name}")
                    
                    return "\n".join(events)
                else:
                    return f"Подій календаря на {month}.{year} не знайдено"
            else:
                return f"Помилка: {data}"
        
        # --- Інструменти для викладача ---
        
        @self.mcp.tool()
        async def get_course_students(course_id: int) -> str:
            """Отримання списку студентів курсу (тільки для викладача).
            
            Args:
                course_id: ID курсу в системі Moodle
            
            Returns:
                Список студентів курсу
            """
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
            if not self.is_teacher:
                return "Цей інструмент доступний тільки для викладачів"
            
            # Отримання списку enrolled користувачів з роллю студента
            success, data = await self._call_moodle_api("core_enrol_get_enrolled_users", {
                "courseid": course_id
            })
            
            if success:
                if not data:
                    return f"Студентів не знайдено для курсу з ID {course_id}"
                
                # Фільтрація тільки студентів
                students = [user for user in data if any(role['shortname'] == 'student' for role in user.get('roles', []))]
                
                if not students:
                    return f"Студентів не знайдено для курсу з ID {course_id}"
                
                result = []
                for student in students:
                    result.append(f"ID: {student['id']}, Ім'я: {student['fullname']}, Email: {student.get('email', 'Недоступно')}")
                
                return "\n".join(result)
            else:
                return f"Помилка: {data}"
        
        @self.mcp.tool()
        async def get_course_grades(course_id: int) -> str:
            """Отримання оцінок студентів курсу (тільки для викладача).
            
            Args:
                course_id: ID курсу в системі Moodle
            
            Returns:
                Оцінки студентів курсу
            """
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
            if not self.is_teacher:
                return "Цей інструмент доступний тільки для викладачів"
            
            # Отримання оцінок всіх студентів курсу
            success, data = await self._call_moodle_api("gradereport_user_get_grade_items", {
                "courseid": course_id
            })
            
            if success:
                if "usergrades" not in data or not data["usergrades"]:
                    return f"Оцінки не знайдені для курсу з ID {course_id}"
                
                result = []
                for usergrade in data["usergrades"]:
                    student_info = f"Студент: {usergrade['userfullname']} (ID: {usergrade['userid']})"
                    grades = []
                    
                    for grade_item in usergrade.get("gradeitems", []):
                        if "itemname" in grade_item and grade_item["itemname"]:
                            grade_value = grade_item.get("gradeformatted", "Не оцінено")
                            grades.append(f"  - {grade_item['itemname']}: {grade_value}")
                    
                    if grades:
                        student_info += "\n" + "\n".join(grades)
                    else:
                        student_info += "\n  Оцінки відсутні"
                    
                    result.append(student_info)
                
                return "\n\n".join(result)
            else:
                return f"Помилка: {data}"
        
        @self.mcp.tool()
        async def get_assignment_submissions(assignment_id: int) -> str:
            """Отримання зданих завдань студентів (тільки для викладача).
            
            Args:
                assignment_id: ID завдання
            
            Returns:
                Здані роботи студентів для вказаного завдання
            """
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
            if not self.is_teacher:
                return "Цей інструмент доступний тільки для викладачів"
            
            # Отримання інформації про здані завдання
            success, data = await self._call_moodle_api("mod_assign_get_submissions", {
                "assignmentids[0]": assignment_id
            })
            
            if success:
                if "assignments" not in data or not data["assignments"]:
                    return f"Здані роботи не знайдені для завдання з ID {assignment_id}"
                
                result = []
                for assignment in data["assignments"]:
                    result.append(f"Завдання: {assignment.get('name', f'ID: {assignment_id}')}")
                    
                    if "submissions" not in assignment or not assignment["submissions"]:
                        result.append("  Немає зданих робіт")
                        continue
                    
                    for submission in assignment["submissions"]:
                        status = "Здано" if submission.get("status") == "submitted" else "Чернетка"
                        time = submission.get("timemodified", "Невідомо")
                        if time != "Невідомо":
                            from datetime import datetime
                            time = datetime.fromtimestamp(time).strftime('%d.%m.%Y %H:%M')
                        
                        # Отримання додаткової інформації про студента
                        user_id = submission.get("userid")
                        user_info = await self._get_user_by_id(user_id)
                        user_name = user_info.get("fullname", f"ID: {user_id}")
                        
                        result.append(f"  - Студент: {user_name}")
                        result.append(f"    Статус: {status}")
                        result.append(f"    Останнє оновлення: {time}")
                        
                        # Якщо є коментарі
                        if "plugins" in submission:
                            for plugin in submission["plugins"]:
                                if plugin.get("type") == "comments" and "editorfields" in plugin:
                                    for field in plugin["editorfields"]:
                                        if field.get("text"):
                                            result.append(f"    Коментар: {field['text']}")
                
                return "\n".join(result)
            else:
                return f"Помилка: {data}"
        
        @self.mcp.tool()
        async def create_announcement(course_id: int, subject: str, message: str) -> str:
            """Створення оголошення для курсу (тільки для викладача).
            
            Args:
                course_id: ID курсу
                subject: Тема оголошення
                message: Текст оголошення
            
            Returns:
                Результат створення оголошення
            """
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
            if not self.is_teacher:
                return "Цей інструмент доступний тільки для викладачів"
            
            if self.mode != "administrative":
                return "Цей інструмент доступний тільки в адміністративному режимі"
            
            # Спочатку отримання ID форуму оголошень для курсу
            success, course_data = await self._call_moodle_api("core_course_get_contents", {
                "courseid": course_id
            })
            
            if not success:
                return f"Помилка отримання вмісту курсу: {course_data}"
            
            # Пошук форуму оголошень
            forum_id = None
            for section in course_data:
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
            
            if not forum_id:
                return "Форум оголошень не знайдено в цьому курсі"
            
            # Створення оголошення
            success, data = await self._call_moodle_api("mod_forum_add_discussion", {
                "forumid": forum_id,
                "subject": subject,
                "message": message,
                "options[0][name]": "discussionsubscribe",
                "options[0][value]": 1  # Підписати всіх на оголошення
            })
            
            if success:
                return f"Оголошення успішно створено! ID: {data.get('discussionid')}"
            else:
                return f"Помилка створення оголошення: {data}"
        
        @self.mcp.tool()
        async def create_course_section(course_id: int, name: str, description: str = "") -> str:
            """Створення нового розділу в курсі (тільки для викладача).
            
            Args:
                course_id: ID курсу
                name: Назва розділу
                description: Опис розділу (опціонально)
            
            Returns:
                Результат створення розділу
            """
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
            if not self.is_teacher:
                return "Цей інструмент доступний тільки для викладачів"
            
            if self.mode != "administrative":
                return "Цей інструмент доступний тільки в адміністративному режимі"
            
            # Створення нового розділу
            success, data = await self._call_moodle_api("core_course_edit_section", {
                "courseid": course_id,
                "sectionid": 0,  # 0 означає створення нового розділу
                "name": name,
                "summary": description,
                "summaryformat": 1  # 1 означає HTML-формат
            })
            
            if success:
                section_id = data.get("sectionid")
                if section_id:
                    return f"Розділ '{name}' успішно створено! ID: {section_id}"
                else:
                    return "Розділ створено, але не вдалося отримати його ID."
            else:
                if isinstance(data, dict) and data.get("message"):
                    return f"Помилка створення розділу: {data['message']}"
                return f"Помилка створення розділу: {data}"
        
        # --- Інструменти для роботи з LLM ---
        
        @self.mcp.tool()
        async def ai_analyze_course(course_id: int, ctx: Context) -> str:
            """Аналіз структури та вмісту курсу за допомогою AI.
            
            Args:
                course_id: ID курсу
            
            Returns:
                AI-аналіз курсу
            """
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
            await ctx.report_progress(1, 4, "Ініціалізація LLM провайдера...")
            if not self.llm_provider:
                try:
                    self.llm_provider = await LLMProviderFactory.create_provider("claude")
                    if not self.llm_provider:
                        return "Не вдалося ініціалізувати LLM провайдера. Перевірте налаштування API ключа."
                except Exception as e:
                    return f"Помилка ініціалізації LLM провайдера: {e}"
            
            await ctx.report_progress(2, 4, "Отримання даних курсу...")
            
            # Отримання інформації про курс
            success_course, course_data = await self._call_moodle_api("core_course_get_courses", {
                "options[ids][0]": course_id
            })
            
            if not success_course or not course_data:
                return f"Не вдалося отримати інформацію про курс з ID {course_id}"
            
            course_info = course_data[0]
            course_name = course_info.get("fullname", f"ID: {course_id}")
            
            # Отримання вмісту курсу
            success_contents, contents_data = await self._call_moodle_api("core_course_get_contents", {
                "courseid": course_id
            })
            
            if not success_contents:
                return f"Не вдалося отримати вміст курсу з ID {course_id}"
            
            # Підготовка даних для аналізу
            course_structure = []
            for section in contents_data:
                section_info = f"Розділ: {section.get('name', 'Без назви')}"
                module_list = []
                
                for module in section.get("modules", []):
                    module_info = f"{module.get('name', 'Без назви')} (Тип: {module.get('modname', 'N/A')})"
                    module_list.append(module_info)
                
                if module_list:
                    section_info += "\nЕлементи:\n- " + "\n- ".join(module_list)
                else:
                    section_info += "\nРозділ порожній"
                
                course_structure.append(section_info)
            
            # Отримання кількості студентів
            await ctx.report_progress(3, 4, "Отримання даних про студентів...")
            success_students, students_data = await self._call_moodle_api("core_enrol_get_enrolled_users", {
                "courseid": course_id
            })
            
            student_count = 0
            if success_students:
                students = [user for user in students_data if any(role.get('shortname') == 'student' for role in user.get('roles', []))]
                student_count = len(students)
            
            # Підготовка запиту для LLM
            # Використовуємо окрему змінну для форматування структури курсу
            structure_text = "\n\n".join(course_structure)
            
            prompt = f"""
            Проаналізуй структуру та вміст курсу "{course_name}" з ID {course_id}.
            
            Загальна інформація:
            - Повна назва: {course_info.get('fullname', 'N/A')}
            - Коротка назва: {course_info.get('shortname', 'N/A')}
            - Опис: {course_info.get('summary', 'Опис відсутній')}
            - Кількість розділів: {len(contents_data)}
            - Кількість студентів: {student_count}
            
            Структура курсу:
            {structure_text}
            
            Завдання:
            1. Проаналізуй структуру курсу та вміст.
            2. Оціни відповідність структури до стандартних педагогічних практик.
            3. Виявіть сильні сторони та потенційні області для поліпшення.
            4. Надайте рекомендації щодо оптимізації структури курсу та покращення навчального досвіду.
            5. Запропонуйте додаткові елементи або активності, які можуть збагатити курс.
            """
            
            await ctx.report_progress(4, 4, "Аналіз даних курсу за допомогою AI...")
            
            try:
                # Генерація відповіді від LLM
                context = {
                    "user_role": "teacher",
                    "mode": self.mode,
                    "system_prompt": "Ви досвідчений аналітик навчальних курсів у системі Moodle. Ваша мета - надати корисний та об'єктивний аналіз структури та вмісту курсу, виявити його сильні сторони та можливості для покращення. Слідуйте запиту й надайте структурований аналіз зі специфічними рекомендаціями."
                }
                
                response = await self.llm_provider.generate_response(prompt, context)
                return response
            except Exception as e:
                return f"Помилка при аналізі курсу за допомогою AI: {e}"
        
        @self.mcp.tool()
        async def ai_generate_announcement(course_id: int, topic: str, ctx: Context) -> str:
            """Генерація оголошення для курсу за допомогою AI.
            
            Args:
                course_id: ID курсу
                topic: Тема оголошення
            
            Returns:
                Згенероване оголошення
            """
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
            if not self.is_teacher:
                return "Цей інструмент доступний тільки для викладачів"
            
            await ctx.report_progress(1, 3, "Ініціалізація LLM провайдера...")
            if not self.llm_provider:
                try:
                    self.llm_provider = await LLMProviderFactory.create_provider("claude")
                    if not self.llm_provider:
                        return "Не вдалося ініціалізувати LLM провайдера. Перевірте налаштування API ключа."
                except Exception as e:
                    return f"Помилка ініціалізації LLM провайдера: {e}"
            
            await ctx.report_progress(2, 3, "Отримання даних курсу...")
            
            # Отримання інформації про курс
            success_course, course_data = await self._call_moodle_api("core_course_get_courses", {
                "options[ids][0]": course_id
            })
            
            if not success_course or not course_data:
                return f"Не вдалося отримати інформацію про курс з ID {course_id}"
            
            course_info = course_data[0]
            course_name = course_info.get("fullname", f"ID: {course_id}")
            
            # Підготовка запиту для LLM
            prompt = f"""
            Згенеруй оголошення для курсу "{course_name}" на тему "{topic}".
            
            Оголошення має містити:
            1. Інформативний заголовок
            2. Привітання
            3. Основний текст оголошення
            4. Заключну частину з підписом викладача
            
            Тема оголошення: {topic}
            
            Формат відповіді:
            ЗАГОЛОВОК: [заголовок оголошення]
            
            ТЕКСТ:
            [повний текст оголошення]
            """
            
            await ctx.report_progress(3, 3, "Генерація оголошення за допомогою AI...")
            
            try:
                # Генерація відповіді від LLM
                context = {
                    "user_role": "teacher",
                    "mode": self.mode,
                    "system_prompt": "Ви досвідчений викладач, який готує оголошення для своїх студентів у системі Moodle. Ваша мета - написати інформативне, чітке та дружнє оголошення, яке ефективно комунікує необхідну інформацію. Ваші оголошення мають бути професійними, але не надто формальними. Використовуйте українську мову."
                }
                
                response = await self.llm_provider.generate_response(prompt, context)
                
                # Парсинг відповіді для отримання заголовка та тексту
                lines = response.split("\n")
                title = ""
                content = []
                
                # Знаходження заголовка
                for i, line in enumerate(lines):
                    if line.startswith("ЗАГОЛОВОК:"):
                        title = line.replace("ЗАГОЛОВОК:", "").strip()
                        break
                
                # Знаходження тексту
                text_start = False
                for line in lines:
                    if line.startswith("ТЕКСТ:"):
                        text_start = True
                        continue
                    
                    if text_start:
                        content.append(line)
                
                if title and content:
                    return f"ЗАГОЛОВОК: {title}\n\nТЕКСТ:\n{''.join(content)}"
                else:
                    return response
            except Exception as e:
                return f"Помилка при генерації оголошення за допомогою AI: {e}"
        
        @self.mcp.tool()
        async def initialize_llm_provider(provider_name: str = "claude") -> str:
            """Ініціалізація LLM провайдера.
            
            Args:
                provider_name: Назва LLM провайдера (за замовчуванням "claude")
            
            Returns:
                Повідомлення про результат ініціалізації
            """
            try:
                self.llm_provider = await LLMProviderFactory.create_provider(provider_name)
                
                if self.llm_provider:
                    return f"Провайдер '{provider_name}' успішно ініціалізовано."
                else:
                    return f"Помилка: Не вдалося ініціалізувати провайдера '{provider_name}'. Перевірте налаштування API ключа."
            except Exception as e:
                return f"Помилка ініціалізації провайдера: {e}"
    
    def _register_resources(self):
        """Реєстрація MCP ресурсів."""
        
        @self.mcp.resource("user://info")
        async def get_user_info() -> str:
            """Отримання інформації про поточного користувача."""
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію за допомогою інструменту login або set_token"
            
            if not self.user_info:
                success, _ = await self._get_user_info()
                if not success:
                    return "Помилка отримання інформації про користувача"
            
            info = [
                f"ID: {self.user_info['id']}",
                f"Повне ім'я: {self.user_info['fullname']}",
                f"Ім'я: {self.user_info['firstname']}",
                f"Прізвище: {self.user_info['lastname']}",
                f"Email: {self.user_info['email']}",
                f"Роль: {'Викладач' if self.is_teacher else 'Студент'}",
                f"Режим роботи: {self.mode} (для викладача)"
            ]
            return "\n".join(info)
        
        @self.mcp.resource("calendar://{month}/{year}")
        async def get_calendar_events(month: str, year: str) -> str:
            """Отримання подій календаря за вказаний місяць і рік."""
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
            try:
                month = int(month)
                year = int(year)
            except ValueError:
                return "Місяць і рік повинні бути числами"
            
            # Отримання першого і останнього дня місяця
            import calendar
            from datetime import datetime
            
            first_day = int(datetime(year, month, 1).timestamp())
            last_day = int(datetime(year, month, calendar.monthrange(year, month)[1], 23, 59, 59).timestamp())
            
            success, data = await self._call_moodle_api("core_calendar_get_calendar_events", {
                "events": {
                    "timestart": first_day,
                    "timeend": last_day
                }
            })
            
            if success:
                if "events" in data and data["events"]:
                    events = []
                    for event in data["events"]:
                        event_time = datetime.fromtimestamp(event['timestart']).strftime('%d.%m.%Y %H:%M')
                        course_name = event.get('course', {}).get('fullname', 'Невідомо')
                        events.append(f"Дата: {event_time}, Назва: {event['name']}, Курс: {course_name}")
                    
                    return "\n".join(events)
                else:
                    return f"Подій календаря на {month}.{year} не знайдено"
            else:
                return f"Помилка: {data}"
        
        @self.mcp.resource("course://{course_id}/assignments")
        async def get_course_assignments(course_id: str) -> str:
            """Отримання списку завдань курсу."""
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
            try:
                course_id = int(course_id)
            except ValueError:
                return "ID курсу має бути числом"
            
            success, data = await self._call_moodle_api("mod_assign_get_assignments", {
                "courseids[0]": course_id
            })
            
            if success and "courses" in data:
                assignments = []
                
                for course in data["courses"]:
                    if course["id"] == course_id:
                        if not course["assignments"]:
                            return f"Завдання не знайдені для курсу з ID {course_id}"
                        
                        for assignment in course["assignments"]:
                            due_date = "Не встановлено"
                            if assignment.get("duedate") and assignment["duedate"] > 0:
                                from datetime import datetime
                                due_date = datetime.fromtimestamp(assignment["duedate"]).strftime('%d.%m.%Y %H:%M')
                            
                            assignments.append(f"ID: {assignment['id']}, Назва: {assignment['name']}, Термін здачі: {due_date}")
                
                if assignments:
                    return "\n".join(assignments)
            
            # Якщо mod_assign_get_assignments не допоміг, спробуємо через core_course_get_contents
            success, course_data = await self._call_moodle_api("core_course_get_contents", {
                "courseid": course_id
            })
            
            if not success:
                return f"Помилка отримання вмісту курсу: {course_data}"
            
            assignments = []
            for section in course_data:
                for module in section.get("modules", []):
                    if module.get("modname") == "assign":
                        due_date = "Не встановлено"
                        if module.get("dates") and len(module["dates"]) > 0:
                            for date in module["dates"]:
                                if date.get("label") == "Due:":
                                    from datetime import datetime
                                    due_timestamp = date.get("timestamp")
                                    if due_timestamp:
                                        due_date = datetime.fromtimestamp(due_timestamp).strftime('%d.%m.%Y %H:%M')
                                    break
                        
                        assignments.append(f"ID: {module.get('instance')}, Назва: {module['name']}, Термін здачі: {due_date}")
            
            if assignments:
                return "\n".join(assignments)
            else:
                return f"Завдання не знайдені для курсу з ID {course_id}"
        
        @self.mcp.resource("course://{course_id}/content")
        async def get_course_content_resource(course_id: str) -> str:
            """Отримання вмісту курсу."""
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
            try:
                course_id = int(course_id)
            except ValueError:
                return "ID курсу має бути числом"
            
            success, data = await self._call_moodle_api("core_course_get_contents", {
                "courseid": course_id
            })
            
            if success:
                if not data:
                    return f"Вміст курсу з ID {course_id} не знайдено або курс порожній"
                
                sections = []
                for section in data:
                    section_info = f"Розділ: {section['name']}"
                    if "modules" in section and section["modules"]:
                        modules = []
                        for module in section["modules"]:
                            module_info = f"  - {module['name']} ({module['modname']})"
                            if module.get('modname') == 'assign':
                                module_info += f", ID: {module.get('instance')}"
                            modules.append(module_info)
                        section_info += "\n" + "\n".join(modules)
                    else:
                        section_info += "\n  Розділ порожній"
                    
                    sections.append(section_info)
                
                return "\n\n".join(sections)
            else:
                return f"Помилка: {data}"
    
    def _register_prompts(self):
        """Реєстрація MCP промптів."""
        
        @self.mcp.prompt()
        def analyze_course_structure(course_id: int) -> str:
            """Створення промпту для аналізу структури курсу."""
            return f"""
            Проаналізуйте структуру курсу з ID {course_id}. Використовуйте інструмент get_course_content для отримання вмісту курсу, а потім оцініть:
            
            1. Логічність структури розділів
            2. Різноманітність типів навчальних активностей
            3. Наявність оцінюваних завдань
            4. Рекомендації щодо покращення структури курсу
            
            Будь ласка, використайте інструмент ai_analyze_course для глибокого аналізу з використанням AI.
            """
        
        @self.mcp.prompt()
        def student_performance_analysis(course_id: int) -> str:
            """Створення промпту для аналізу успішності студентів."""
            return f"""
            Проаналізуйте успішність студентів у курсі з ID {course_id}. Для цього:
            
            1. Отримайте список студентів курсу за допомогою інструменту get_course_students
            2. Отримайте оцінки студентів за допомогою інструменту get_course_grades
            3. Проаналізуйте, які завдання викликають найбільші труднощі
            4. Визначте найуспішніших та найменш успішних студентів
            5. Надайте рекомендації щодо підвищення успішності
            
            Використайте інструмент initialize_llm_provider, якщо потрібно використати AI для аналізу.
            """
        
        @self.mcp.prompt()
        def create_course_announcement(course_id: int, topic: str) -> str:
            """Створення промпту для генерації оголошення курсу за допомогою AI."""
            return f"""
            Створіть оголошення для курсу з ID {course_id} на тему "{topic}". Для цього:
            
            1. Використайте інструмент ai_generate_announcement для генерації тексту оголошення на основі вказаної теми
            2. Перегляньте згенерований текст і за потреби відредагуйте його
            3. Використайте інструмент create_announcement для публікації оголошення в курсі
            
            Переконайтеся, що ви працюєте в адміністративному режимі. Якщо потрібно змінити режим, використайте інструмент set_mode("administrative").
            """
    
    async def _authenticate(self, username: str, password: str) -> Tuple[bool, str]:
        """Аутентифікація і отримання токена."""
        try:
            # Використання Moodle Web Service для аутентифікації
            url = f"{self.base_url}/login/token.php"
            params = {
                "username": username,
                "password": password,
                "service": "moodle_mobile_app"  # Стандартний сервіс Moodle
            }
            async with httpx.AsyncClient() as client:
                response = await client.post(url, params=params)
                data = response.json()
                
                if "token" in data:
                    self.token = data["token"]
                    return True, "Аутентифікація успішна"
                else:
                    return False, f"Помилка аутентифікації: {data.get('error', 'Невідома помилка')}"
        except Exception as e:
            return False, f"Помилка при підключенні до Moodle: {str(e)}"
    
    async def _call_moodle_api(self, function: str, params: Optional[Dict[str, Any]] = None) -> Tuple[bool, Any]:
        """Виконання API запитів до Moodle."""
        if self.token is None:
            return False, "Необхідно спочатку виконати аутентифікацію"
        
        try:
            url = f"{self.base_url}/webservice/rest/server.php"
            request_params = {
                "wstoken": self.token,
                "wsfunction": function,
                "moodlewsrestformat": "json"
            }
            
            if params:
                request_params.update(params)
            
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=request_params)
                data = response.json()
                
                # Перевірка на помилки у відповіді Moodle
                if isinstance(data, dict) and "exception" in data:
                    return False, f"{data.get('message', 'Помилка Moodle API')}"
                
                return True, data
        except Exception as e:
            return False, f"Помилка при виклику Moodle API: {str(e)}"
    
    async def _ensure_authenticated(self) -> bool:
        """Перевіряє та забезпечує аутентифікацію."""
        if self.token is None and self.username and self.password:
            success, _ = await self._authenticate(self.username, self.password)
            return success
        return self.token is not None
    
    async def is_token_valid(self) -> Tuple[bool, str]:
        """Перевіряє валідність токена."""
        if not self.token:
            return False, "Токен не надано"
        
        try:
            success, data = await self._call_moodle_api("core_webservice_get_site_info")
            
            if success:
                return True, "Токен валідний"
            else:
                return False, f"Помилка перевірки токена: {data}"
        except Exception as e:
            return False, f"Помилка перевірки токена: {str(e)}"
    
    async def _get_user_info(self) -> Tuple[bool, str]:
        """Отримання інформації про поточного користувача."""
        success, data = await self._call_moodle_api("core_webservice_get_site_info")
        
        if success:
            if "userid" in data:
                self.user_id = data["userid"]
                user_success, user_data = await self._call_moodle_api("core_user_get_users_by_field", {
                    "field": "id", 
                    "values[0]": self.user_id
                })
                
                if user_success and user_data and len(user_data) > 0:
                    self.user_info = user_data[0]
                    return True, "Інформація користувача отримана"
            
            return False, "Не вдалося отримати ID користувача"
        else:
            return False, f"Помилка отримання інформації про сайт: {data}"
    
    async def _get_user_role(self) -> bool:
        """Визначення ролі користувача (викладач/студент)."""
        if not self.user_id:
            success, _ = await self._get_user_info()
            if not success:
                return False
        
        # Отримання ролей користувача в системі
        success, data = await self._call_moodle_api("core_role_assign_get_user_roles", {
            "userid": self.user_id
        })
        
        if success:
            # Перевірка на роль викладача серед отриманих ролей
            self.is_teacher = any(role.get('shortname') in ['editingteacher', 'teacher', 'coursecreator', 'manager'] 
                               for role in data.get('roles', []))
            return True
        
        return False
    
    async def _get_user_by_id(self, user_id: int) -> Dict[str, Any]:
        """Отримання інформації про користувача за ID."""
        success, user_data = await self._call_moodle_api("core_user_get_users_by_field", {
            "field": "id", 
            "values[0]": user_id
        })
        
        if success and user_data and len(user_data) > 0:
            return user_data[0]
        return {}
    
    def run(self):
        """Запуск MCP сервера."""
        self.mcp.run()


def main():
    """Функція запуску MCP сервера."""
    parser = argparse.ArgumentParser(description="MCP сервер для Moodle")
    parser.add_argument("--base-url", default="http://78.137.2.119:2929", help="Базова URL-адреса Moodle")
    parser.add_argument("--token", default=None, help="API токен Moodle (опціонально, також може бути взятий з .env)")
    
    args = parser.parse_args()
    
    # Створення та запуск сервера
    server = MoodleMCPServer(base_url=args.base_url, token=args.token)
    server.run()


if __name__ == "__main__":
    main()