import gradio as gr
import asyncio
import os
import sys
import json
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

class StudentDashboard:
    """Клас для інтерфейсу студента."""
    
    def __init__(self, moodle_url: str = "http://78.137.2.119:2929"):
        self.moodle_url = moodle_url
        self.auth = MoodleAuth(moodle_url)
        self.llm_provider = None
        
        # Стан панелі
        self.courses = []
        self.selected_course = None
        self.selected_course_name = None
        self.assignments = []
        self.chat_history = []

        self.use_full_mcp_server = False  # За замовчуванням використовуємо прямий доступ
        
        # Константи для обмеження історії чату
        self.MAX_HISTORY_LENGTH = 50  # Максимальна кількість повідомлень у історії
        self.MAX_CONTEXT_MESSAGES = 10  # Максимальна кількість повідомлень для контексту LLM
    
    def build_ui(self) -> gr.Blocks:
        """Побудова інтерфейсу панелі студента."""
        with gr.Blocks(title="Moodle Асистент - Панель студента") as dashboard:
            gr.Markdown("# Moodle Асистент - Панель студента")
            
            with gr.Row():
                with gr.Column(scale=1):
                    # Блок інформації про користувача
                    with gr.Group() as user_info_group:
                        gr.Markdown("### Інформація про студента")
                        user_info_output = gr.Textbox(label="Профіль", interactive=False, lines=6, value="Завантаження...")
                        
                        # Оновлюємо інформацію тільки після успішної автентифікації
                        if self.auth.authenticated and self.auth.token and self.auth.user_id:
                            asyncio.create_task(self.update_user_info(user_info_output))
                        else:
                            auth_error_msg = "Очікування автентифікації..."
                            user_info_output.value = auth_error_msg
                            print(auth_error_msg)
                    
                    # Блок курсів
                    with gr.Group() as courses_group:
                        gr.Markdown("### Мої курси")
                        refresh_courses_button = gr.Button("Оновити список курсів")
                        courses_dropdown = gr.Dropdown(label="Виберіть курс", choices=[("Завантаження...", None)], interactive=False)
                        
                        # Завантажуємо курси, якщо є токен
                        if self.auth.token and self.auth.user_id:
                            asyncio.create_task(self.load_courses(courses_dropdown))
                
                with gr.Column(scale=2):
                    with gr.Tabs() as tabs:
                        # Вкладка інформації про курс
                        with gr.Tab("Інформація про курс"):
                            course_info_button = gr.Button("Отримати інформацію про курс")
                            course_info_output = gr.Textbox(label="Інформація про курс", interactive=False, lines=10)
                        
                        # Вкладка вмісту курсу
                        with gr.Tab("Вміст курсу"):
                            content_button = gr.Button("Отримати вміст курсу")
                            content_output = gr.Textbox(label="Вміст курсу", interactive=False, lines=15)
                        
                        # Вкладка завдань
                        with gr.Tab("Мої завдання"):
                            assignments_button = gr.Button("Отримати список завдань")
                            assignments_table = gr.Dataframe(
                                headers=["ID", "Назва", "Термін здачі", "Статус"],
                                datatype=["number", "str", "str", "str"],
                                label="Завдання курсу"
                            )
                            
                            # Деталі вибраного завдання
                            assignment_id_input = gr.Number(label="ID завдання")
                            get_assignment_details_button = gr.Button("Отримати деталі завдання")
                            assignment_details_output = gr.Textbox(label="Деталі завдання", interactive=False, lines=10)
                        
                        # Вкладка AI асистента
                        with gr.Tab("AI Асистент"):
                            gr.Markdown("### Спілкування з AI Асистентом")
                            
                            # Історія чату
                            chat_history_output = gr.Chatbot(label="Історія чату", height=400)
                            
                            # Вибір режиму інтеграції з MCP
                            with gr.Row():
                                gr.Markdown("#### Режим інтеграції з даними:")
                                mcp_mode_selector = gr.Radio(
                                    choices=["Прямий доступ до Moodle API", "Повний MCP сервер"],
                                    value="Прямий доступ до Moodle API",
                                    label="Режим взаємодії з Moodle",
                                    info="Оберіть, як AI Асистент отримує дані з Moodle"
                                )
                                mcp_status = gr.Textbox(label="Статус MCP сервера", interactive=False)

                            # Кнопки керування MCP сервером, видимі тільки в режимі повного MCP сервера
                            with gr.Row(visible=False) as mcp_controls:
                                start_mcp_button = gr.Button("Запустити MCP сервер")
                                stop_mcp_button = gr.Button("Зупинити MCP сервер")

                            # Введення та відправка
                            with gr.Row():
                                chat_input = gr.Textbox(label="Задайте питання", lines=2, placeholder="Наприклад: поясни мені тему цього курсу")
                                send_button = gr.Button("Відправити")
                            
                            # Очищення історії чату
                            clear_chat_button = gr.Button("Очистити історію")
                            
                            # Вибір провайдера
                            with gr.Accordion("Налаштування AI", open=False):
                                provider_dropdown = gr.Dropdown(
                                    label="LLM Провайдер",
                                    choices=[("Claude (Anthropic)", "claude")],
                                    value="claude"
                                )
                                
                                init_provider_button = gr.Button("Ініціалізувати провайдера")
                                provider_status = gr.Textbox(label="Статус провайдера", interactive=False)
            
            # Обробники подій
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
            
            content_button.click(
                fn=self.get_course_content,
                inputs=[],
                outputs=[content_output]
            )
            
            assignments_button.click(
                fn=self.get_assignments,
                inputs=[],
                outputs=[assignments_table]
            )
            
            get_assignment_details_button.click(
                fn=self.get_assignment_details,
                inputs=[assignment_id_input],
                outputs=[assignment_details_output]
            )
            
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
            
            clear_chat_button.click(
                fn=self.clear_chat_history,
                inputs=[],
                outputs=[chat_history_output]
            )

            mcp_mode_selector.change(
                fn=self.switch_mcp_mode,
                inputs=[mcp_mode_selector],
                outputs=[mcp_controls, mcp_status]
            )

            start_mcp_button.click(
                fn=self.start_mcp_server,
                inputs=[],
                outputs=[mcp_status]
            )

            stop_mcp_button.click(
                fn=self.stop_mcp_server,
                inputs=[],
                outputs=[mcp_status]
            )
        
        return dashboard
    
    async def update_user_info(self, info_output_component: gr.Textbox) -> None:
        """Оновлення інформації про користувача."""
        if not self.auth.token or not self.auth.user_id:
            await asyncio.sleep(0)
            # Пряме присвоєння значення замість update
            info_output_component.value = "Помилка: Не вдалося отримати інформацію (проблема автентифікації)."
            return
        
        try:
            print("Оновлення інформації про студента...")
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
                    f"Роль: Студент"
                ]
                # Пряме присвоєння значення замість update
                info_output_component.value = "\n".join(info)
                print("Інформація про студента оновлена.")
            else:
                error_msg = f"Не вдалося отримати дані користувача: {data if not success else 'Порожня відповідь'}"
                print(error_msg)
                # Пряме присвоєння значення замість update
                info_output_component.value = error_msg
        except Exception as e:
            error_msg = f"Критична помилка при оновленні інфо студента: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            # Пряме присвоєння значення замість update
            info_output_component.value = error_msg
    
    async def load_courses(self, dropdown_component: gr.Dropdown) -> None:
        """Завантаження курсів для випадаючого списку."""
        if not self.auth.token or not self.auth.user_id:
            await asyncio.sleep(0)
            # Пряме присвоєння властивостей замість update
            dropdown_component.choices = [("Помилка автентифікації", None)]
            dropdown_component.value = None
            dropdown_component.interactive = False
            return
        
        try:
            print("Завантаження курсів для студента...")
            success, data = await self.auth._call_api("core_enrol_get_users_courses", {
                "userid": self.auth.user_id
            })
            
            if success:
                self.courses = data
                courses_list = [(f"{course.get('fullname', 'Без назви')} (ID: {course.get('id', 'N/A')})", course.get('id'))
                               for course in data if course.get('id')]
                
                if not courses_list:
                    # Пряме присвоєння властивостей замість update
                    dropdown_component.choices = [("Курси не знайдено", None)]
                    dropdown_component.value = None
                    dropdown_component.interactive = False
                else:
                    # Пряме присвоєння властивостей замість update
                    dropdown_component.choices = courses_list
                    dropdown_component.value = None
                    dropdown_component.interactive = True
                print(f"Курси для студента завантажено: {len(courses_list)}")
            else:
                error_msg = f"Помилка API при завантаженні курсів: {data}"
                print(error_msg)
                # Пряме присвоєння властивостей замість update
                dropdown_component.choices = [(error_msg, None)]
                dropdown_component.value = None
                dropdown_component.interactive = False
        except Exception as e:
            error_msg = f"Критична помилка при завантаженні курсів: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            # Пряме присвоєння властивостей замість update
            dropdown_component.choices = [(error_msg, None)]
            dropdown_component.value = None
            dropdown_component.interactive = False
    
    async def load_courses_callback(self) -> Dict:
        """Завантаження курсів при натисканні кнопки оновлення (повертає оновлення для Gradio)."""
        if not self.auth.token or not self.auth.user_id:
            return gr.update(choices=[("Помилка автентифікації", None)], value=None, interactive=False)
        
        try:
            print("Оновлення списку курсів для студента...")
            success, data = await self.auth._call_api("core_enrol_get_users_courses", {
                "userid": self.auth.user_id
            })
            
            if success:
                self.courses = data
                courses_list = [(f"{course.get('fullname', 'Без назви')} (ID: {course.get('id', 'N/A')})", course.get('id'))
                               for course in data if course.get('id')]
                
                if not courses_list:
                    return gr.update(choices=[("Курси не знайдено", None)], value=None, interactive=False)
                else:
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
        print(f"Студент обрав курс ID: {self.selected_course}")
        
        if self.selected_course:
            for course in self.courses:
                if course.get('id') == self.selected_course:
                    self.selected_course_name = course.get('fullname', 'Ім\'я не знайдено')
                    print(f"Знайдено ім'я курсу: {self.selected_course_name}")
                    break
    
    async def get_course_info(self) -> str:
        """Отримання інформації про вибраний курс."""
        if not self.auth.token:
            return "Помилка: Не автентифіковано."
        if not self.selected_course:
            return "Будь ласка, спочатку виберіть курс зі списку."
        
        try:
            print(f"Отримання інформації для курсу ID: {self.selected_course}")
            success, data = await self.auth._call_api("core_course_get_courses", {
                "options[ids][0]": self.selected_course
            })
            
            if success and data:
                course = data[0]
                info = [
                    f"ID курсу: {course.get('id', 'N/A')}",
                    f"Повна назва: {course.get('fullname', 'N/A')}",
                    f"Коротка назва: {course.get('shortname', 'N/A')}",
                    f"Категорія: {course.get('categoryname', 'N/A')}",
                    f"Опис: {course.get('summary', 'Опис відсутній')}",
                    f"Дата початку: {self._format_timestamp(course.get('startdate'))}",
                    f"Дата закінчення: {self._format_timestamp(course.get('enddate'))}"
                ]
                return "\n".join(info)
            else:
                return f"Помилка отримання інформації про курс: {data}"
        except Exception as e:
            error_msg = f"Критична помилка при отриманні інформації про курс: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return error_msg
    
    async def get_course_content(self) -> str:
        """Отримання вмісту вибраного курсу."""
        if not self.auth.token:
            return "Помилка: Не автентифіковано."
        if not self.selected_course:
            return "Будь ласка, спочатку виберіть курс зі списку."
        
        try:
            print(f"Отримання вмісту для курсу ID: {self.selected_course}")
            success, data = await self.auth._call_api("core_course_get_contents", {
                "courseid": self.selected_course
            })
            
            if success:
                if not data:
                    return f"Вміст курсу '{self.selected_course_name or self.selected_course}' не знайдено або курс порожній."
                
                sections = []
                for section in data:
                    section_info = f"Розділ: {section.get('name', 'Без назви')}"
                    modules = []
                    for module in section.get("modules", []):
                        module_info = f"  - {module.get('name', 'Без назви')} (Тип: {module.get('modname', 'N/A')})"
                        if module.get('modname') == 'assign':
                            module_info += f", ID: {module.get('instance')}"
                        modules.append(module_info)
                    
                    if modules:
                        section_info += "\n" + "\n".join(modules)
                    else:
                        section_info += "\n  (Розділ порожній)"
                    
                    sections.append(section_info)
                
                return "\n\n".join(sections)
            else:
                return f"Помилка отримання вмісту курсу: {data}"
        except Exception as e:
            error_msg = f"Критична помилка при отриманні вмісту курсу: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return error_msg
    
    async def get_assignments(self) -> Dict:
        """Отримання завдань для вибраного курсу (повертає оновлення для Dataframe)."""
        if not self.auth.token:
            return gr.update(value=[["Помилка автентифікації", "", "", ""]])
        if not self.selected_course:
            gr.Warning("Будь ласка, спочатку виберіть курс.")
            return gr.update(value=None)
        
        try:
            print(f"Отримання завдань для курсу ID: {self.selected_course}")
            success, data = await self.auth._call_api("mod_assign_get_assignments", {
                "courseids[0]": self.selected_course
            })
            
            if success and "courses" in data:
                assignments_list = []
                self.assignments = []
                
                for course in data["courses"]:
                    if str(course.get('id')) == str(self.selected_course):
                        for assignment in course.get("assignments", []):
                            assignment_id = assignment.get("id")
                            if not assignment_id:
                                continue
                            
                            # Отримання статусу здачі
                            status = await self._get_assignment_status(assignment_id)
                            
                            due_date = self._format_timestamp(assignment.get("duedate"))
                            
                            # Зберігаємо повні дані
                            self.assignments.append(assignment)
                            
                            # Дані для таблиці
                            assignments_list.append([
                                assignment_id,
                                assignment.get("name", "Без назви"),
                                due_date,
                                status
                            ])
                
                if not assignments_list:
                    return gr.update(value=[["Завдання не знайдено", "", "", ""]])
                
                return gr.update(value=assignments_list)
            else:
                return gr.update(value=[["Помилка отримання завдань", "", "", ""]])
        except Exception as e:
            error_msg = f"Критична помилка при отриманні завдань: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            return gr.update(value=[[error_msg, "", "", ""]])
    
    async def _get_assignment_status(self, assignment_id: int) -> str:
        """Отримання статусу завдання для поточного користувача."""
        try:
            success, data = await self.auth._call_api("mod_assign_get_submission_status", {
                "assignid": assignment_id
            })
            
            if success:
                status = "Не здано"
                if "laststatus" in data:
                    last_status = data.get("laststatus")
                    if last_status == "submitted":
                        status = "Здано"
                    elif last_status == "draft":
                        status = "Чернетка"
                    else:
                        status = last_status
                return status
            else:
                return "Невідомо"
        except Exception as e:
            print(f"Помилка отримання статусу завдання {assignment_id}: {e}")
            return "Помилка"
    
    async def get_assignment_details(self, assignment_id: Optional[int]) -> str:
        """Отримання деталей завдання."""
        if not self.auth.token:
            return "Помилка: Не автентифіковано."
        if not assignment_id:
            return "Будь ласка, введіть ID завдання."
        
        try:
            print(f"Отримання деталей завдання ID: {assignment_id}")
            success, data = await self.auth._call_api("mod_assign_get_assignment", {
                "assignmentid": assignment_id
            })
            
            if success and "assignment" in data:
                assignment = data["assignment"]
                
                # Отримання статусу здачі
                status = await self._get_assignment_status(assignment_id)
                
                details = [
                    f"Назва: {assignment.get('name', 'Без назви')}",
                    f"ID: {assignment.get('id', 'N/A')}",
                    f"Опис: {assignment.get('intro', 'Опис відсутній')}",
                    f"Максимальна оцінка: {assignment.get('grade', 'N/A')}",
                    f"Термін здачі: {self._format_timestamp(assignment.get('duedate'))}",
                    f"Ваш статус: {status}"
                ]
                return "\n".join(details)
            else:
                return f"Помилка отримання деталей завдання: {data}"
        except Exception as e:
            error_msg = f"Критична помилка при отриманні деталей завдання: {e}"
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
    
    def clear_chat_history(self) -> List[Tuple[str, str]]:
        """Очищення історії чату."""
        self.chat_history = []
        return self.chat_history
    
    async def send_message(self, message: str) -> Tuple[List[Tuple[str, str]], str]:
        """Відправка повідомлення до LLM та отримання відповіді."""
        if not message or message.strip() == "":
            return self.chat_history, ""
        
        # Автоматична ініціалізація LLM провайдера, якщо потрібно
        if not self.llm_provider:
            try:
                print("Автоматична ініціалізація LLM провайдера (Claude)")
                self.llm_provider = await LLMProviderFactory.create_provider("claude")
                
                if not self.llm_provider:
                    error_msg = "Помилка: Не вдалося ініціалізувати LLM провайдера. Перевірте налаштування API ключа."
                    print(error_msg)
                    self.chat_history.append((message, error_msg))
                    return self.chat_history, ""
            except Exception as e:
                error_msg = f"Помилка ініціалізації LLM провайдера: {e}"
                print(error_msg)
                self.chat_history.append((message, f"Помилка ініціалізації LLM провайдера: {e}. Будь ласка, спочатку ініціалізуйте провайдера."))
                return self.chat_history, ""
        
        # Підготовка контексту
        context = {
            "user_id": self.auth.user_id,
            "user_role": "student",
            "mode": "chat",
            "system_prompt": "Ви корисний асистент для навчальної платформи Moodle, що допомагає студенту. Надавайте пояснення, рекомендації для навчання та допомогу в розумінні матеріалів курсу. Не надавайте готових відповідей на завдання чи тести. Відповідайте українською мовою, якщо явно не зазначено інше."
        }
        
        # Додавання інформації про курс, якщо він вибраний
        if self.selected_course:
            context["course"] = {
                "id": self.selected_course,
                "name": self.selected_course_name
            }
            
            # Отримання інформації про курс
            try:
                success, course_info = await self.auth._call_api("core_course_get_courses", {
                    "options[ids][0]": self.selected_course
                })
                if success and course_info:
                    context["course_info"] = course_info[0]
            except Exception as e:
                print(f"Помилка отримання інформації про курс: {e}")
            
            # Отримання завдань курсу
            try:
                success, assignments = await self.auth._call_api("mod_assign_get_assignments", {
                    "courseids[0]": self.selected_course
                })
                if success and assignments:
                    context["assignments"] = assignments.get("courses", [{}])[0].get("assignments", [])
            except Exception as e:
                print(f"Помилка отримання завдань курсу: {e}")
            
            # Отримання вмісту курсу
            try:
                success, content = await self.auth._call_api("core_course_get_contents", {
                    "courseid": self.selected_course
                })
                if success and content:
                    context["course_content"] = content
            except Exception as e:
                print(f"Помилка отримання вмісту курсу: {e}")
        
        try:
            # Додаємо до історії перед отриманням відповіді з тимчасовим повідомленням
            tmp_msg = "Очікування відповіді..."
            self.chat_history.append((message, tmp_msg))
            
            # Формування повідомлень з історії для Claude
            messages = []
            # Беремо останні повідомлення для контексту, пропускаючи поточне тимчасове
            for idx, (user_msg, assistant_msg) in enumerate(self.chat_history[:-1]):
                if len(self.chat_history) - idx <= self.MAX_CONTEXT_MESSAGES:
                    if user_msg and user_msg.strip():
                        messages.append({"role": "user", "content": user_msg})
                    if assistant_msg and assistant_msg.strip() and assistant_msg != tmp_msg:
                        messages.append({"role": "assistant", "content": assistant_msg})
            
            # Додавання поточного повідомлення
            messages.append({"role": "user", "content": message})
            
            # Додавання історії чату до контексту
            context["messages"] = messages
            context["chat_history"] = messages  # Дублюємо для сумісності
            
            # Додавання MCP параметрів для використання MCP функцій
            context["use_mcp"] = True
            context["mcp_server_url"] = self.moodle_url
            context["mcp_token"] = self.auth.token
            
            # Отримання відповіді від LLM з використанням історії
            print(f"Відправка запиту до Claude з {len(messages)} повідомленнями в історії")
            
            # Отримання відповіді від LLM 
            response = await self.llm_provider.generate_response(
                message, 
                context,
                use_mcp=True,  # Дозволяємо використання MCP
                mcp_server_url="auto" if self.use_full_mcp_server else self.moodle_url,
                mcp_token=self.auth.token,
                use_full_mcp_server=self.use_full_mcp_server
            )
            
            # Оновлення останнього повідомлення в історії з відповіддю
            if self.chat_history:
                self.chat_history[-1] = (message, response)
            
            # Обмеження довжини історії чату
            if len(self.chat_history) > self.MAX_HISTORY_LENGTH:
                self.chat_history = self.chat_history[-self.MAX_HISTORY_LENGTH:]
            
            return self.chat_history, ""
        except Exception as e:
            error_msg = f"Помилка отримання відповіді: {e}"
            print(error_msg)
            import traceback
            traceback.print_exc()
            
            # Оновлення останнього повідомлення з повідомленням про помилку
            if self.chat_history and self.chat_history[-1][0] == message:
                self.chat_history[-1] = (message, error_msg)
            else:
                self.chat_history.append((message, error_msg))
            
            return self.chat_history, ""
    
    def _format_timestamp(self, timestamp: Optional[int]) -> str:
        """Форматування Unix-timestamp у читабельну дату."""
        if not timestamp:
            return "Не вказано"
        
        from datetime import datetime
        try:
            return datetime.fromtimestamp(timestamp).strftime('%d.%m.%Y %H:%M')
        except Exception:
            return f"Timestamp: {timestamp}"
        
    def switch_mcp_mode(self, mode: str) -> Tuple[Dict, str]:
        """Перемикання режиму інтеграції з MCP."""
        if mode == "Повний MCP сервер":
            self.use_full_mcp_server = True
            return gr.update(visible=True), "MCP сервер не запущено. Натисніть кнопку 'Запустити MCP сервер'."
        else:
            self.use_full_mcp_server = False
            # Зупиняємо MCP сервер, якщо він запущений
            if self.llm_provider:
                try:
                    status = self.llm_provider.stop_mcp_server()
                    return gr.update(visible=False), f"Режим прямого доступу активовано. {status}"
                except Exception as e:
                    return gr.update(visible=False), f"Режим прямого доступу активовано. Помилка при зупинці MCP сервера: {e}"
            return gr.update(visible=False), "Режим прямого доступу активовано."

    async def start_mcp_server(self) -> str:
        """Запуск MCP сервера."""
        if not self.llm_provider:
            try:
                self.llm_provider = await LLMProviderFactory.create_provider("claude")
            except Exception as e:
                return f"Помилка ініціалізації LLM провайдера: {e}"
        
        try:
            success, message, _ = await self.llm_provider.start_mcp_server(self.moodle_url)
            return message
        except Exception as e:
            return f"Помилка запуску MCP сервера: {e}"

    def stop_mcp_server(self) -> str:
        """Зупинка MCP сервера."""
        if not self.llm_provider:
            return "LLM провайдер не ініціалізовано."
        
        try:
            status = self.llm_provider.stop_mcp_server()
            return status
        except Exception as e:
            return f"Помилка зупинки MCP сервера: {e}"