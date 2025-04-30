import gradio as gr
import asyncio
import subprocess
import os
import json
import sys
from typing import Dict, Any, List, Tuple, Optional

# Імпортуємо необхідні модулі з проекту
try:
    from common.auth import MoodleAuth
except ImportError:
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    from common.auth import MoodleAuth

try:
    from common.llm_provider import LLMProviderFactory
except ImportError:
    from common.llm_provider import LLMProviderFactory

# Аналогічно для MoodleMCPServer, якщо він існує
try:
    from mcp_server.moodle_server import MoodleMCPServer
except ImportError:
    MoodleMCPServer = None


class TeacherDashboard:
    """Клас для інтерфейсу викладача з підтримкою аналітичного та адміністративного режимів."""
    
    def __init__(self, moodle_url: str = "http://78.137.2.119:2929"):
        self.moodle_url = moodle_url
        self.auth = MoodleAuth(moodle_url)
        self.selected_course = None
        self.courses = []
        self.students = []
        self.assignments = []
        self.messages = []
        self.llm_provider = None
        self._initialize_auth()  # Викликаємо синхронно
        
    def _initialize_auth(self):
        """Ініціалізація автентифікації"""
        if self.auth.token:
            print("Спроба автоматичної автентифікації...")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                success, message = loop.run_until_complete(self.auth.authenticate_with_token())
                if success:
                    print(f"Автентифікація успішна. User ID: {self.auth.user_id}, Is Teacher: {self.auth.is_teacher}")
                else:
                    print(f"Помилка автентифікації: {message}")
            finally:
                loop.close()
    
    def build_ui(self) -> gr.Blocks:
        """Побудова інтерфейсу панелі викладача."""
        with gr.Blocks(title="Moodle Асистент - Панель викладача") as dashboard:
            gr.Markdown("# Moodle Асистент - Панель викладача")
            
            with gr.Row():
                with gr.Column(scale=1):
                    # Вибір режиму роботи
                    with gr.Group() as mode_selection_group:
                        gr.Markdown("### Режим роботи")
                        with gr.Row():
                            analytical_mode_button = gr.Button("Аналітичний режим", variant="primary")
                            administrative_mode_button = gr.Button("Адміністративний режим", variant="secondary")
                        
                        mode_status = gr.Textbox(label="Поточний режим", value="Аналітичний режим", interactive=False)
                    
                    # Блок інформації про користувача
                    with gr.Group() as user_info_group:
                        gr.Markdown("### Інформація про викладача")
                        user_info_output = gr.Textbox(label="Профіль", interactive=False, lines=6)
                        
                        # Оновлюємо інформацію про користувача синхронно
                        if self.auth.authenticated and self.auth.token and self.auth.user_id:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            try:
                                loop.run_until_complete(self.update_user_info(user_info_output))
                            finally:
                                loop.close()
                        else:
                            user_info_output.value = "Очікування автентифікації..."
                    
                    # Блок курсів
                    with gr.Group() as courses_group:
                        gr.Markdown("### Мої курси")
                        refresh_courses_button = gr.Button("Оновити список курсів")
                        courses_dropdown = gr.Dropdown(label="Виберіть курс", choices=[("Завантаження...", None)], interactive=False)
                        
                        # Завантажуємо курси синхронно
                        if self.auth.token and self.auth.user_id:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            try:
                                loop.run_until_complete(self.load_courses(courses_dropdown))
                            finally:
                                loop.close()
                
                with gr.Column(scale=2):
                    with gr.Tabs() as tabs:
                        # Вкладка інформації про курс (спільна для обох режимів)
                        with gr.Tab("Інформація про курс"):
                            course_info_button = gr.Button("Отримати інформацію про курс")
                            course_info_output = gr.Textbox(label="Інформація про курс", interactive=False, lines=10)
                        
                        # Вкладка студентів (спільна для обох режимів)
                        with gr.Tab("Студенти"):
                            with gr.Row():
                                get_students_button = gr.Button("Отримати список студентів")
                                export_students_button = gr.Button("Експортувати список (CSV)")
                            
                            students_output = gr.Dataframe(
                                headers=["ID", "Ім'я", "Email"],
                                datatype=["number", "str", "str"],
                                label="Студенти курсу"
                            )
                        
                        # Вкладка завдань (спільна для обох режимів)
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
                        
                        # Вкладки для аналітичного режиму
                        with gr.Tab("Аналітика", visible=True) as analytics_tab:
                            gr.Markdown("### Аналіз курсу")
                            
                            with gr.Group():
                                gr.Markdown("#### Активність студентів")
                                get_activity_button = gr.Button("Аналізувати активність студентів")
                                activity_output = gr.Textbox(label="Аналіз активності", interactive=False, lines=10)
                            
                            with gr.Group():
                                gr.Markdown("#### Статистика оцінювання")
                                get_grades_stats_button = gr.Button("Отримати статистику оцінювання")
                                grades_stats_output = gr.Textbox(label="Статистика оцінювання", interactive=False, lines=10)
                            
                            with gr.Group():
                                gr.Markdown("#### Генерація звітів")
                                report_type_dropdown = gr.Dropdown(
                                    label="Тип звіту",
                                    choices=[
                                        ("Загальна інформація про курс", "general"),
                                        ("Активність студентів", "activity"),
                                        ("Статистика завдань", "assignments"),
                                        ("Повний звіт", "full")
                                    ],
                                    value="general"
                                )
                                generate_report_button = gr.Button("Згенерувати звіт")
                                report_output = gr.Textbox(label="Звіт", interactive=False, lines=15)
                        
                        # Вкладки для адміністративного режиму
                        with gr.Tab("Управління контентом", visible=False) as content_tab:
                            gr.Markdown("### Управління контентом курсу")
                            
                            with gr.Accordion("Створення нового розділу", open=False):
                                section_name_input = gr.Textbox(label="Назва розділу")
                                section_desc_input = gr.Textbox(label="Опис розділу", lines=3)
                                create_section_button = gr.Button("Створити розділ")
                                section_status = gr.Textbox(label="Статус", interactive=False)
                            
                            with gr.Accordion("Створення нового елемента", open=False):
                                module_type_dropdown = gr.Dropdown(
                                    label="Тип елемента",
                                    choices=[
                                        ("Завдання", "assign"),
                                        ("Файл", "resource"),
                                        ("Сторінка", "page"),
                                        ("URL", "url"),
                                        ("Форум", "forum")
                                    ],
                                    value="assign"
                                )
                                module_name_input = gr.Textbox(label="Назва елемента")
                                module_desc_input = gr.Textbox(label="Опис елемента", lines=3)
                                section_id_input = gr.Number(label="ID розділу (0 - головний)")
                                create_module_button = gr.Button("Створити елемент")
                                module_status = gr.Textbox(label="Статус", interactive=False)
                        
                        # Вкладка оголошень (спільна для обох режимів)
                        with gr.Tab("Оголошення"):
                            with gr.Group():
                                gr.Markdown("### Створення оголошення")
                                announcement_subject = gr.Textbox(label="Тема оголошення")
                                announcement_text = gr.Textbox(label="Текст оголошення", lines=5)
                                create_announcement_button = gr.Button("Опублікувати оголошення")
                                announcement_status = gr.Textbox(label="Статус", interactive=False)
                        
                        # Вкладка AI асистента (спільна для обох режимів)
                        with gr.Tab("AI Асистент"):
                            gr.Markdown("### Спілкування з AI Асистентом")
                            
                            # Історія чату
                            chat_history_output = gr.Chatbot(label="Історія чату", height=400)
                            
                            # Введення та відправка
                            with gr.Row():
                                chat_input = gr.Textbox(label="Задайте питання", lines=2, placeholder="Наприклад: проаналізуй активність студентів у моєму курсі")
                                send_button = gr.Button("Відправити")
                            
                            # Вибір провайдера
                            with gr.Accordion("Налаштування AI", open=False):
                                provider_dropdown = gr.Dropdown(
                                    label="LLM Провайдер",
                                    choices=[("Claude (Anthropic)", "claude")],
                                    value="claude"
                                )
                                
                                init_provider_button = gr.Button("Ініціалізувати провайдера")
                                provider_status = gr.Textbox(label="Статус провайдера", interactive=False)
                        
                        # Вкладка MCP сервера
                        if MoodleMCPServer is not None:  # Показуємо вкладку тільки якщо сервер імпортовано
                            with gr.Tab("MCP Сервер"):
                                gr.Markdown("### AI Асистент на базі MCP і Claude")
                                
                                with gr.Row():
                                    mcp_status = gr.Textbox(label="Статус MCP сервера", value="Не запущено", interactive=False)
                                    with gr.Column():
                                        start_mcp_button = gr.Button("Запустити MCP сервер")
                                        stop_mcp_button = gr.Button("Зупинити MCP сервер")
                                
                                gr.Markdown("""
                                #### Інструкція з підключення до Claude Desktop:
                                1. Встановіть Claude Desktop з офіційного сайту: [claude.ai/download](https://claude.ai/download)
                                2. Після запуску MCP сервера налаштуйте інтеграцію у Claude Desktop
                                3. Виберіть "Підключити MCP сервер" у налаштуваннях
                                4. Використовуйте згенеровану JSON конфігурацію нижче
                                """)
                                
                                with gr.Accordion("Налаштування MCP сервера", open=False):
                                    mcp_config = gr.Code(label="Налаштування для claude_desktop_config.json", language="json")
                                    update_mcp_config_button = gr.Button("Оновити налаштування")
            
            # Обробники перемикання режимів
            analytical_mode_button.click(
                fn=self.switch_to_analytical_mode,
                inputs=[],
                outputs=[mode_status, analytics_tab, content_tab]
            )
            
            administrative_mode_button.click(
                fn=self.switch_to_administrative_mode,
                inputs=[],
                outputs=[mode_status, analytics_tab, content_tab]
            )
            
            # Функції обробки подій для основного дашборду
            refresh_courses_button.click(
                fn=self.load_courses_callback,
                inputs=[],
                outputs=[courses_dropdown]
            )
            
            courses_dropdown.change(
                fn=self.select_course,
                inputs=[courses_dropdown],
                outputs=[]
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
            
            # Обробники для аналітичного режиму
            get_activity_button.click(
                fn=self.analyze_student_activity,
                inputs=[],
                outputs=[activity_output]
            )
            
            get_grades_stats_button.click(
                fn=self.get_grades_statistics,
                inputs=[],
                outputs=[grades_stats_output]
            )
            
            generate_report_button.click(
                fn=self.generate_report,
                inputs=[report_type_dropdown],
                outputs=[report_output]
            )
            
            # Обробники для адміністративного режиму
            create_section_button.click(
                fn=self.create_course_section,
                inputs=[section_name_input, section_desc_input],
                outputs=[section_status]
            )
            
            create_module_button.click(
                fn=self.create_course_module,
                inputs=[module_type_dropdown, module_name_input, module_desc_input, section_id_input],
                outputs=[module_status]
            )
            
            # Обробники для AI Асистента
            init_provider_button.click(
                fn=self.init_provider_callback,
                inputs=[provider_dropdown],
                outputs=[provider_status]
            )
            
            send_button.click(
                fn=self.send_message,
                inputs=[chat_input],
                outputs=[chat_history_output, chat_input]
            )
            
            # Обробники для MCP сервера
            if MoodleMCPServer is not None:
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
                    outputs=[mcp_status]
                )
        
        return dashboard
    
    def switch_to_analytical_mode(self) -> Tuple[str, Dict, Dict]:
        """Перемикання в аналітичний режим."""
        self.mode = "analytical"
        print("Перемикання в аналітичний режим")
        return (
            "Аналітичний режим",
            gr.update(visible=True),
            gr.update(visible=False)
        )
    
    def switch_to_administrative_mode(self) -> Tuple[str, Dict, Dict]:
        """Перемикання в адміністративний режим."""
        self.mode = "administrative"
        print("Перемикання в адміністративний режим")
        return (
            "Адміністративний режим",
            gr.update(visible=False),
            gr.update(visible=True)
        )
    
    async def update_user_info(self, info_output_component: gr.Textbox) -> None:
        """Оновлення інформації про користувача."""
        if not self.auth.token or not self.auth.user_id:
            await asyncio.sleep(0)
            info_output_component.value = "Помилка: Не вдалося отримати інформацію (проблема автентифікації)."
            return
        
        try:
            print("Оновлення інформації про користувача...")
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
                info_output_component.value = "\n".join(info)
                print("Інформація про користувача оновлена.")
            else:
                error_msg = f"Не вдалося отримати дані користувача: {data if not success else 'Порожня відповідь'}"
                print(error_msg)
                info_output_component.value = error_msg
        except Exception as e:
            error_msg = f"Критична помилка при оновленні інфо користувача: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            info_output_component.value = error_msg
    
    async def load_courses(self, dropdown_component: gr.Dropdown) -> None:
        """Завантаження курсів для випадаючого списку."""
        if not self.auth.token or not self.auth.user_id:
            await asyncio.sleep(0)
            dropdown_component.choices = [("Помилка автентифікації", None)]
            dropdown_component.value = None
            dropdown_component.interactive = False
            return
        
        try:
            print("Завантаження курсів...")
            success, data = await self.auth._call_api("core_enrol_get_users_courses", {
                "userid": self.auth.user_id
            })
            
            if success:
                self.courses = data
                courses_list = [(f"{course.get('fullname', 'Без назви')} (ID: {course.get('id', 'N/A')})", course.get('id'))
                               for course in data if course.get('id')]
                
                if not courses_list:
                    dropdown_component.choices = [("Призначені курси не знайдено", None)]
                    dropdown_component.value = None
                    dropdown_component.interactive = False
                else:
                    dropdown_component.choices = courses_list
                    dropdown_component.value = None
                    dropdown_component.interactive = True
                print(f"Курси завантажено: {len(courses_list)}")
            else:
                error_msg = f"Помилка API при завантаженні курсів: {data}"
                print(error_msg)
                dropdown_component.choices = [(error_msg, None)]
                dropdown_component.value = None
                dropdown_component.interactive = False
        except Exception as e:
            error_msg = f"Критична помилка при завантаженні курсів: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            dropdown_component.choices = [(error_msg, None)]
            dropdown_component.value = None
            dropdown_component.interactive = False
    
    async def load_courses_callback(self) -> Dict:
        """Завантаження курсів при натисканні кнопки оновлення (повертає оновлення для Gradio)."""
        if not self.auth.token or not self.auth.user_id:
            return gr.update(choices=[("Помилка автентифікації", None)], value=None, interactive=False)
        
        try:
            print("Оновлення списку курсів (callback)...")
            success, data = await self.auth._call_api("core_enrol_get_users_courses", {
                "userid": self.auth.user_id
            })
            
            if success:
                self.courses = data
                courses_list = [(f"{course.get('fullname', 'Без назви')} (ID: {course.get('id', 'N/A')})", course.get('id'))
                               for course in data if course.get('id')]
                
                if not courses_list:
                    print("Призначені курси не знайдено (callback).")
                    return gr.update(choices=[("Призначені курси не знайдено", None)], value=None, interactive=False)
                else:
                    print(f"Курси оновлено: {len(courses_list)} (callback).")
                    return gr.update(choices=courses_list, value=None, interactive=True)
            else:
                error_msg = f"Помилка API при оновленні курсів: {data}"
                print(error_msg)
                return gr.update(choices=[(error_msg, None)], value=None, interactive=False)
        except Exception as e:
            error_msg = f"Критична помилка при оновленні курсів: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return gr.update(choices=[(error_msg, None)], value=None, interactive=False)
    
    def select_course(self, course_id: str) -> None:
        """Вибір курсу зі списку."""
        self.selected_course = course_id
        self.selected_course_name = None
        print(f"Обрано курс ID: {self.selected_course}")
        
        if self.selected_course:
            for course in self.courses:
                if course.get('id') == self.selected_course:
                    self.selected_course_name = course.get('fullname', 'Ім\'я не знайдено')
                    print(f"Знайдено ім'я курсу: {self.selected_course_name}")
                    break
            if not self.selected_course_name:
                print(f"Попередження: Не вдалося знайти ім'я для курсу ID {self.selected_course} у списку self.courses.")
    
    async def get_course_info(self) -> str:
        """Отримання інформації про вибраний курс."""
        if not self.auth.token:
            return "Помилка: Не автентифіковано."
        if not self.selected_course:
            return "Будь ласка, спочатку виберіть курс зі списку."
        
        try:
            print(f"Отримання інформації для курсу ID: {self.selected_course}")
            success, data = await self.auth._call_api("core_course_get_contents", {
                "courseid": self.selected_course
            })
            
            if success:
                if not data:
                    course_name = self.selected_course_name or f"ID {self.selected_course}"
                    print(f"Вміст курсу '{course_name}' не знайдено або курс порожній.")
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
                print(f"Інформація про курс ID {self.selected_course} отримана.")
                return result
            else:
                error_msg = f"Помилка API при отриманні вмісту курсу: {data}"
                print(error_msg)
                return error_msg
        except Exception as e:
            error_msg = f"Критична помилка при отриманні вмісту курсу: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return error_msg
    
    async def get_course_students(self) -> Dict:
        """Отримання списку студентів курсу (повертає оновлення для Dataframe)."""
        if not self.auth.token:
            return gr.update(value=[["Помилка автентифікації", "", ""]])
        if not self.selected_course:
            gr.Warning("Будь ласка, спочатку виберіть курс.")
            return gr.update(value=None)
        
        try:
            print(f"Отримання студентів для курсу ID: {self.selected_course}")
            success, data = await self.auth._call_api("core_enrol_get_enrolled_users", {
                "courseid": self.selected_course
            })
            
            if success:
                # Фільтруємо користувачів з роллю 'student'
                students = [user for user in data if user.get('id') and any(role.get('shortname') == 'student' for role in user.get('roles', []))]
                
                if not students:
                    print(f"Студентів не знайдено в курсі ID {self.selected_course}.")
                    self.students = []
                    return gr.update(value=[["Студентів не знайдено", "", ""]])
                
                self.students = students
                result_list = [[
                    student['id'],
                    student.get('fullname', 'N/A'),
                    student.get('email', 'N/A')
                ] for student in students]
                print(f"Отримано студентів: {len(result_list)}")
                return gr.update(value=result_list)
            else:
                error_msg = f"Помилка API при отриманні студентів: {data}"
                print(error_msg)
                return gr.update(value=[[error_msg, "", ""]])
        except Exception as e:
            error_msg = f"Критична помилка при отриманні студентів: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return gr.update(value=[[error_msg, "", ""]])
    
    def export_students_list(self) -> None:
        """Експорт поточного списку студентів (self.students) у CSV файл."""
        if not self.students:
            gr.Warning("Список студентів порожній або ще не завантажений. Спочатку натисніть 'Отримати список студентів'.")
            return
        
        course_name_part = f"_{self.selected_course}" if self.selected_course else "_no_course_selected"
        safe_course_name = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in str(self.selected_course_name or course_name_part))
        filename = f"students{safe_course_name}.csv"
        
        try:
            import csv
            print(f"Експорт списку студентів у файл: {filename}")
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['ID', 'Повне ім\'я', 'Email'])
                
                for student in self.students:
                    writer.writerow([
                        student.get('id', 'N/A'),
                        student.get('fullname', 'N/A'),
                        student.get('email', 'N/A')
                    ])
            gr.Info(f"Список студентів експортовано у файл: {filename}")
        except Exception as e:
            error_msg = f"Помилка експорту студентів: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            gr.Error(error_msg)
    
    async def get_course_assignments(self) -> Dict:
        """Отримання списку завдань курсу (повертає оновлення для Dataframe)."""
        if not self.auth.token:
            return gr.update(value=[["Помилка автентифікації", "", "", ""]])
        if not self.selected_course:
            gr.Warning("Будь ласка, спочатку виберіть курс.")
            return gr.update(value=None)
        
        assignments_list_for_df = []
        self.assignments = []
        
        try:
            print(f"Отримання завдань для курсу ID: {self.selected_course}")
            success, data = await self.auth._call_api("mod_assign_get_assignments", {
                "courseids[0]": self.selected_course
            })
            
            if success and "courses" in data:
                print(f"Отримано дані завдань через mod_assign_get_assignments.")
                for course_info in data['courses']:
                    if str(course_info.get('id')) == str(self.selected_course):
                        for assignment in course_info.get('assignments', []):
                            assignment_id = assignment.get('id')
                            if not assignment_id:
                                continue
                            
                            submission_count = await self._get_submission_count(assignment_id)
                            
                            due_date_ts = assignment.get('duedate')
                            due_date_str = "Немає"
                            if due_date_ts and due_date_ts > 0:
                                from datetime import datetime, timezone
                                try:
                                    due_date_str = datetime.fromtimestamp(due_date_ts, tz=timezone.utc).strftime('%d.%m.%Y %H:%M UTC')
                                except Exception as dt_err:
                                    print(f"Помилка форматування дати {due_date_ts}: {dt_err}")
                                    due_date_str = f"Timestamp: {due_date_ts}"
                            
                            current_assignment = {
                                'id': assignment_id,
                                'name': assignment.get('name', 'Без назви'),
                                'duedate': due_date_str,
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
                print("Функція mod_assign_get_assignments не повернула даних, спроба через core_course_get_contents...")
                success_cont, course_data = await self.auth._call_api("core_course_get_contents", {
                    "courseid": self.selected_course
                })
                if success_cont:
                    for section in course_data:
                        for module in section.get("modules", []):
                            if module.get("modname") == "assign":
                                assignment_id = module.get('instance')
                                if not assignment_id:
                                    continue
                                
                                submission_count = await self._get_submission_count(assignment_id)
                                
                                due_date_str = "Немає"
                                
                                current_assignment = {
                                    'id': assignment_id,
                                    'name': module.get('name', 'Без назви'),
                                    'duedate': due_date_str,
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
                    print(error_msg)
                    return gr.update(value=[[error_msg, "", "", ""]])
            
            if not assignments_list_for_df:
                print(f"Завдань не знайдено в курсі ID {self.selected_course}.")
                return gr.update(value=[["Завдань не знайдено", "", "", ""]])
            else:
                print(f"Отримано завдань: {len(assignments_list_for_df)}")
                return gr.update(value=assignments_list_for_df)
        
        except Exception as e:
            error_msg = f"Критична помилка при отриманні завдань: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return gr.update(value=[[error_msg, "", "", ""]])
    
    async def _get_submission_count(self, assignment_id: int) -> int:
        """Отримання кількості зданих робіт для завдання."""
        if not self.auth.token or not assignment_id:
            return 0
        
        try:
            success, data = await self.auth._call_api("mod_assign_get_grades", {
                "assignmentids[0]": assignment_id
            })
            
            count = 0
            if success and data.get('assignments'):
                for assignment_info in data['assignments']:
                    if str(assignment_info.get('assignmentid')) == str(assignment_id):
                        for grade_info in assignment_info.get('grades', []):
                            count += 1
                        break
            else:
                print(f"Помилка або порожня відповідь від mod_assign_get_grades для ID {assignment_id}: {data}")
            
            return count
        except Exception as e:
            print(f"Помилка при отриманні кількості зданих для завдання {assignment_id}: {e}")
            return 0
    
    async def get_assignment_submissions(self, assignment_id: Optional[int]) -> str:
        """Отримання інформації про здані роботи для завдання."""
        if not self.auth.token:
            return "Помилка: Не автентифіковано."
        if not assignment_id:
            return "Будь ласка, введіть ID завдання у поле вище."
        
        try:
            assignment_id = int(assignment_id)
        except (ValueError, TypeError):
            return "Некоректний ID завдання. Введіть число."
        
        try:
            print(f"Отримання зданих робіт для завдання ID: {assignment_id}")
            success, data = await self.auth._call_api("mod_assign_get_submissions", {
                "assignmentids[0]": assignment_id
            })
            
            if success:
                assignments_data = data.get("assignments")
                if not assignments_data:
                    return f"Дані для завдання з ID {assignment_id} не знайдено."
                
                assignment_data = assignments_data[0]
                assignment_name = assignment_data.get('assignmentname', f'Завдання ID: {assignment_id}')
                submissions = assignment_data.get("submissions")
                
                result_lines = [f"Завдання: {assignment_name}"]
                
                if not submissions:
                    result_lines.append("  Немає зданих робіт.")
                    return "\n".join(result_lines)
                
                user_ids = [s.get("userid") for s in submissions if s.get("userid")]
                user_info_map = {}
                if user_ids:
                    success_users, users_data = await self.auth._call_api("core_user_get_users_by_field", {
                        "field": "id",
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
                    status_map = {
                        "new": "Немає спроб",
                        "draft": "Чернетка",
                        "submitted": "Здано",
                        "marked": "Оцінено",
                        "graded": "Оцінено",
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
                    
                    if "plugins" in submission:
                        for plugin in submission["plugins"]:
                            if plugin.get("type") == "comments" and "editorfields" in plugin:
                                for field in plugin["editorfields"]:
                                    if field.get("text"):
                                        result_lines.append(f"    Коментар: {field['text']}")
                            elif plugin.get("type") == "file" and "fileareas" in plugin:
                                for area in plugin["fileareas"]:
                                    if area.get("files"):
                                        files_str = ", ".join([f.get('filename', 'N/A') for f in area["files"]])
                                        result_lines.append(f"    Файли: {files_str}")
                
                print(f"Здані роботи для завдання {assignment_id} отримані.")
                return "\n".join(result_lines)
            else:
                error_msg = f"Помилка API при отриманні зданих робіт: {data}"
                print(error_msg)
                return error_msg
        except Exception as e:
            error_msg = f"Критична помилка при отриманні зданих робіт: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return error_msg
    
    async def create_announcement(self, subject: str, message: str) -> str:
        """Створення оголошення для курсу."""
        if not self.auth.token:
            return "Помилка: Не автентифіковано."
        if not self.selected_course:
            return "Будь ласка, спочатку виберіть курс."
        if not subject or not message:
            return "Будь ласка, введіть тему та текст оголошення."
        
        forum_id = None
        try:
            print(f"Пошук форуму оголошень для курсу ID: {self.selected_course}")
            success_cont, course_data = await self.auth._call_api("core_course_get_contents", {
                "courseid": self.selected_course
            })
            
            if not success_cont:
                return f"Помилка отримання вмісту курсу для пошуку форуму: {course_data}"
            
            if course_data and isinstance(course_data, list):
                for section in course_data:
                    is_general_section = section.get('id') == 0 or 'general' in section.get('name', '').lower()
                    if not is_general_section:
                        continue
                    
                    for module in section.get("modules", []):
                        is_news_forum = module.get('modname') == 'forum' and module.get('id') == course_data[0].get('newsitems', [{}])[0].get('id')
                        is_announcement_by_name = module.get('modname') == 'forum' and ('оголошення' in module.get('name', '').lower() or 'news forum' in module.get('name', '').lower())
                        
                        if is_news_forum or is_announcement_by_name:
                            forum_id = module.get("instance")
                            print(f"Знайдено форум оголошень ID: {forum_id}")
                            break
                    if forum_id:
                        break
            
            if not forum_id:
                print(f"Форум оголошень не знайдено автоматично в курсі ID: {self.selected_course}")
                return "Не вдалося автоматично знайти форум оголошень у цьому курсі. Можливо, він має нестандартну назву або структуру."
            
            print(f"Створення оголошення у форумі ID: {forum_id}")
            success_add, data_add = await self.auth._call_api("mod_forum_add_discussion", {
                "forumid": forum_id,
                "subject": subject.strip(),
                "message": message.strip(),
                "options[0][name]": "messageformat",
                "options[0][value]": 1,
                "options[1][name]": "discussionsubscribe",
                "options[1][value]": 1
            })
            
            if success_add and data_add.get('discussionid'):
                disc_id = data_add['discussionid']
                print(f"Оголошення успішно створено! ID: {disc_id}")
                return f"Оголошення успішно створено! ID обговорення: {disc_id}"
            else:
                error_msg = f"Помилка API при створенні оголошення: {data_add}"
                print(error_msg)
                if isinstance(data_add, dict):
                    if data_add.get("errorcode") == "cannotcreatediscussion":
                        return "Помилка: Недостатньо прав для створення обговорення в цьому форумі."
                    elif data_add.get("message"):
                        return f"Помилка створення оголошення: {data_add['message']}"
                return error_msg
        except Exception as e:
            error_msg = f"Критична помилка при створенні оголошення: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return error_msg
    
    async def analyze_student_activity(self) -> str:
        """Аналіз активності студентів у курсі."""
        if not self.auth.token:
            return "Помилка: Не автентифіковано."
        if not self.selected_course:
            return "Будь ласка, спочатку виберіть курс."
        
        try:
            print(f"Аналіз активності студентів для курсу ID: {self.selected_course}")
            # Отримання списку студентів, якщо він ще не завантажений
            if not self.students:
                success, data = await self.auth._call_api("core_enrol_get_enrolled_users", {
                    "courseid": self.selected_course
                })
                if success:
                    self.students = [user for user in data if user.get('id') and any(role.get('shortname') == 'student' for role in user.get('roles', []))]
                else:
                    return f"Помилка отримання списку студентів: {data}"
            
            if not self.students:
                return "Студентів не знайдено в цьому курсі."
            
            # Отримання логів активності для курсу
            success_logs, logs_data = await self.auth._call_api("report_log_get_course_log", {
                "courseid": self.selected_course,
                "enddate": 0,  # 0 означає "до теперішнього часу"
                "startdate": 0,  # Від початку курсу
                "page": 0,
                "perpage": 1000  # Обмеження кількості записів
            })
            
            if not success_logs:
                return f"Помилка отримання логів активності: {logs_data}"
            
            # Аналіз активності
            student_activities = {}
            for log in logs_data.get("logs", []):
                user_id = log.get("userid")
                if not user_id:
                    continue
                
                # Перевіряємо, чи це студент
                if not any(str(student.get('id')) == str(user_id) for student in self.students):
                    continue
                
                if user_id not in student_activities:
                    student_name = next((student.get('fullname', f'ID: {user_id}') for student in self.students if str(student.get('id')) == str(user_id)), f'ID: {user_id}')
                    student_activities[user_id] = {
                        "name": student_name,
                        "total_actions": 0,
                        "last_access": 0,
                        "actions": {}
                    }
                
                # Додаємо активність
                student_activities[user_id]["total_actions"] += 1
                
                # Оновлюємо час останнього доступу
                timestamp = log.get("timecreated", 0)
                if timestamp > student_activities[user_id]["last_access"]:
                    student_activities[user_id]["last_access"] = timestamp
                
                # Рахуємо типи дій
                action = log.get("action", "unknown")
                if action not in student_activities[user_id]["actions"]:
                    student_activities[user_id]["actions"][action] = 0
                student_activities[user_id]["actions"][action] += 1
            
            # Формуємо звіт
            if not student_activities:
                return "Активність студентів не знайдена в логах курсу."
            
            report_lines = [f"Аналіз активності студентів у курсі '{self.selected_course_name or self.selected_course}'"]
            report_lines.append("")
            
            # Сортуємо студентів за кількістю дій (найактивніші спочатку)
            sorted_students = sorted(
                student_activities.values(),
                key=lambda x: x["total_actions"],
                reverse=True
            )
            
            for student in sorted_students:
                # Форматуємо час останнього доступу
                last_access_str = "Ніколи"
                if student["last_access"] > 0:
                    from datetime import datetime
                    last_access_str = datetime.fromtimestamp(student["last_access"]).strftime('%d.%m.%Y %H:%M')
                
                report_lines.append(f"Студент: {student['name']}")
                report_lines.append(f"Загальна кількість дій: {student['total_actions']}")
                report_lines.append(f"Останній доступ: {last_access_str}")
                
                # Топ-3 найчастіших дій
                if student["actions"]:
                    top_actions = sorted(
                        student["actions"].items(),
                        key=lambda x: x[1],
                        reverse=True
                    )[:3]
                    
                    report_lines.append("Найчастіші дії:")
                    for action, count in top_actions:
                        report_lines.append(f"- {action}: {count}")
                
                report_lines.append("")
            
            # Додаємо загальну статистику
            total_actions = sum(student["total_actions"] for student in student_activities.values())
            avg_actions = total_actions / len(student_activities) if student_activities else 0
            
            report_lines.append("Загальна статистика:")
            report_lines.append(f"Всього студентів: {len(self.students)}")
            report_lines.append(f"Активних студентів: {len(student_activities)}")
            report_lines.append(f"Загальна кількість дій: {total_actions}")
            report_lines.append(f"Середня кількість дій на студента: {avg_actions:.2f}")
            
            return "\n".join(report_lines)
        except Exception as e:
            error_msg = f"Критична помилка при аналізі активності студентів: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return error_msg
    
    async def get_grades_statistics(self) -> str:
        """Отримання статистики оцінювання для курсу."""
        if not self.auth.token:
            return "Помилка: Не автентифіковано."
        if not self.selected_course:
            return "Будь ласка, спочатку виберіть курс."
        
        try:
            print(f"Отримання статистики оцінювання для курсу ID: {self.selected_course}")
            success, data = await self.auth._call_api("gradereport_user_get_grade_items", {
                "courseid": self.selected_course
            })
            
            if not success:
                return f"Помилка отримання оцінок: {data}"
            
            if "usergrades" not in data or not data["usergrades"]:
                return "Оцінки не знайдені для цього курсу."
            
            # Словник для зберігання статистики за кожним елементом оцінювання
            grade_stats = {}
            
            # Проходимо по всіх оцінках
            for usergrade in data["usergrades"]:
                for grade_item in usergrade.get("gradeitems", []):
                    item_id = grade_item.get("id")
                    if not item_id:
                        continue
                    
                    item_name = grade_item.get("itemname", f"ID: {item_id}")
                    if not item_name:
                        continue
                    
                    grade_value = grade_item.get("graderaw")
                    if grade_value is None:
                        continue
                    
                    if item_name not in grade_stats:
                        grade_stats[item_name] = {
                            "sum": 0,
                            "count": 0,
                            "max": float("-inf"),
                            "min": float("inf"),
                            "grades": []
                        }
                    
                    # Додаємо оцінку до статистики
                    grade_stats[item_name]["sum"] += grade_value
                    grade_stats[item_name]["count"] += 1
                    grade_stats[item_name]["max"] = max(grade_stats[item_name]["max"], grade_value)
                    grade_stats[item_name]["min"] = min(grade_stats[item_name]["min"], grade_value)
                    grade_stats[item_name]["grades"].append(grade_value)
            
            # Формуємо звіт
            if not grade_stats:
                return "Статистика оцінювання недоступна для цього курсу."
            
            report_lines = [f"Статистика оцінювання для курсу '{self.selected_course_name or self.selected_course}'"]
            report_lines.append("")
            
            for item_name, stats in grade_stats.items():
                if stats["count"] == 0:
                    continue
                
                avg_grade = stats["sum"] / stats["count"]
                
                # Медіана
                median = 0
                if stats["grades"]:
                    sorted_grades = sorted(stats["grades"])
                    n = len(sorted_grades)
                    if n % 2 == 0:
                        median = (sorted_grades[n//2 - 1] + sorted_grades[n//2]) / 2
                    else:
                        median = sorted_grades[n//2]
                
                report_lines.append(f"Елемент оцінювання: {item_name}")
                report_lines.append(f"Кількість оцінок: {stats['count']}")
                report_lines.append(f"Середня оцінка: {avg_grade:.2f}")
                report_lines.append(f"Медіана: {median:.2f}")
                report_lines.append(f"Максимальна оцінка: {stats['max']}")
                report_lines.append(f"Мінімальна оцінка: {stats['min']}")
                report_lines.append("")
            
            # Загальна статистика курсу
            total_grade_count = sum(stats["count"] for stats in grade_stats.values())
            total_grade_sum = sum(stats["sum"] for stats in grade_stats.values())
            avg_course_grade = total_grade_sum / total_grade_count if total_grade_count > 0 else 0
            
            report_lines.append("Загальна статистика курсу:")
            report_lines.append(f"Всього елементів оцінювання: {len(grade_stats)}")
            report_lines.append(f"Всього виставлених оцінок: {total_grade_count}")
            report_lines.append(f"Середня оцінка по курсу: {avg_course_grade:.2f}")
            
            return "\n".join(report_lines)
        except Exception as e:
            error_msg = f"Критична помилка при отриманні статистики оцінювання: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return error_msg
    
    async def generate_report(self, report_type: str) -> str:
        """Генерація звіту вибраного типу для курсу."""
        if not self.auth.token:
            return "Помилка: Не автентифіковано."
        if not self.selected_course:
            return "Будь ласка, спочатку виберіть курс."
        
        try:
            print(f"Генерація звіту типу '{report_type}' для курсу ID: {self.selected_course}")
            
            # Отримання базової інформації про курс
            course_name = self.selected_course_name or f"ID: {self.selected_course}"
            report_lines = [f"Звіт для курсу '{course_name}'"]
            report_lines.append(f"Тип звіту: {report_type}")
            report_lines.append(f"Дата створення: {self._get_current_datetime()}")
            report_lines.append("")
            
            # Генерація звіту в залежності від типу
            if report_type == "general" or report_type == "full":
                # Загальна інформація про курс
                success, course_data = await self.auth._call_api("core_course_get_courses", {
                    "options[ids][0]": self.selected_course
                })
                
                if success and course_data:
                    course = course_data[0]
                    report_lines.append("## Інформація про курс")
                    report_lines.append(f"Повна назва: {course.get('fullname', 'N/A')}")
                    report_lines.append(f"Коротка назва: {course.get('shortname', 'N/A')}")
                    report_lines.append(f"Категорія: {course.get('categoryname', 'N/A')}")
                    
                    # Кількість розділів і елементів
                    success_contents, contents_data = await self.auth._call_api("core_course_get_contents", {
                        "courseid": self.selected_course
                    })
                    
                    if success_contents:
                        section_count = len(contents_data)
                        module_count = sum(len(section.get("modules", [])) for section in contents_data)
                        
                        module_types = {}
                        for section in contents_data:
                            for module in section.get("modules", []):
                                mod_type = module.get("modname", "unknown")
                                if mod_type not in module_types:
                                    module_types[mod_type] = 0
                                module_types[mod_type] += 1
                        
                        report_lines.append(f"Кількість розділів: {section_count}")
                        report_lines.append(f"Кількість елементів: {module_count}")
                        report_lines.append("Типи елементів:")
                        for mod_type, count in module_types.items():
                            report_lines.append(f"- {mod_type}: {count}")
                    
                    # Кількість студентів
                    student_count = len(self.students) if self.students else "Не завантажено"
                    report_lines.append(f"Кількість студентів: {student_count}")
                    
                    report_lines.append("")
            
            if report_type == "activity" or report_type == "full":
                # Інформація про активність студентів
                activity_report = await self.analyze_student_activity()
                report_lines.append("## Активність студентів")
                report_lines.append(activity_report)
                report_lines.append("")
            
            if report_type == "assignments" or report_type == "full":
                # Інформація про завдання і статистика оцінювання
                report_lines.append("## Завдання та оцінювання")
                
                # Завантажуємо завдання, якщо ще не завантажені
                if not self.assignments:
                    await self.get_course_assignments()
                
                if self.assignments:
                    report_lines.append(f"Всього завдань: {len(self.assignments)}")
                    report_lines.append("Список завдань:")
                    for assignment in self.assignments:
                        report_lines.append(f"- {assignment.get('name')} (ID: {assignment.get('id')})")
                        report_lines.append(f"  Термін здачі: {assignment.get('duedate')}")
                        report_lines.append(f"  Зданих робіт: {assignment.get('submissions')}")
                else:
                    report_lines.append("Завдання не знайдені або не завантажені.")
                
                # Додаємо статистику оцінювання
                grades_stats = await self.get_grades_statistics()
                report_lines.append("")
                report_lines.append("### Статистика оцінювання")
                report_lines.append(grades_stats)
            
            return "\n".join(report_lines)
        except Exception as e:
            error_msg = f"Критична помилка при генерації звіту: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return error_msg
    
    async def create_course_section(self, section_name: str, section_desc: str) -> str:
        """Створення нового розділу в курсі."""
        if not self.auth.token:
            return "Помилка: Не автентифіковано."
        if not self.selected_course:
            return "Будь ласка, спочатку виберіть курс."
        if not section_name:
            return "Будь ласка, введіть назву розділу."
        
        try:
            print(f"Створення нового розділу '{section_name}' в курсі ID: {self.selected_course}")
            success, data = await self.auth._call_api("core_course_edit_section", {
                "courseid": self.selected_course,
                "sectionid": 0,  # 0 означає створення нового розділу
                "name": section_name,
                "summary": section_desc,
                "summaryformat": 1  # 1 означає HTML-формат
            })
            
            if success:
                section_id = data.get("sectionid")
                if section_id:
                    print(f"Розділ успішно створено! ID: {section_id}")
                    return f"Розділ '{section_name}' успішно створено! ID: {section_id}"
                else:
                    return "Розділ створено, але не вдалося отримати його ID."
            else:
                error_msg = f"Помилка API при створенні розділу: {data}"
                print(error_msg)
                if isinstance(data, dict) and data.get("message"):
                    return f"Помилка створення розділу: {data['message']}"
                return error_msg
        except Exception as e:
            error_msg = f"Критична помилка при створенні розділу: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return error_msg
    
    async def create_course_module(self, module_type: str, module_name: str, module_desc: str, section_id: int) -> str:
        """Створення нового елемента в розділі курсу."""
        if not self.auth.token:
            return "Помилка: Не автентифіковано."
        if not self.selected_course:
            return "Будь ласка, спочатку виберіть курс."
        if not module_name:
            return "Будь ласка, введіть назву елемента."
        if section_id is None:
            return "Будь ласка, вкажіть ID розділу."
        
        try:
            print(f"Створення нового елемента '{module_name}' типу '{module_type}' в розділі ID: {section_id}")
            
            # Різні типи модулів потребують різних API-викликів
            if module_type == "assign":
                # Створення завдання
                success, data = await self.auth._call_api("mod_assign_add_assignment", {
                    "coursemodule": 0,
                    "course": self.selected_course,
                    "name": module_name,
                    "intro": module_desc,
                    "introformat": 1,  # 1 = HTML
                    "duedate": 0,  # 0 = без терміну
                    "section": section_id,
                    "visible": 1,  # 1 = видимий
                    "grade": 100  # Максимальна оцінка
                })
            elif module_type == "resource":
                # Створення файла (потребує додаткового API для завантаження файлу)
                success, data = await self.auth._call_api("core_course_add_mod_resource", {
                    "coursemodule": 0,
                    "course": self.selected_course,
                    "name": module_name,
                    "intro": module_desc,
                    "introformat": 1,
                    "section": section_id,
                    "visible": 1
                })
            elif module_type == "page":
                # Створення сторінки
                success, data = await self.auth._call_api("core_course_add_mod_page", {
                    "coursemodule": 0,
                    "course": self.selected_course,
                    "name": module_name,
                    "intro": module_desc,
                    "introformat": 1,
                    "content": module_desc,
                    "contentformat": 1,
                    "section": section_id,
                    "visible": 1
                })
            elif module_type == "url":
                # Створення URL-посилання
                success, data = await self.auth._call_api("core_course_add_mod_url", {
                    "coursemodule": 0,
                    "course": self.selected_course,
                    "name": module_name,
                    "intro": module_desc,
                    "introformat": 1,
                    "externalurl": "https://example.com",  # Тут треба вказати реальну URL
                    "section": section_id,
                    "visible": 1
                })
            elif module_type == "forum":
                # Створення форуму
                success, data = await self.auth._call_api("core_course_add_mod_forum", {
                    "coursemodule": 0,
                    "course": self.selected_course,
                    "name": module_name,
                    "intro": module_desc,
                    "introformat": 1,
                    "section": section_id,
                    "visible": 1
                })
            else:
                return f"Непідтримуваний тип елемента: {module_type}"
            
            if success:
                module_id = data.get("moduleinfo", {}).get("id") or data.get("id")
                if module_id:
                    print(f"Елемент успішно створено! ID: {module_id}")
                    return f"Елемент '{module_name}' типу '{module_type}' успішно створено! ID: {module_id}"
                else:
                    return "Елемент створено, але не вдалося отримати його ID."
            else:
                error_msg = f"Помилка API при створенні елемента: {data}"
                print(error_msg)
                if isinstance(data, dict) and data.get("message"):
                    return f"Помилка створення елемента: {data['message']}"
                return error_msg
        except Exception as e:
            error_msg = f"Критична помилка при створенні елемента: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return error_msg
    
    async def init_provider_callback(self, provider_name: str) -> str:
        """Ініціалізація вибраного LLM провайдера."""
        try:
            print(f"Ініціалізація LLM провайдера: {provider_name}")
            self.llm_provider = await LLMProviderFactory.create_provider(provider_name)
            
            if self.llm_provider:
                return f"Провайдер '{provider_name}' успішно ініціалізовано."
            else:
                return f"Помилка: Не вдалося ініціалізувати провайдера '{provider_name}'. Перевірте налаштування API ключа."
        except Exception as e:
            error_msg = f"Помилка ініціалізації провайдера: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return error_msg
    
    async def send_message(self, message: str) -> Tuple[List[Tuple[str, str]], str]:
        """Відправка повідомлення до LLM та отримання відповіді."""
        if not message:
            return self.messages, ""
        
        if not self.llm_provider:
            try:
                print("Автоматична ініціалізація LLM провайдера (Claude)")
                self.llm_provider = await LLMProviderFactory.create_provider("claude")
                
                if not self.llm_provider:
                    self.messages.append((message, "Помилка: Не вдалося ініціалізувати LLM провайдера. Перевірте налаштування API ключа."))
                    return self.messages, ""
            except Exception as e:
                error_msg = f"Помилка ініціалізації LLM провайдера: {e}"
                print(error_msg)
                self.messages.append((message, f"Помилка ініціалізації LLM провайдера: {e}. Будь ласка, спочатку ініціалізуйте провайдера."))
                return self.messages, ""
        
        # Підготовка контексту
        context = {
            "user_id": self.auth.user_id,
            "user_role": "teacher",
            "mode": self.mode,
            "system_prompt": "Ви корисний асистент для викладача навчальної платформи Moodle. " +
                            f"Ви працюєте в режимі '{self.mode}'. " +
                            "У вас є прямий доступ до даних Moodle, включаючи інформацію про курс, студентів та завдання. " +
                            "Використовуйте ці дані для надання детальних і точних відповідей. " +
                            "Відповідайте українською мовою, якщо явно не зазначено інше."
        }
        
        if self.selected_course:
            # Отримання повної інформації про курс
            course_info = await self.get_course_info()
            context["course"] = {
                "id": self.selected_course,
                "name": self.selected_course_name,
                "info": course_info
            }
            
            # Отримання повної інформації про студентів
            students_data = await self.get_course_students()
            if students_data and "students" in students_data:
                # Обмежуємо до 50 студентів для запобігання перевищення контексту
                max_students = min(len(students_data["students"]), 50)
                context["students"] = students_data["students"][:max_students]
                context["student_count"] = len(students_data["students"])
            
            # Отримання інформації про завдання
            assignments_data = await self.get_course_assignments()
            if assignments_data and "assignments" in assignments_data:
                context["assignments"] = assignments_data["assignments"]
            
            # Отримання статистики оцінок
            grades_stats = await self.get_grades_statistics()
            if grades_stats:
                context["grades_statistics"] = grades_stats
        
        try:
            # Додаємо до історії перед отриманням відповіді, щоб показати повідомлення одразу
            self.messages.append((message, None))
            
            # Отримання відповіді від LLM
            response = await self.llm_provider.generate_response(message, context)
            
            # Оновлення останнього повідомлення в історії з відповіддю
            self.messages[-1] = (message, response)
            
            return self.messages, ""
        except Exception as e:
            error_msg = f"Помилка отримання відповіді: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            self.messages[-1] = (message, error_msg)
            return self.messages, ""
    
    def _get_current_datetime(self) -> str:
        """Отримання поточної дати і часу в читабельному форматі."""
        from datetime import datetime
        return datetime.now().strftime('%d.%m.%Y %H:%M:%S')
    
    # --- Методи для MCP сервера ---
    def start_mcp_server(self) -> Tuple[str, str]:
        """Запуск MCP сервера."""
        if MoodleMCPServer is None:
            return "Помилка: Модуль MCP сервера не знайдено.", ""
        if self.mcp_process and self.mcp_process.poll() is None:
            return "MCP сервер вже запущено", self._generate_mcp_config()
        
        try:
            server_script_path = os.path.join(os.path.dirname(__file__), "..", "mcp_server", "moodle_server.py")
            server_script_path = os.path.abspath(server_script_path)
            
            if not os.path.exists(server_script_path):
                return f"Помилка: Файл сервера не знайдено за шляхом {server_script_path}", ""
            
            print(f"Запуск MCP сервера зі скрипта: {server_script_path}")
            cmd = [sys.executable, server_script_path, "--base-url", self.moodle_url]
            
            self.mcp_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8'
            )
            
            if self.mcp_process.poll() is not None:
                stderr_output = self.mcp_process.stderr.read()
                error_msg = f"Помилка запуску MCP сервера. Код виходу: {self.mcp_process.returncode}. Помилка: {stderr_output}"
                print(error_msg)
                self.mcp_process = None
                return error_msg, ""
            
            print("MCP сервер успішно запущено (процес створено).")
            return "MCP сервер запущено", self._generate_mcp_config()
        
        except Exception as e:
            error_msg = f"Критична помилка запуску MCP сервера: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return error_msg, ""
    
    def stop_mcp_server(self) -> str:
        """Зупинка MCP сервера."""
        if self.mcp_process and self.mcp_process.poll() is None:
            print("Зупинка MCP сервера...")
            self.mcp_process.terminate()
            try:
                stdout, stderr = self.mcp_process.communicate(timeout=5)
                print("MCP сервер зупинено.")
                if stderr:
                    print(f"Помилки MCP сервера при зупинці: {stderr}")
                return "MCP сервер зупинено"
            except subprocess.TimeoutExpired:
                print("MCP сервер не відповів на terminate, примусова зупинка (kill)...")
                self.mcp_process.kill()
                stdout, stderr = self.mcp_process.communicate()
                print("MCP сервер примусово зупинено.")
                return "MCP сервер примусово зупинено"
            finally:
                self.mcp_process = None
        else:
            print("Спроба зупинити MCP сервер, але він не запущений.")
            return "MCP сервер не запущено"
    
    def _generate_mcp_config(self) -> str:
        """Генерація конфігурації для Claude Desktop."""
        server_script_path = os.path.join(os.path.dirname(__file__), "..", "mcp_server", "moodle_server.py")
        server_script_path = os.path.abspath(server_script_path)
        
        args = [server_script_path, "--base-url", self.moodle_url]
        
        config = {
            "mcpServers": {
                "moodle-assistant": {
                    "command": os.path.abspath(sys.executable),
                    "args": args
                }
            }
        }
        return json.dumps(config, indent=2)
    
    def update_mcp_config(self, config_json: str) -> str:
        """Оновлення конфігурації MCP сервера (збереження у файл)."""
        config_filename = "mcp_config_manual.json"
        try:
            loaded_config = json.loads(config_json)
            print(f"Збереження конфігурації MCP у файл: {config_filename}")
            with open(config_filename, "w", encoding='utf-8') as f:
                json.dump(loaded_config, f, indent=2, ensure_ascii=False)
            return f"Конфігурацію збережено у файл {config_filename}"
        except json.JSONDecodeError as e:
            error_msg = f"Помилка: Некоректний JSON формат конфігурації - {e}"
            print(error_msg)
            return error_msg
        except Exception as e:
            error_msg = f"Критична помилка збереження конфігурації MCP: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return error_msg