import os
import json
import httpx
from typing import Dict, Any, Tuple, Optional
from dotenv import load_dotenv # <-- Додано імпорт

# Завантажуємо змінні оточення з .env файлу (якщо він є)
# Це краще робити на початку скрипта або модуля
load_dotenv()

class MoodleAuth:
    # Видаляємо service_name, він більше не потрібен
    # Додаємо опціональний параметр token в __init__
    def __init__(self, base_url: str = "http://78.137.2.119:2929", token: Optional[str] = None):
        """
        Ініціалізація клієнта Moodle API.

        Args:
            base_url (str): Базова URL-адреса сайту Moodle.
            token (Optional[str]): API токен Moodle. Якщо не надано,
                                   спробує завантажити зі змінної оточення API_MOODLE_TOKEN.
        """
        self.base_url = base_url
        self.token = token # Спочатку встановлюємо з аргументу (якщо передано)
        self.authenticated = False  # Додаємо флаг стану автентифікації

        # Якщо токен не передано через аргумент, пробуємо завантажити з .env
        if self.token is None:
            self.token = os.getenv("API_MOODLE_TOKEN")
            if self.token:
                print("Токен успішно завантажено зі змінної оточення API_MOODLE_TOKEN.")
            else:
                print("Попередження: Токен не передано і змінна оточення API_MOODLE_TOKEN не знайдена.")

        # Ініціалізуємо решту полів
        self.username = None # Логін не використовується при автентифікації токеном
        self.user_id = None
        self.is_teacher = os.getenv("FORCE_TEACHER_ROLE", "").lower() == "true"
        if self.is_teacher:
            print("УВАГА: Роль викладача встановлена примусово через змінну оточення FORCE_TEACHER_ROLE")


    # Метод login більше не є основним способом автентифікації
    # Його можна закоментувати, видалити або залишити як альтернативу,
    # але пріоритет тепер у токена. Закоментуємо його, щоб уникнути випадкового використання.
    # async def login(self, username: str, password: str) -> Tuple[bool, str]:
    #    """Автентифікація в Moodle за логіном/паролем (НЕ РЕКОМЕНДОВАНО, ЯКЩО Є ТОКЕН)."""
    #    if self.token:
    #        return False, "Неможливо увійти за логіном/паролем, оскільки токен вже встановлено."
    #
    #    # ... (решта коду методу login залишається тут, якщо ви вирішите його залишити) ...
    #    print("ПОПЕРЕДЖЕННЯ: Використовується автентифікація за логіном/паролем. Рекомендується використовувати API токен.")
    #    # ... (решта коду методу login) ...


    async def authenticate_with_token(self) -> Tuple[bool, str]:
        """
        Перевіряє валідність наданого токена та отримує інформацію про користувача.
        Цей метод потрібно викликати після ініціалізації класу.
        """
        if not self.token:
            return False, "Токен не надано (через аргумент або змінну оточення API_MOODLE_TOKEN)"

        print("Перевірка валідності наданого токена...")
        is_valid, msg = await self.is_token_valid()

        if not is_valid:
            self.token = None
            self.authenticated = False
            print(f"Помилка: Наданий токен недійсний або термін дії закінчився. {msg}")
            return False, f"Наданий токен недійсний: {msg}"

        print("Токен дійсний. Отримання інформації про користувача...")
        if not self.user_id:
            info_ok, info_msg = await self._get_user_info()
            if not info_ok:
                self.authenticated = False
                print(f"Критична помилка: Не вдалося отримати User ID з валідним токеном: {info_msg}")
                return False, f"Не вдалося отримати User ID з валідним токеном: {info_msg}"
        else:
            info_ok = True

        success_site_info, site_info_data = await self._call_api("core_webservice_get_site_info")
        if success_site_info and isinstance(site_info_data, dict):
            self.username = site_info_data.get("username")
            print(f"Ім'я користувача (з токена): {self.username}")
        else:
            self.username = "TokenUser"

        role_ok = await self._get_user_role()
        if role_ok:
            print(f"Роль користувача визначена. is_teacher: {self.is_teacher}")
        else:
            print("Попередження: Не вдалося визначити роль користувача.")

        self.authenticated = True
        return True, "Автентифікація за допомогою токена успішна"

    async def update_user_info(self) -> Tuple[bool, str]:
        """Оновлення інформації про користувача."""
        if not self.token:
            return False, "Токен відсутній"

        if not self.authenticated:
            # Спробуємо автентифікуватися
            auth_success, auth_msg = await self.authenticate_with_token()
            if not auth_success:
                print(f"Не запускаємо update_user_info: {auth_msg}")
                return False, f"Автентифікація не пройдена: {auth_msg}"

        success, msg = await self._get_user_info()
        if not success:
            print(f"Помилка оновлення інформації користувача: {msg}")
            return False, f"Помилка оновлення інформації: {msg}"

        role_ok = await self._get_user_role()
        if not role_ok:
            print("Помилка оновлення ролі користувача")
            return False, "Не вдалося оновити роль користувача"

        print("Інформація користувача успішно оновлена")
        return True, "Інформація користувача оновлена успішно"

    async def _call_api(self, function: str, params: Optional[Dict[str, Any]] = None) -> Tuple[bool, Any]:
        """Виконання API запитів до Moodle."""
        # Перевірка токена тепер на початку authenticate_with_token
        if self.token is None:
             # Ця перевірка залишається про всяк випадок, якщо метод викликається до authenticate_with_token
             return False, "Токен не встановлено або невалідний."

        # --- Решта коду методу _call_api без змін ---
        try:
            url = f"{self.base_url}/webservice/rest/server.php"
            request_params = {
                "wstoken": self.token,
                "wsfunction": function,
                "moodlewsrestformat": "json"
            }
            # ... (обробка params) ...
            if params:
                processed_params = {}
                for key, value in params.items():
                    if isinstance(value, list):
                        for i, item in enumerate(value):
                            if isinstance(item, dict):
                                for sub_key, sub_value in item.items():
                                     processed_params[f"{key}[{i}][{sub_key}]"] = sub_value
                            else:
                                processed_params[f"{key}[{i}]"] = item
                    else:
                         processed_params[key] = value
                request_params.update(processed_params)

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(url, params=request_params)
                response.raise_for_status()
                try:
                    data = response.json()
                except json.JSONDecodeError as json_err:
                     print(f"Не вдалося декодувати JSON з API відповіді для функції {function}: {json_err}")
                     print(f"Тіло відповіді: {response.text[:500]}")
                     return False, f"Помилка: API {function} повернуло невалідний JSON"

                if isinstance(data, dict):
                    if "exception" in data:
                        error_msg = data.get('message', 'Невідома помилка Moodle API')
                        error_code = data.get('errorcode', 'unknown')
                        debug_info = data.get('debuginfo', '')
                        print(f"Помилка Moodle API ({function}). Код: {error_code}, Повідомлення: {error_msg}, Debug: {debug_info}")
                        # Якщо помилка - невалідний токен, скинемо його
                        if error_code == 'invalidtoken':
                             self.token = None
                             print("Токен визнано невалідним сервером.")
                        return False, f"Помилка Moodle API ({error_code}): {error_msg}"
                    elif "error" in data and "errorcode" in data and len(data.keys()) <= 3:
                        error_msg = data.get('error')
                        error_code = data.get('errorcode')
                        print(f"Помилка Moodle API ({function}). Код: {error_code}, Повідомлення: {error_msg}")
                        return False, f"Помилка Moodle API ({error_code}): {error_msg}"
                return True, data

        except httpx.HTTPStatusError as e:
             # Якщо помилка 403 або подібна, можливо токен невалідний
             if e.response.status_code in [403, 401]:
                 self.token = None # Припускаємо, що токен невалідний
                 print(f"Помилка HTTP {e.response.status_code} при виклику API {function}. Можливо, токен недійсний.")
                 return False, f"Помилка HTTP {e.response.status_code} (можливо, недійсний токен)"
             else:
                print(f"HTTP помилка при виклику API {function}: {e.response.status_code}")
                print(f"Тіло відповіді: {e.response.text[:500]}")
                return False, f"Помилка HTTP {e.response.status_code} при виклику API {function}"
        # ... (решта обробки помилок з _call_api) ...
        except httpx.TimeoutException:
            print(f"Помилка: Час очікування відповіді від API {function} вичерпано.")
            return False, f"Помилка: API {function} не відповіло вчасно (timeout)."
        except httpx.RequestError as e:
            print(f"Помилка мережі при виклику API {function}: {str(e)}")
            return False, f"Помилка мережі при виклику Moodle API {function}: {str(e)}"
        except Exception as e:
            import traceback
            print(f"Непередбачена помилка при виклику API {function}: {str(e)}")
            print(traceback.format_exc())
            return False, f"Непередбачена помилка при виклику Moodle API {function}: {str(e)}"


    async def _get_user_info(self) -> Tuple[bool, str]:
        """Отримання інформації про поточного користувача (ID)."""
        # Ця функція тепер використовується і для перевірки токена
        success, data = await self._call_api("core_webservice_get_site_info")

        if success and isinstance(data, dict) and "userid" in data:
            self.user_id = data["userid"]
            # Спробуємо зберегти і username, якщо він є у відповіді
            if "username" in data:
                self.username = data["username"]
            return True, "Інформація користувача (ID) отримана"
        elif not success:
             # Помилка (наприклад, invalidtoken) вже була залогована в _call_api
             # data тут буде повідомленням про помилку
             return False, f"Не вдалося викликати core_webservice_get_site_info: {data}"
        else:
             print(f"Відповідь від core_webservice_get_site_info не містить 'userid': {data}")
             return False, "Не вдалося отримати 'userid' з відповіді API"

    # Всередині класу MoodleAuth в auth.py
    async def _get_user_role(self) -> bool:
        """Визначення ролі користувача через перевірку прав у курсах."""
        if not self.user_id:
            print("User ID невідомий, неможливо перевірити права.")
            return False

        # Спочатку перевіряємо примусове призначення ролі
        force_teacher = os.getenv("FORCE_TEACHER_ROLE", "").lower() == "true"
        if force_teacher:
            self.is_teacher = True
            print("УВАГА: Роль викладача встановлена примусово через FORCE_TEACHER_ROLE")
            return True

        print(f"Отримання курсів для користувача ID: {self.user_id}")
        success, courses_data = await self._call_api("core_enrol_get_users_courses", {
            "userid": self.user_id
        })

        if not success or not isinstance(courses_data, list):
            print(f"Не вдалося отримати список курсів: {courses_data}")
            return False

        # Перевірка через параметри курсів
        for course in courses_data:
            if 'roleid' in course and course['roleid'] in [3, 4]:  # 3 і 4 часто відповідають викладачам
                self.is_teacher = True
                print(f"Знайдено роль викладача в курсі ID {course.get('id')}")
                return True
        
        # Якщо інформації про роль у курсі немає, спробуємо інший підхід
        try:
            for course_id in [course.get('id') for course in courses_data if course.get('id')]:
                print(f"  Отримання ролей для курсу ID {course_id}...")
                success_roles, roles_data = await self._call_api("core_enrol_get_enrolled_users", {
                    "courseid": course_id
                })
                
                if success_roles and isinstance(roles_data, list):
                    for user in roles_data:
                        if str(user.get('id')) == str(self.user_id):
                            for role in user.get('roles', []):
                                if role.get('shortname') in ['editingteacher', 'teacher', 'coursecreator', 'manager']:
                                    self.is_teacher = True
                                    print(f"Знайдено роль викладача ({role.get('shortname')}) в курсі ID {course_id}")
                                    return True
        except Exception as e:
            print(f"Помилка при перевірці ролей у курсі: {e}")
            
        self.is_teacher = False
        print("Права викладача не знайдено в жодному з курсів.")
        return True

    # Метод is_token_valid тепер використовує _get_user_info
    async def is_token_valid(self) -> Tuple[bool, str]:
        """Перевіряє, чи поточний токен ще дійсний, викликаючи _get_user_info."""
        if not self.token:
            return False, "Токен відсутній"

        # Просто викликаємо _get_user_info. Якщо успішно, токен валідний.
        # _get_user_info також встановить self.user_id.
        success, msg_or_data = await self._get_user_info()

        if success:
            return True, "Токен дійсний"
        else:
            # msg_or_data містить повідомлення про помилку з _get_user_info або _call_api
             return False, f"Перевірка токена не вдалася: {msg_or_data}"

    # Збереження/завантаження сесії більше не потрібні, оскільки токен
    # завантажується з .env, а решта даних отримується при кожному запуску.
    # Закоментуємо або видалимо ці методи.

    # def save_session(self, filename: str = "session.json") -> bool:
    #     """Збереження сесії у файл (НЕ РЕКОМЕНДУЄТЬСЯ З ТОКЕНОМ З .ENV)."""
    #     print("Попередження: Збереження сесії з токеном з .env не рекомендується.")
    #     # ... (можна зберегти user_id, is_teacher, але не сам токен) ...
    #     return False

    # def load_session(self, filename: str = "session.json") -> bool:
    #     """Завантаження сесії з файлу (НЕ ВИКОРИСТОВУЄТЬСЯ З ТОКЕНОМ З .ENV)."""
    #     print("Попередження: Завантаження сесії ігнорується, використовується токен з .env.")
    #     return False


# --- Приклад використання оновленого класу ---
async def main():
    print("Запуск Moodle AI Assistant...")
    # Створюємо екземпляр. Токен автоматично підтягнеться з .env
    # Можна також передати токен явно: moodle = MoodleAuth(token="ваш_токен_тут")
    moodle = MoodleAuth()

    # Автентифікуємось (перевіряємо токен і отримуємо дані)
    auth_ok, auth_msg = await moodle.authenticate_with_token()

    if not auth_ok:
        print(f"Помилка автентифікації: {auth_msg}")
        print("Перевірте наявність та правильність токена у файлі .env (API_MOODLE_TOKEN)")
        print("Або переконайтеся, що токен дійсний і має права на виклик core_webservice_get_site_info.")
        return # Вихід, якщо автентифікація не вдалася
    else:
        print(f"Успішно автентифіковано!")
        print(f"  Користувач (з токена): {moodle.username}")
        print(f"  User ID: {moodle.user_id}")
        print(f"  Є викладачем: {moodle.is_teacher}")

    # Подальші дії з використанням API...
    if moodle.token:
        print("\nПриклад виклику API: Отримання деталей користувача...")
        # Приклад: Отримати повну інформацію про себе
        success, user_details = await moodle._call_api(
            "core_user_get_users_by_field",
            params={"field": "id", "values[0]": moodle.user_id}
        )
        if success and user_details:
            print("Деталі користувача:")
            # Виводимо лише деякі поля для прикладу
            print(f"  Повне ім'я: {user_details[0].get('fullname')}")
            print(f"  Email: {user_details[0].get('email')}")
        elif success:
             print("API викликано успішно, але дані користувача не знайдено.")
        else:
            # user_details тут містить повідомлення про помилку
            print(f"Помилка отримання деталей користувача: {user_details}")

import asyncio

if __name__ == "__main__":
     # Переконайтесь, що ваш основний скрипт (app.py) викликає подібну логіку
     # для ініціалізації та автентифікації MoodleAuth перед використанням.
     asyncio.run(main())
