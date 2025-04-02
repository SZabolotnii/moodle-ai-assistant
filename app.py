"""
Головний модуль Moodle AI Assistant.
Забезпечує взаємодію з Moodle через Gradio інтерфейс.
"""
import gradio as gr
import asyncio
import os
import sys
from dotenv import load_dotenv

# Завантажуємо змінні оточення на старті додатку
load_dotenv()

# Імпортуємо необхідні модулі
from common.auth import MoodleAuth
from teacher.dashboard import TeacherDashboard
from student.dashboard import StudentDashboard

# Клас для зберігання глобального стану додатку
class AppState:
    def __init__(self):
        self.mode = None  # Режим роботи: "teacher" або "student"
        self.moodle_url = os.getenv("MOODLE_URL", "http://78.137.2.119:2929")
        
        # Створюємо об'єкти для режимів роботи
        self.teacher_dashboard = TeacherDashboard(moodle_url=self.moodle_url)
        self.student_dashboard = StudentDashboard(moodle_url=self.moodle_url)

# Створення глобального стану
app_state = AppState()

# Функція для переходу в режим викладача
async def switch_to_teacher_mode_async():
    """
    Перемикання в режим викладача.
    """
    app_state.mode = "teacher"
    auth = app_state.teacher_dashboard.auth  # Отримуємо об'єкт auth
    
    if not auth.token:
        error_message = "Помилка: API токен Moodle не знайдено. Перевірте файл .env (API_MOODLE_TOKEN)."
        print(error_message)
        return (
            gr.update(visible=True),   # mode_selection
            gr.update(visible=False),  # student_mode
            gr.update(visible=False),  # teacher_dashboard
            gr.update(value=error_message, visible=True)  # status_message
        )
    
    print("Спроба автентифікації за токеном...")
    success, message = await auth.authenticate_with_token()
    
    if success:
        print(f"Автентифікація успішна. User ID: {auth.user_id}, Is Teacher: {auth.is_teacher}")
        if not auth.is_teacher:
            warning_message = "Попередження: Акаунт, пов'язаний з токеном, не має прав викладача в жодному курсі."
            print(warning_message)
            return (
                gr.update(visible=False),  # mode_selection
                gr.update(visible=False),  # student_mode
                gr.update(visible=True),   # teacher_dashboard
                gr.update(value=warning_message, visible=True)  # status_message
            )
        else:
            # Успіх і є викладачем
            return (
                gr.update(visible=False),  # mode_selection
                gr.update(visible=False),  # student_mode
                gr.update(visible=True),   # teacher_dashboard
                gr.update(value="Автентифікація за токеном успішна.", visible=False)  # status_message
            )
    else:
        # Помилка автентифікації
        error_message = f"Помилка автентифікації за токеном: {message}"
        print(error_message)
        return (
            gr.update(visible=True),   # mode_selection
            gr.update(visible=False),  # student_mode
            gr.update(visible=False),  # teacher_dashboard
            gr.update(value=error_message, visible=True)  # status_message
        )

# Функція для переходу в режим студента
async def switch_to_student_mode_async():
    """
    Перемикання в режим студента.
    """
    app_state.mode = "student"
    auth = app_state.student_dashboard.auth  # Отримуємо об'єкт auth
    
    if not auth.token:
        error_message = "Помилка: API токен Moodle не знайдено. Перевірте файл .env (API_MOODLE_TOKEN)."
        print(error_message)
        return (
            gr.update(visible=True),   # mode_selection
            gr.update(visible=False),  # student_mode
            gr.update(visible=False),  # teacher_dashboard
            gr.update(value=error_message, visible=True)  # status_message
        )
    
    print("Спроба автентифікації за токеном (режим студента)...")
    success, message = await auth.authenticate_with_token()
    
    if success:
        print(f"Автентифікація успішна. User ID: {auth.user_id}")
        return (
            gr.update(visible=False),  # mode_selection
            gr.update(visible=True),   # student_mode
            gr.update(visible=False),  # teacher_dashboard
            gr.update(visible=False)   # status_message
        )
    else:
        # Помилка автентифікації
        error_message = f"Помилка автентифікації за токеном: {message}"
        print(error_message)
        return (
            gr.update(visible=True),   # mode_selection
            gr.update(visible=False),  # student_mode
            gr.update(visible=False),  # teacher_dashboard
            gr.update(value=error_message, visible=True)  # status_message
        )

# Функція для повернення до вибору режиму
def back_to_selection():
    """
    Повернення до вибору режиму.
    """
    app_state.mode = None
    return (
        gr.update(visible=True),   # mode_selection
        gr.update(visible=False),  # student_mode
        gr.update(visible=False),  # teacher_dashboard
        gr.update(visible=False)   # status_message
    )

# Головна функція для створення інтерфейсу
def create_interface():
    """
    Створення головного інтерфейсу додатку.
    """
    with gr.Blocks(title="Moodle AI Асистент", theme=gr.themes.Soft(), css="footer {visibility: hidden}") as demo:
        # Вибір режиму
        with gr.Group(visible=True) as mode_selection:
            gr.Markdown("# Moodle AI Асистент")
            gr.Markdown("Виберіть режим роботи:")
            
            with gr.Row():
                teacher_btn = gr.Button("Режим викладача", variant="primary")
                student_btn = gr.Button("Режим студента", variant="primary")
            
            # Поле для виводу статусу/помилок
            status_message = gr.Textbox(label="Статус", interactive=False, visible=False)
        
        # Режим студента
        with gr.Group(visible=False) as student_mode:
            # Завантажуємо інтерфейс студента
            app_state.student_dashboard.build_ui()
            # Кнопка повернення
            back_to_modes_btn1 = gr.Button("Повернутися до вибору режиму")
        
        # Режим викладача
        with gr.Group(visible=False) as teacher_dashboard:
            # Завантажуємо інтерфейс викладача
            app_state.teacher_dashboard.build_ui()
            # Кнопка повернення
            back_to_modes_btn2 = gr.Button("Повернутися до вибору режиму")
        
        # Логіка кнопок
        teacher_btn.click(
            fn=switch_to_teacher_mode_async,
            inputs=[],
            outputs=[mode_selection, student_mode, teacher_dashboard, status_message]
        )
        
        student_btn.click(
            fn=switch_to_student_mode_async,
            inputs=[],
            outputs=[mode_selection, student_mode, teacher_dashboard, status_message]
        )
        
        # Кнопки повернення
        back_to_modes_btn1.click(
            fn=back_to_selection,
            inputs=[],
            outputs=[mode_selection, student_mode, teacher_dashboard, status_message]
        )
        
        back_to_modes_btn2.click(
            fn=back_to_selection,
            inputs=[],
            outputs=[mode_selection, student_mode, teacher_dashboard, status_message]
        )
    
    return demo

# Запуск додатку
if __name__ == "__main__":
    # Перевірка наявності токена перед запуском
    moodle_token = os.getenv("API_MOODLE_TOKEN")
    if not moodle_token:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("!!! ПОПЕРЕДЖЕННЯ: Змінна оточення API_MOODLE_TOKEN не знайдена!")
        print("!!! Додайте токен у файл .env для роботи з Moodle.           !")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    else:
        print(f"Знайдено API_MOODLE_TOKEN (останні 6 символів): ...{moodle_token[-6:]}")
    
    # Перевірка наявності ключа Claude
    claude_key = os.getenv("ANTHROPIC_API_KEY")
    if not claude_key:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("!!! ПОПЕРЕДЖЕННЯ: Змінна оточення ANTHROPIC_API_KEY не знайдена!")
        print("!!! Додайте ключ у файл .env для роботи з Claude.            !")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    else:
        print(f"Знайдено ANTHROPIC_API_KEY (останні 6 символів): ...{claude_key[-6:]}")
    
    print("Створення інтерфейсу Gradio...")
    demo = create_interface()
    print("Запуск інтерфейсу Gradio...")
    # share=True для публічного доступу (опціонально)
    demo.launch(share=False)
    print("Додаток Gradio запущено.")