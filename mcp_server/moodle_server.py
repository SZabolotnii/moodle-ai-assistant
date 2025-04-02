import os
import httpx
import json
import asyncio
from typing import Dict, Any, Tuple, List, Optional
from mcp.server.fastmcp import FastMCP, Context

class MoodleMCPServer:
    """MCP сервер для Moodle з підтримкою режимів викладача і студента."""
    
    def __init__(self, base_url: str = "http://78.137.2.119:2929"):
        self.base_url = base_url
        self.token = None
        self.username = None
        self.password = None
        self.user_id = None
        self.user_info = None
        self.is_teacher = False  # Прапорець ролі викладача
        
        # Ініціалізація FastMCP сервера
        self.mcp = FastMCP("moodle-assistant")
        self._register_tools()
        self._register_resources()
    
    def _register_tools(self):
        """Реєстрація MCP інструментів."""
        
        @self.mcp.tool()
        async def login(username: str, password: str) -> str:
            """Автентифікація в Moodle з використанням логіна та пароля.
            
            Args:
                username: Логін користувача Moodle
                password: Пароль користувача Moodle
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
        async def get_user_courses() -> str:
            """Отримання списку курсів користувача."""
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію за допомогою інструменту login"
            
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
        
        # --- Інструменти для викладача ---
        
        @self.mcp.tool()
        async def get_course_students(course_id: int) -> str:
            """Отримання списку студентів курсу (тільки для викладача).
            
            Args:
                course_id: ID курсу в системі Moodle
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
            """
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
                
            if not self.is_teacher:
                return "Цей інструмент доступний тільки для викладачів"
            
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
                    if module.get("modname") == "forum" and "announcement" in module.get("name", "").lower():
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
        
        # --- Спільні інструменти ---
        
        @self.mcp.tool()
        async def search_courses(query: str) -> str:
            """Пошук курсів за ключовим словом.
            
            Args:
                query: Ключове слово для пошуку
            """
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
            success, data = await self._call_moodle_api("core_course_search_courses", {
                "criterianame": "search", 
                "criteriavalue": query
            })
            
            if success:
                if "courses" in data and data["courses"]:
                    courses = []
                    for course in data["courses"]:
                        courses.append(f"ID: {course['id']}, Назва: {course['fullname']}")
                    
                    return "\n".join(courses)
                else:
                    return f"Курсів за запитом '{query}' не знайдено"
            else:
                return f"Помилка: {data}"
        
        @self.mcp.tool()
        async def get_course_content(course_id: int) -> str:
            """Отримання вмісту курсу за його ID.
            
            Args:
                course_id: ID курсу в системі Moodle
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
        
        @self.mcp.tool()
        async def get_user_info() -> str:
            """Отримання інформації про поточного користувача."""
            if not await self._ensure_authenticated():
                return "Необхідно спочатку виконати аутентифікацію"
            
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
                f"Роль: {'Викладач' if self.is_teacher else 'Студент'}"
            ]
            return "\n".join(info)
    
    def _register_resources(self):
        """Реєстрація MCP ресурсів."""
        
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