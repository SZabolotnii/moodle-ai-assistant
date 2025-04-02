import gradio as gr
import asyncio
import subprocess
import os
import json
import sys
from typing import Dict, Any, List, Tuple, Optional


try:
    from common.auth import MoodleAuth
except ImportError:
    # Спробувати інший шлях, якщо структура інша
    # Наприклад, якщо auth.py на рівень вище
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    from common.auth import MoodleAuth

# Аналогічно для MoodleMCPServer, якщо він існує
try:
    from mcp_server.moodle_server import MoodleMCPServer
except ImportError:
    # Якщо сервер в іншій директорії, налаштуйте шлях
    # print("Warning: MoodleMCPServer not found.")
    MoodleMCPServer = None # Заглушка, якщо не використовується або не знайдено

class TeacherDashboard:
    def __init__(self, moodle_url: str = "http://78.137.2.119:2929"):
        self.moodle_url = moodle_url
        # Ініціалізуємо MoodleAuth. Токен має завантажитись з .env
        self.auth = MoodleAuth(moodle_url)
        self.mcp_server = None # Атрибут для MoodleMCPServer, якщо використовується
        self.mcp_process = None

        # Стан дашборду
        self.courses = []
        self.selected_course = None
        self.selected_course_name = None
        self.students = []
        self.assignments = []

    def build_ui(self) -> gr.Blocks:
        """Побудова інтерфейсу панелі викладача."""
        with gr.Blocks(title="Moodle Асистент - Панель викладача") as dashboard:
            gr.Markdown("# Moodle Асистент - Панель викладача")

            with gr.Row():
                with gr.Column(scale=1):
                    # Блок інформації про користувача (завжди видимий тут)
                    with gr.Group() as user_info_group:
                        gr.Markdown("### Інформація про викладача")
                        # Встановлюємо початкове значення "Завантаження..."
                        user_info_output = gr.Textbox(label="Профіль", interactive=False, lines=6, value="Завантаження...")
                        # Запускаємо асинхронне оновлення, якщо токен та ID існують.
                        # Метод update_user_info сам обробить помилки, якщо вони виникнуть під час виконання.
                        if self.auth.token and self.auth.user_id:
                            print("Запуск task: update_user_info") # Debug
                            asyncio.create_task(self.update_user_info(user_info_output))
                        else:
                            # Якщо токена або ID немає ВЖЕ на етапі build_ui
                            # (що малоймовірно, якщо app.py працює правильно),
                            # встановлюємо початкове значення помилки.
                            auth_error_msg = "Помилка: Автентифікація не пройдена (перевірте токен/права)."
                            user_info_output = gr.Textbox(label="Профіль", interactive=False, lines=6, value=auth_error_msg)
                            print(f"Не запускаємо update_user_info: {auth_error_msg}") # Debug


                    # Блок курсів (завжди видимий тут)
                    with gr.Group() as courses_group:
                        gr.Markdown("### Мої курси")
                        refresh_courses_button = gr.Button("Оновити список курсів")
                        # Встановлюємо початкове значення "Завантаження..."
                        courses_dropdown = gr.Dropdown(label="Виберіть курс", choices=[("Завантаження...", None)], interactive=False)
                        # Запускаємо асинхронне оновлення, якщо токен та ID існують.
                        if self.auth.token and self.auth.user_id:
                             print("Запуск task: load_courses") # Debug
                             asyncio.create_task(self.load_courses(courses_dropdown))
                        # Повідомлення про помилку покаже сама функція load_courses

                with gr.Column(scale=2):
                    with gr.Tabs() as tabs:
                        # Вкладка інформації про курс
                        with gr.Tab("Інформація про курс"):
                            course_info_button = gr.Button("Отримати інформацію про курс")
                            course_info_output = gr.Textbox(label="Інформація про курс", interactive=False, lines=10)

                        # Вкладка студентів
                        with gr.Tab("Студенти"):
                            with gr.Row():
                                get_students_button = gr.Button("Отримати список студентів")
                                export_students_button = gr.Button("Експортувати список (CSV)")

                            students_output = gr.Dataframe(
                                headers=["ID", "Ім'я", "Email"],
                                datatype=["number", "str", "str"],
                                label="Студенти курсу"
                            )

                        # Вкладка завдань
                        with gr.Tab("Завдання"):
                            get_assignments_button = gr.Button("Отримати список завдань")
                            assignments_table = gr.Dataframe(
                                headers=["ID", "Назва", "Термін здачі", "Зданих робіт"],
                                datatype=["number", "str", "str", "number"],
                                label="Завдання курсу"
                            )

                            assignment_id_input = gr.Number(label="ID завдання")
                            get_submissions_button = gr.Button("Отримати здані роботи")
                            submissions_output = gr.Textbox(label="Здані роботи", interactive=False, lines=10)

                        # Вкладка оголошень
                        with gr.Tab("Оголошення"):
                            with gr.Group():
                                gr.Markdown("### Створення оголошення")
                                announcement_subject = gr.Textbox(label="Тема оголошення")
                                announcement_text = gr.Textbox(label="Текст оголошення", lines=5)
                                create_announcement_button = gr.Button("Опублікувати оголошення")
                                announcement_status = gr.Textbox(label="Статус", interactive=False)

                        # Вкладка асистента (зберігаємо, якщо використовується)
                        if MoodleMCPServer is not None: # Показуємо вкладку, тільки якщо сервер імпортовано
                            with gr.Tab("AI Асистент"):
                                gr.Markdown("### AI Асистент на базі MCP і Claude")

                                with gr.Row():
                                    mcp_status = gr.Textbox(label="Статус MCP сервера", value="Не запущено", interactive=False)
                                    with gr.Column():
                                        start_mcp_button = gr.Button("Запустити MCP сервер")
                                        stop_mcp_button = gr.Button("Зупинити MCP сервер")

                                gr.Markdown("""
                                #### Інструкція з підключення до Claude Desktop:
                                ... (текст інструкції) ...
                                """)

                                with gr.Accordion("Налаштування MCP сервера", open=False):
                                    mcp_config = gr.Code(label="Налаштування для claude_desktop_config.json", language="json")
                                    update_mcp_config_button = gr.Button("Оновити налаштування")

                                # Обробники для MCP сервера
                                start_mcp_button.click(
                                    fn=self.start_mcp_server,
                                    inputs=[],
                                    outputs=[mcp_status, mcp_config]
                                )
                                stop_mcp_button.click(
                                    fn=self.stop_mcp_server,
                                    inputs=[],
                                    outputs=[mcp_status]
                                )
                                update_mcp_config_button.click(
                                    fn=lambda c: self.update_mcp_config(c),
                                    inputs=[mcp_config],
                                    outputs=[mcp_status] # Оновлюємо статус після зміни конфігу
                                )

            # Функції обробки подій для основного дашборду
            refresh_courses_button.click(
                fn=self.load_courses_callback, # Викликаємо без asyncio.run, бо Gradio обробить async
                inputs=[],
                outputs=[courses_dropdown]
            )

            courses_dropdown.change(
                fn=self.select_course,
                inputs=[courses_dropdown],
                outputs=[] # Немає прямого виводу UI, оновлює стан self.selected_course
            )

            course_info_button.click(
                fn=self.get_course_info,
                inputs=[],
                outputs=[course_info_output]
            )

            get_students_button.click(
                fn=self.get_course_students,
                inputs=[],
                outputs=[students_output]
            )

            export_students_button.click(
                fn=self.export_students_list,
                inputs=[],
                # Виводить повідомлення через gr.Info/gr.Error, тому outputs не потрібен
                outputs=[]
            )

            get_assignments_button.click(
                fn=self.get_course_assignments,
                inputs=[],
                outputs=[assignments_table]
            )

            get_submissions_button.click(
                fn=self.get_assignment_submissions,
                inputs=[assignment_id_input],
                outputs=[submissions_output]
            )

            create_announcement_button.click(
                fn=self.create_announcement,
                inputs=[announcement_subject, announcement_text],
                outputs=[announcement_status]
            )

        return dashboard

    # --- Методи login та logout ВИДАЛЕНО ---

    async def update_user_info(self, info_output_component: gr.Textbox) -> None:
        """Оновлення інформації про користувача."""
        # Перевірка вже зроблена перед викликом, але дублюємо про всяк випадок
        if not self.auth.token or not self.auth.user_id:
             await asyncio.sleep(0) # Невелике очікування для Gradio
             info_output_component.update("Помилка: Не вдалося отримати інформацію (проблема автентифікації).")
             return

        try:
            print("Оновлення інформації про користувача...") # Debug
            success, data = await self.auth._call_api("core_user_get_users_by_field", {
                "field": "id",
                "values[0]": self.auth.user_id
            })

            if success and data and len(data) > 0:
                user = data[0]
                info = [
                    f"ID: {user.get('id', 'N/A')}",
                    f"Повне ім'я: {user.get('fullname', 'N/A')}",
                    f"Ім'я: {user.get('firstname', 'N/A')}",
                    f"Прізвище: {user.get('lastname', 'N/A')}",
                    f"Email: {user.get('email', 'N/A')}",
                    f"Є викладачем: {'Так' if self.auth.is_teacher else 'Ні (або не визначено)'}"
                ]
                info_output_component.update("\n".join(info))
                print("Інформація про користувача оновлена.") # Debug
            else:
                 error_msg = f"Не вдалося отримати дані користувача: {data if not success else 'Порожня відповідь'}"
                 print(error_msg) # Debug
                 info_output_component.update(error_msg)
        except Exception as e:
             error_msg = f"Критична помилка при оновленні інфо користувача: {e}"
             print(error_msg) # Debug
             import traceback
             traceback.print_exc() # Debug traceback
             info_output_component.update(error_msg)


    async def load_courses(self, dropdown_component: gr.Dropdown) -> None:
        """Завантаження курсів для випадаючого списку."""
        if not self.auth.token or not self.auth.user_id:
            await asyncio.sleep(0)
            dropdown_component.update(choices=[("Помилка автентифікації", None)], value=None, interactive=False)
            return

        try:
            print("Завантаження курсів...") # Debug
            success, data = await self.auth._call_api("core_enrol_get_users_courses", {
                "userid": self.auth.user_id
            })

            if success:
                self.courses = data # Зберігаємо повні дані
                # Формуємо список для Dropdown: (відображуване_ім'я, значення_id)
                courses_list = [(f"{course.get('fullname', 'Без назви')} (ID: {course.get('id', 'N/A')})", course.get('id'))
                                for course in data if course.get('id')] # Додаємо перевірку наявності ID
                if not courses_list:
                    dropdown_component.update(choices=[("Призначені курси не знайдено", None)], value=None, interactive=False)
                else:
                    # Оновлюємо список і робимо активним
                    dropdown_component.update(choices=courses_list, value=None, interactive=True)
                print(f"Курси завантажено: {len(courses_list)}") # Debug
            else:
                 error_msg = f"Помилка API при завантаженні курсів: {data}"
                 print(error_msg) # Debug
                 dropdown_component.update(choices=[(error_msg, None)], value=None, interactive=False)
        except Exception as e:
            error_msg = f"Критична помилка при завантаженні курсів: {e}"
            print(error_msg) # Debug
            import traceback
            traceback.print_exc() # Debug traceback
            dropdown_component.update(choices=[(error_msg, None)], value=None, interactive=False)

    async def load_courses_callback(self) -> Dict:
        """Завантаження курсів при натисканні кнопки оновлення (повертає оновлення для Gradio)."""
        if not self.auth.token or not self.auth.user_id:
            return gr.update(choices=[("Помилка автентифікації", None)], value=None, interactive=False)

        # Логіка аналогічна load_courses, але повертає gr.update
        try:
            print("Оновлення списку курсів (callback)...") # Debug
            success, data = await self.auth._call_api("core_enrol_get_users_courses", {
                "userid": self.auth.user_id
            })

            if success:
                self.courses = data
                courses_list = [(f"{course.get('fullname', 'Без назви')} (ID: {course.get('id', 'N/A')})", course.get('id'))
                                for course in data if course.get('id')]
                if not courses_list:
                    print("Призначені курси не знайдено (callback).") # Debug
                    return gr.update(choices=[("Призначені курси не знайдено", None)], value=None, interactive=False)
                else:
                    print(f"Курси оновлено: {len(courses_list)} (callback).") # Debug
                    return gr.update(choices=courses_list, value=None, interactive=True) # Скидаємо вибір
            else:
                 error_msg = f"Помилка API при оновленні курсів: {data}"
                 print(error_msg) # Debug
                 return gr.update(choices=[(error_msg, None)], value=None, interactive=False)
        except Exception as e:
             error_msg = f"Критична помилка при оновленні курсів: {e}"
             print(error_msg) # Debug
             import traceback
             traceback.print_exc() # Debug traceback
             return gr.update(choices=[(error_msg, None)], value=None, interactive=False)


    def select_course(self, course_repr: str) -> None:
        """
        Вибір курсу зі списку.
        Примітка: Gradio Dropdown повертає значення (ID), а не відображуване ім'я.
        """
        # course_repr тепер буде ID курсу (значення з choices)
        self.selected_course = course_repr # Зберігаємо ID
        self.selected_course_name = None # Скидаємо ім'я, знайдемо за ID
        print(f"Обрано курс ID: {self.selected_course}") # Debug

        if self.selected_course:
            # Знаходимо ім'я курсу в збереженому списку self.courses
            for course in self.courses:
                if course.get('id') == self.selected_course:
                    self.selected_course_name = course.get('fullname', 'Ім\'я не знайдено')
                    print(f"Знайдено ім'я курсу: {self.selected_course_name}") # Debug
                    break
            if not self.selected_course_name:
                 print(f"Попередження: Не вдалося знайти ім'я для курсу ID {self.selected_course} у списку self.courses.")


    async def get_course_info(self) -> str:
        """Отримання інформації про вибраний курс."""
        if not self.auth.token: return "Помилка: Не автентифіковано."
        if not self.selected_course: return "Будь ласка, спочатку виберіть курс зі списку."

        try:
            print(f"Отримання інформації для курсу ID: {self.selected_course}") # Debug
            success, data = await self.auth._call_api("core_course_get_contents", {
                "courseid": self.selected_course
            })

            if success:
                if not data:
                    course_name = self.selected_course_name or f"ID {self.selected_course}"
                    print(f"Вміст курсу '{course_name}' не знайдено або курс порожній.") # Debug
                    return f"Вміст курсу '{course_name}' не знайдено або курс порожній."

                sections_output = []
                for section in data:
                    section_name = section.get('name', 'Без назви')
                    section_info = f"Розділ: {section_name}"
                    modules_output = []
                    for module in section.get("modules", []):
                        mod_name = module.get('name', 'Без назви')
                        mod_type = module.get('modname', 'N/A')
                        module_info = f"  - {mod_name} (Тип: {mod_type}"
                        # Додамо ID для завдань (assign) та тестів (quiz) для зручності
                        if mod_type in ['assign', 'quiz', 'forum'] and 'instance' in module:
                             module_info += f", ID: {module['instance']}"
                        module_info += ")"
                        modules_output.append(module_info)

                    if modules_output:
                        section_info += "\n" + "\n".join(modules_output)
                    else:
                        section_info += "\n  (Розділ порожній)"
                    sections_output.append(section_info)

                result = "\n\n".join(sections_output)
                print(f"Інформація про курс ID {self.selected_course} отримана.") # Debug
                return result
            else:
                error_msg = f"Помилка API при отриманні вмісту курсу: {data}"
                print(error_msg) # Debug
                return error_msg
        except Exception as e:
            error_msg = f"Критична помилка при отриманні вмісту курсу: {e}"
            print(error_msg) # Debug
            import traceback
            traceback.print_exc() # Debug traceback
            return error_msg

    async def get_course_students(self) -> Dict:
        """Отримання списку студентів курсу (повертає оновлення для Dataframe)."""
        if not self.auth.token:
             return gr.update(value=[["Помилка автентифікації", "", ""]])
        if not self.selected_course:
             gr.Warning("Будь ласка, спочатку виберіть курс.")
             return gr.update(value=None) # Не змінюємо дані, якщо курс не вибрано

        try:
            print(f"Отримання студентів для курсу ID: {self.selected_course}") # Debug
            success, data = await self.auth._call_api("core_enrol_get_enrolled_users", {
                "courseid": self.selected_course
                # Можна додати параметри для фільтрації ролей на сервері, якщо API дозволяє
            })

            if success:
                # Фільтруємо користувачів з роллю 'student'
                students = [user for user in data if user.get('id') and any(role.get('shortname') == 'student' for role in user.get('roles', []))]

                if not students:
                    print(f"Студентів не знайдено в курсі ID {self.selected_course}.") # Debug
                    self.students = []
                    return gr.update(value=[["Студентів не знайдено", "", ""]]) # Повертаємо рядок-повідомлення

                self.students = students # Зберігаємо повні дані
                # Формуємо дані для Dataframe
                result_list = [[
                    student['id'],
                    student.get('fullname', 'N/A'),
                    student.get('email', 'N/A')
                    ] for student in students]
                print(f"Отримано студентів: {len(result_list)}") # Debug
                return gr.update(value=result_list)
            else:
                error_msg = f"Помилка API при отриманні студентів: {data}"
                print(error_msg) # Debug
                return gr.update(value=[[error_msg, "", ""]])
        except Exception as e:
            error_msg = f"Критична помилка при отриманні студентів: {e}"
            print(error_msg) # Debug
            import traceback
            traceback.print_exc() # Debug traceback
            return gr.update(value=[[error_msg, "", ""]])

    def export_students_list(self) -> None:
        """Експорт поточного списку студентів (self.students) у CSV файл."""
        if not self.students:
            gr.Warning("Список студентів порожній або ще не завантажений. Спочатку натисніть 'Отримати список студентів'.")
            return

        course_name_part = f"_{self.selected_course}" if self.selected_course else "_no_course_selected"
        # Очистка імені файлу від потенційно небезпечних символів
        safe_course_name = "".join(c if c.isalnum() or c in ('_','-') else '_' for c in str(self.selected_course_name or course_name_part))
        filename = f"students{safe_course_name}.csv"

        try:
            import csv
            print(f"Експорт списку студентів у файл: {filename}") # Debug
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['ID', 'Повне ім\'я', 'Email']) # Заголовки

                for student in self.students:
                    writer.writerow([
                        student.get('id', 'N/A'),
                        student.get('fullname', 'N/A'),
                        student.get('email', 'N/A')
                    ])
            gr.Info(f"Список студентів експортовано у файл: {filename}")
        except Exception as e:
            error_msg = f"Помилка експорту студентів: {e}"
            print(error_msg) # Debug
            import traceback
            traceback.print_exc() # Debug traceback
            gr.Error(error_msg)

    async def get_course_assignments(self) -> Dict:
        """Отримання списку завдань курсу (повертає оновлення для Dataframe)."""
        if not self.auth.token: return gr.update(value=[["Помилка автентифікації", "", "", ""]])
        if not self.selected_course:
             gr.Warning("Будь ласка, спочатку виберіть курс.")
             return gr.update(value=None)

        assignments_list_for_df = []
        self.assignments = [] # Очищуємо перед заповненням

        try:
            print(f"Отримання завдань для курсу ID: {self.selected_course}") # Debug
            # Використовуємо спеціалізовану функцію, якщо вона є і дозволена
            # mod_assign_get_assignments часто краще, ніж перебирати contents
            assign_success, assign_data = await self.auth._call_api("mod_assign_get_assignments", {
                "courseids[0]": self.selected_course
            })

            if assign_success and assign_data.get('courses'):
                print(f"Отримано дані завдань через mod_assign_get_assignments.") # Debug
                for course_info in assign_data['courses']:
                    if str(course_info.get('id')) == str(self.selected_course): # Перевірка ID курсу
                        for assignment in course_info.get('assignments', []):
                            assignment_id = assignment.get('id')
                            if not assignment_id: continue

                            submission_count = await self._get_submission_count(assignment_id) # Отримуємо кількість

                            due_date_ts = assignment.get('duedate')
                            due_date_str = "Немає"
                            if due_date_ts and due_date_ts > 0:
                                from datetime import datetime, timezone
                                try:
                                    # Moodle зазвичай повертає UTC timestamp
                                    due_date_str = datetime.fromtimestamp(due_date_ts, tz=timezone.utc).strftime('%d.%m.%Y %H:%M UTC')
                                except Exception as dt_err:
                                    print(f"Помилка форматування дати {due_date_ts}: {dt_err}")
                                    due_date_str = f"Timestamp: {due_date_ts}"

                            current_assignment = {
                                'id': assignment_id,
                                'name': assignment.get('name', 'Без назви'),
                                'duedate': due_date_str,
                                'submissions': submission_count # Зберігаємо отриману кількість
                            }
                            self.assignments.append(current_assignment)
                            assignments_list_for_df.append([
                                assignment_id,
                                current_assignment['name'],
                                current_assignment['duedate'],
                                submission_count # Використовуємо отриману кількість
                            ])
            else:
                # Запасний варіант через core_course_get_contents (менш ефективний)
                print("Функція mod_assign_get_assignments не повернула даних, спроба через core_course_get_contents...") # Debug
                success_cont, course_data = await self.auth._call_api("core_course_get_contents", {
                    "courseid": self.selected_course
                })
                if success_cont:
                    for section in course_data:
                         for module in section.get("modules", []):
                             if module.get("modname") == "assign":
                                 assignment_id = module.get('instance')
                                 if not assignment_id: continue

                                 submission_count = await self._get_submission_count(assignment_id)

                                 due_date_str = "Немає"
                                 # Дати в get_contents можуть бути в іншому форматі
                                 # Потрібно адаптувати логіку отримання дати, якщо використовується цей шлях

                                 current_assignment = {
                                     'id': assignment_id,
                                     'name': module.get('name', 'Без назви'),
                                     'duedate': due_date_str, # Потрібно реалізувати отримання дати з 'module'
                                     'submissions': submission_count
                                 }
                                 self.assignments.append(current_assignment)
                                 assignments_list_for_df.append([
                                     assignment_id,
                                     current_assignment['name'],
                                     current_assignment['duedate'],
                                     submission_count
                                 ])
                else:
                     error_msg = f"Помилка API при отриманні вмісту курсу: {course_data}"
                     print(error_msg) # Debug
                     return gr.update(value=[[error_msg, "", "", ""]])


            if not assignments_list_for_df:
                print(f"Завдань не знайдено в курсі ID {self.selected_course}.") # Debug
                return gr.update(value=[["Завдань не знайдено", "", "", ""]])
            else:
                print(f"Отримано завдань: {len(assignments_list_for_df)}") # Debug
                return gr.update(value=assignments_list_for_df)

        except Exception as e:
            error_msg = f"Критична помилка при отриманні завдань: {e}"
            print(error_msg) # Debug
            import traceback
            traceback.print_exc() # Debug traceback
            return gr.update(value=[[error_msg, "", "", ""]])


    async def _get_submission_count(self, assignment_id: int) -> int:
        """Отримання кількості зданих робіт для завдання."""
        # Додамо базові перевірки
        if not self.auth.token: return 0
        if not assignment_id: return 0

        try:
            # Використаємо API для отримання оцінок/статусів, а не повних робіт
            # mod_assign_get_grades може бути ефективнішим
            success, data = await self.auth._call_api("mod_assign_get_grades", {
                 "assignmentids[0]": assignment_id
            })

            count = 0
            if success and data.get('assignments'):
                 for assignment_info in data['assignments']:
                     if str(assignment_info.get('assignmentid')) == str(assignment_id):
                          for grade_info in assignment_info.get('grades', []):
                              # Потрібно перевірити статус здачі, якщо він є в get_grades
                              # Або просто рахувати записи, припускаючи, що це здані роботи
                              # Якщо get_grades не повертає статус 'submitted',
                              # тоді повертаємось до get_submissions, але це менш ефективно
                              # Поки що просто рахуємо записи оцінок
                              count += 1
                          break # Знайшли потрібне завдання
                 # Якщо get_grades не підходить, розкоментуйте старий варіант:
                 # success, data = await self.auth._call_api("mod_assign_get_submissions", {
                 #    "assignmentids[0]": assignment_id
                 # })
                 # if success and data.get("assignments"):
                 #      assignment = data["assignments"][0]
                 #      if "submissions" in assignment:
                 #           count = sum(1 for s in assignment["submissions"] if s.get("status") == "submitted")
            else:
                 print(f"Помилка або порожня відповідь від mod_assign_get_grades для ID {assignment_id}: {data}")

            # print(f"Кількість зданих для завдання {assignment_id}: {count}") # Debug
            return count
        except Exception as e:
            print(f"Помилка при отриманні кількості зданих для завдання {assignment_id}: {e}")
            return 0 # Повертаємо 0 у разі помилки


    async def get_assignment_submissions(self, assignment_id: Optional[int]) -> str:
        """Отримання інформації про здані роботи для завдання."""
        if not self.auth.token: return "Помилка: Не автентифіковано."
        if not assignment_id: return "Будь ласка, введіть ID завдання у поле вище."
        # Перетворимо на int про всяк випадок
        try:
            assignment_id = int(assignment_id)
        except (ValueError, TypeError):
            return "Некоректний ID завдання. Введіть число."

        try:
            print(f"Отримання зданих робіт для завдання ID: {assignment_id}") # Debug
            success, data = await self.auth._call_api("mod_assign_get_submissions", {
                "assignmentids[0]": assignment_id
            })

            if success:
                assignments_data = data.get("assignments")
                if not assignments_data:
                    return f"Дані для завдання з ID {assignment_id} не знайдено."

                assignment_data = assignments_data[0] # Припускаємо, що повернулось одне завдання
                assignment_name = assignment_data.get('assignmentname', f'Завдання ID: {assignment_id}') # Змінено ключ
                submissions = assignment_data.get("submissions")

                result_lines = [f"Завдання: {assignment_name}"]

                if not submissions:
                    result_lines.append("  Немає зданих робіт.")
                    return "\n".join(result_lines)

                # Отримаємо ID всіх користувачів одним запитом для ефективності
                user_ids = [s.get("userid") for s in submissions if s.get("userid")]
                user_info_map = {}
                if user_ids:
                    success_users, users_data = await self.auth._call_api("core_user_get_users_by_field", {
                        "field": "id",
                        # Формуємо параметри списку для Moodle API
                        **{f"values[{i}]": user_id for i, user_id in enumerate(user_ids)}
                    })
                    if success_users:
                        user_info_map = {user['id']: user for user in users_data}
                    else:
                         print(f"Помилка отримання даних користувачів: {users_data}")


                for submission in submissions:
                    user_id = submission.get("userid")
                    user_name = f"ID: {user_id}"
                    if user_id in user_info_map:
                        user_name = user_info_map[user_id].get("fullname", user_name)

                    status_key = submission.get("status")
                    status_text = f"Статус: {status_key}" # Показуємо як є
                    # Можна додати маппінг для перекладу статусів
                    status_map = {
                         "new": "Немає спроб",
                         "draft": "Чернетка",
                         "submitted": "Здано",
                         "marked": "Оцінено",
                         "graded": "Оцінено", # Інший можливий статус
                         # ... додати інші статуси за потреби
                    }
                    status_text = status_map.get(status_key, f"Статус: {status_key}")


                    time_modified_ts = submission.get("timemodified")
                    time_str = "N/A"
                    if time_modified_ts:
                        from datetime import datetime, timezone
                        try:
                            time_str = datetime.fromtimestamp(time_modified_ts, tz=timezone.utc).strftime('%d.%m.%Y %H:%M UTC')
                        except Exception as dt_err:
                             print(f"Помилка форматування дати {time_modified_ts}: {dt_err}")
                             time_str = f"Timestamp: {time_modified_ts}"

                    result_lines.append(f"\n  - Студент: {user_name} (ID: {user_id})")
                    result_lines.append(f"    {status_text}")
                    result_lines.append(f"    Останнє оновлення: {time_str}")

                    # Спробуємо отримати оцінку через get_grades (якщо є відповідний grade item)
                    # grade_info = await self._get_submission_grade(assignment_id, user_id)
                    # if grade_info:
                    #     result_lines.append(f"    Оцінка: {grade_info.get('grade', 'N/A')}")
                    #     result_lines.append(f"    Коментар оцінювача: {grade_info.get('feedback', 'N/A')}")

                    # Або беремо дані з плагінів, якщо вони є
                    # (Це може містити коментарі студента або оцінювача, залежно від типу плагіна)
                    if "plugins" in submission:
                        for plugin in submission["plugins"]:
                            plugin_type = plugin.get("type")
                            plugin_name = plugin.get("name")
                            # Коментарі до здачі (feedback) або файли (file)
                            if plugin_type == "comments" and "editorfields" in plugin:
                                for field in plugin["editorfields"]:
                                    if field.get("text"):
                                        result_lines.append(f"    Коментар ({plugin_name}): {field['text']}")
                            elif plugin_type == "file" and "fileareas" in plugin:
                                for area in plugin["fileareas"]:
                                     if area.get("files"):
                                         files_str = ", ".join([f.get('filename', 'N/A') for f in area["files"]])
                                         result_lines.append(f"    Файли ({area.get('areaname', plugin_name)}): {files_str}")

                print(f"Здані роботи для завдання {assignment_id} отримані.") # Debug
                return "\n".join(result_lines)
            else:
                error_msg = f"Помилка API при отриманні зданих робіт: {data}"
                print(error_msg) # Debug
                return error_msg
        except Exception as e:
            error_msg = f"Критична помилка при отриманні зданих робіт: {e}"
            print(error_msg) # Debug
            import traceback
            traceback.print_exc() # Debug traceback
            return error_msg


    async def create_announcement(self, subject: str, message: str) -> str:
        """Створення оголошення для курсу."""
        if not self.auth.token: return "Помилка: Не автентифіковано."
        if not self.selected_course: return "Будь ласка, спочатку виберіть курс."
        if not subject or not message: return "Будь ласка, введіть тему та текст оголошення."

        forum_id = None
        try:
            print(f"Пошук форуму оголошень для курсу ID: {self.selected_course}") # Debug
            # Спочатку отримання ID форуму оголошень для курсу
            success_cont, course_data = await self.auth._call_api("core_course_get_contents", {
                "courseid": self.selected_course
            })

            if not success_cont:
                return f"Помилка отримання вмісту курсу для пошуку форуму: {course_data}"

            # Пошук форуму оголошень (зазвичай перший форум у нульовій секції)
            if course_data and isinstance(course_data, list):
                 for section in course_data:
                     # Шукаємо в нульовій секції або якщо назва містить 'оголошення'
                     is_general_section = section.get('id') == 0 or 'general' in section.get('name','').lower()
                     if not is_general_section: continue # Пропускаємо інші секції для пришвидшення

                     for module in section.get("modules", []):
                         # Перевіряємо тип 'forum' і чи є це головним форумом курсу (зазвичай ім'я 'News forum' або 'Оголошення')
                         is_news_forum = module.get('modname') == 'forum' and module.get('id') == course_data[0].get('newsitems', [{}])[0].get('id') # Спроба знайти через newsitems
                         is_announcement_by_name = module.get('modname') == 'forum' and ('оголошення' in module.get('name', '').lower() or 'news forum' in module.get('name', '').lower())

                         if is_news_forum or is_announcement_by_name:
                             forum_id = module.get("instance")
                             print(f"Знайдено форум оголошень ID: {forum_id}") # Debug
                             break
                     if forum_id:
                         break # Знайшли, виходимо з зовнішнього циклу

            if not forum_id:
                print(f"Форум оголошень не знайдено автоматично в курсі ID: {self.selected_course}") # Debug
                return "Не вдалося автоматично знайти форум оголошень у цьому курсі. Можливо, він має нестандартну назву або структуру."

            # Створення оголошення
            print(f"Створення оголошення у форумі ID: {forum_id}") # Debug
            success_add, data_add = await self.auth._call_api("mod_forum_add_discussion", {
                "forumid": forum_id,
                "subject": subject.strip(),
                "message": message.strip(), # Видаляємо зайві пробіли
                # Формат повідомлення (HTML або MOODLE)
                "options[0][name]": "messageformat",
                "options[0][value]": 1, # 1 = HTML, 0 = MOODLE, 2 = PLAIN, 4 = MARKDOWN
                # Підписати всіх (зазвичай для оголошень це потрібно)
                "options[1][name]": "discussionsubscribe",
                "options[1][value]": 1 # 1 = Так, 0 = Ні
            })

            if success_add and data_add.get('discussionid'):
                disc_id = data_add['discussionid']
                print(f"Оголошення успішно створено! ID: {disc_id}") # Debug
                return f"Оголошення успішно створено! ID обговорення: {disc_id}"
            else:
                error_msg = f"Помилка API при створенні оголошення: {data_add}"
                print(error_msg) # Debug
                # Спробуємо надати більш детальну інформацію, якщо є
                if isinstance(data_add, dict):
                     if data_add.get("errorcode") == "cannotcreatediscussion":
                         return "Помилка: Недостатньо прав для створення обговорення в цьому форумі."
                     elif data_add.get("message"):
                         return f"Помилка створення оголошення: {data_add['message']}"
                return error_msg
        except Exception as e:
            error_msg = f"Критична помилка при створенні оголошення: {e}"
            print(error_msg) # Debug
            import traceback
            traceback.print_exc() # Debug traceback
            return error_msg

    # --- Методи для MCP сервера залишаються без змін ---
    def start_mcp_server(self) -> Tuple[str, str]:
        """Запуск MCP сервера."""
        if MoodleMCPServer is None:
             return "Помилка: Модуль MCP сервера не знайдено.", ""
        if self.mcp_process and self.mcp_process.poll() is None:
            return "MCP сервер вже запущено", self._generate_mcp_config()

        try:
            # Визначаємо шлях до скрипта сервера відносно поточного файлу
            server_script_path = os.path.join(os.path.dirname(__file__), "..", "mcp_server", "moodle_server.py")
            server_script_path = os.path.abspath(server_script_path) # Абсолютний шлях

            # Перевіряємо, чи існує файл сервера
            if not os.path.exists(server_script_path):
                 return f"Помилка: Файл сервера не знайдено за шляхом {server_script_path}", ""

            print(f"Запуск MCP сервера зі скрипта: {server_script_path}") # Debug
            # Використовуємо subprocess для запуску Python скрипта
            # Передаємо необхідні аргументи, якщо сервер їх очікує (напр., URL Moodle)
            # Припускаємо, що moodle_server.py приймає --base-url
            cmd = [sys.executable, server_script_path, "--base-url", self.moodle_url]
            # Додаємо токен як аргумент командного рядка (якщо сервер це підтримує)
            # Це може бути не дуже безпечно, краще передавати через змінні оточення або конфіг
            # if self.auth.token:
            #    cmd.extend(["--token", self.auth.token])

            self.mcp_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8', # Вказуємо кодування
                # Запускаємо в окремій директорії, якщо потрібно
                # cwd=os.path.dirname(server_script_path)
            )

            # Дамо серверу трохи часу на запуск (опціонально)
            # asyncio.sleep(2) # Не можна робити sleep в синхронній функції Gradio

            # Перевіримо, чи процес запустився (не завершився одразу з помилкою)
            if self.mcp_process.poll() is not None:
                stderr_output = self.mcp_process.stderr.read()
                error_msg = f"Помилка запуску MCP сервера. Код виходу: {self.mcp_process.returncode}. Помилка: {stderr_output}"
                print(error_msg)
                self.mcp_process = None
                return error_msg, ""

            print("MCP сервер успішно запущено (процес створено).") # Debug
            return "MCP сервер запущено", self._generate_mcp_config()

        except Exception as e:
            error_msg = f"Критична помилка запуску MCP сервера: {e}"
            print(error_msg) # Debug
            import traceback
            traceback.print_exc() # Debug traceback
            return error_msg, ""


    def stop_mcp_server(self) -> str:
        """Зупинка MCP сервера."""
        if self.mcp_process and self.mcp_process.poll() is None:
            print("Зупинка MCP сервера...") # Debug
            self.mcp_process.terminate() # Надсилаємо SIGTERM
            try:
                stdout, stderr = self.mcp_process.communicate(timeout=5) # Чекаємо завершення
                print("MCP сервер зупинено.") # Debug
                if stderr:
                     print(f"Помилки MCP сервера при зупинці: {stderr}")
                return "MCP сервер зупинено"
            except subprocess.TimeoutExpired:
                print("MCP сервер не відповів на terminate, примусова зупинка (kill)...") # Debug
                self.mcp_process.kill() # Надсилаємо SIGKILL
                stdout, stderr = self.mcp_process.communicate() # Отримуємо вивід після kill
                print("MCP сервер примусово зупинено.") # Debug
                return "MCP сервер примусово зупинено"
            finally:
                 self.mcp_process = None # Скидаємо процес
        else:
            print("Спроба зупинити MCP сервер, але він не запущений.") # Debug
            return "MCP сервер не запущено"


    def _generate_mcp_config(self) -> str:
        """Генерація конфігурації для Claude Desktop."""
        # Використовуємо той самий підхід до шляху, що й при запуску
        server_script_path = os.path.join(os.path.dirname(__file__), "..", "mcp_server", "moodle_server.py")
        server_script_path = os.path.abspath(server_script_path)

        # Передаємо аргументи, які використовувалися для запуску
        args = [server_script_path, "--base-url", self.moodle_url]
        # if self.auth.token: # Якщо токен передавався як аргумент
        #    args.extend(["--token", self.auth.token])

        config = {
            "mcpServers": {
                "moodle-assistant": {
                    # Використовуємо абсолютний шлях до інтерпретатора Python
                    "command": os.path.abspath(sys.executable),
                    "args": args,
                    # Можна вказати робочу директорію, якщо сервер цього потребує
                    # "cwd": os.path.dirname(server_script_path)
                }
            }
        }
        return json.dumps(config, indent=2)

    def update_mcp_config(self, config_json: str) -> str:
        """Оновлення конфігурації MCP сервера (збереження у файл)."""
        # Ця функція, ймовірно, не потрібна, якщо конфіг генерується динамічно.
        # Якщо ж користувач редагує конфіг і хоче його зберегти для ручного запуску,
        # то можна залишити.
        config_filename = "mcp_config_manual.json"
        try:
            # Перевірка валідності JSON
            loaded_config = json.loads(config_json)
            print(f"Збереження конфігурації MCP у файл: {config_filename}") # Debug
            with open(config_filename, "w", encoding='utf-8') as f:
                json.dump(loaded_config, f, indent=2, ensure_ascii=False)
            return f"Конфігурацію збережено у файл {config_filename}"
        except json.JSONDecodeError as e:
             error_msg = f"Помилка: Некоректний JSON формат конфігурації - {e}"
             print(error_msg) # Debug
             return error_msg
        except Exception as e:
            error_msg = f"Критична помилка збереження конфігурації MCP: {e}"
            print(error_msg) # Debug
            import traceback
            traceback.print_exc() # Debug traceback
            return error_msg