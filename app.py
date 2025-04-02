import gradio as gr
import asyncio
import os
# Видаляємо імпорт json, якщо він більше не потрібен тут
from teacher.dashboard import TeacherDashboard
# Імпортуємо клас MoodleAuth для type hinting (опціонально, але корисно)
from common.auth import MoodleAuth
from dotenv import load_dotenv # Додаємо імпорт dotenv

# Завантажуємо змінні оточення на старті додатку
load_dotenv()

# Створюємо глобальний стан програми
class AppState:
    def __init__(self):
        self.mode = None
        # Ініціалізація TeacherDashboard автоматично створить MoodleAuth,
        # який спробує завантажити токен з .env
        self.teacher_dashboard = TeacherDashboard(moodle_url="http://78.137.2.119:2929")

app_state = AppState()

# Функція для переходу до режиму викладача (тепер асинхронна)
async def switch_to_teacher_mode_async():
    """
    Намагається автентифікуватися за допомогою токена і переключити інтерфейс.
    """
    auth: MoodleAuth = app_state.teacher_dashboard.auth # Отримуємо об'єкт auth

    if not auth.token:
        error_message = "Помилка: API токен Moodle не знайдено. Перевірте файл .env (API_MOODLE_TOKEN)."
        print(error_message)
        # Показуємо помилку в інтерфейсі та залишаємось на виборі режиму
        return (
            gr.update(visible=True),  # mode_selection
            gr.update(visible=False), # student_mode
            gr.update(visible=False), # teacher_dashboard
            gr.update(value=error_message, visible=True) # status_message
        )

    print("Спроба автентифікації за токеном...")
    success, message = await auth.authenticate_with_token()

    if success:
        print(f"Автентифікація успішна. User ID: {auth.user_id}, Is Teacher: {auth.is_teacher}")
        if not auth.is_teacher:
             # Хоча ми не логінились, перевірка ролі все одно важлива
             warning_message = "Попередження: Акаунт, пов'язаний з токеном, не має прав викладача в жодному курсі."
             print(warning_message)
             # Можна або продовжити з попередженням, або заблокувати доступ
             # Покажемо дашборд, але виведемо попередження
             return (
                gr.update(visible=False), # mode_selection
                gr.update(visible=False), # student_mode
                gr.update(visible=True),  # teacher_dashboard
                gr.update(value=warning_message, visible=True) # status_message
             )
        else:
            # Успіх і є викладачем
            return (
                gr.update(visible=False), # mode_selection
                gr.update(visible=False), # student_mode
                gr.update(visible=True),  # teacher_dashboard
                gr.update(value="Автентифікація за токеном успішна.", visible=False) # status_message (можна приховати)
            )
    else:
        # Помилка автентифікації токеном (невалідний, помилка API тощо)
        error_message = f"Помилка автентифікації за токеном: {message}"
        print(error_message)
        # Показуємо помилку і залишаємось на виборі режиму
        return (
            gr.update(visible=True),  # mode_selection
            gr.update(visible=False), # student_mode
            gr.update(visible=False), # teacher_dashboard
            gr.update(value=error_message, visible=True) # status_message
        )


# Функція для переходу до режиму студента (без змін)
def switch_to_student_mode():
    app_state.mode = "student"
    return (
        gr.update(visible=False), # mode_selection
        gr.update(visible=True),  # student_mode
        gr.update(visible=False), # teacher_dashboard
        gr.update(visible=False)  # status_message (приховуємо, якщо була помилка)
    )

# Функція для повернення до вибору режиму (без змін)
def back_to_selection():
    app_state.mode = None
    return (
        gr.update(visible=True),  # mode_selection
        gr.update(visible=False), # student_mode
        gr.update(visible=False), # teacher_dashboard
        gr.update(visible=False)  # status_message (приховуємо)
    )

# Функція для входу викладача (teacher_login) БІЛЬШЕ НЕ ПОТРІБНА, ВИДАЛЯЄМО
# async def teacher_login(username, password):
#    ... (старий код) ...

# Функція для перевірки статусу входу (check_login_status) БІЛЬШЕ НЕ ПОТРІБНА, ВИДАЛЯЄМО
# def check_login_status(status):
#    ... (старий код) ...


# Головна функція для створення інтерфейсу
def create_interface():
    # Важливо: Переконайтеся, що TeacherDashboard правильно ініціалізує MoodleAuth,
    # який в свою чергу завантажує токен з .env
    # Якщо TeacherDashboard очікує вже автентифікований об'єкт,
    # то логіку ініціалізації можливо доведеться трохи змінити.
    # Припускаємо, що поточна ініціалізація в AppState працює.

    with gr.Blocks(title="Moodle AI Асистент", theme=gr.themes.Soft(), css="footer {visibility: hidden}") as demo:
        # Створюємо всі групи інтерфейсу

        # Вибір режиму
        with gr.Group(visible=True) as mode_selection:
            gr.Markdown("# Moodle Асистент")
            gr.Markdown("Виберіть режим роботи:")

            with gr.Row():
                teacher_btn = gr.Button("Режим викладача", variant="primary")
                student_btn = gr.Button("Режим студента", variant="primary")

            # Додаємо поле для виводу статусу/помилок автентифікації токеном
            status_message = gr.Textbox(label="Статус", interactive=False, visible=False)

        # Форма входу викладача (teacher_login_form) БІЛЬШЕ НЕ ПОТРІБНА, ВИДАЛЯЄМО
        # with gr.Group(visible=False) as teacher_login_form:
        #    ... (старий код) ...

        # Режим студента
        with gr.Group(visible=False) as student_mode:
            gr.Markdown("# Режим студента")
            gr.Markdown("Режим студента поки не реалізовано.")
            # Кнопку повернення можна залишити
            back_to_modes_btn2 = gr.Button("Повернутися до вибору режиму")

        # Панель викладача
        with gr.Group(visible=False) as teacher_dashboard_ui: # Перейменував, щоб уникнути конфлікту імен
            # Завантажуємо UI з класу TeacherDashboard
            # Переконайтесь, що build_ui() не викликає логін або завантаження сесії
            # і що він може працювати з вже автентифікованим (через токен) об'єктом auth
            app_state.teacher_dashboard.build_ui() # Якщо build_ui повертає компонент, його треба присвоїти змінній

        # Логіка завантаження збереженої сесії ВИДАЛЕНА
        # if os.path.exists("session.json"):
        #    ... (старий код) ...

        # Логіка кнопок
        teacher_btn.click(
            fn=switch_to_teacher_mode_async, # Викликаємо нову асинхронну функцію
            inputs=[],
            # Оновлюємо видимість блоків + статус повідомлення
            outputs=[mode_selection, student_mode, teacher_dashboard_ui, status_message]
        )

        student_btn.click(
            fn=switch_to_student_mode,
            inputs=[],
            outputs=[mode_selection, student_mode, teacher_dashboard_ui, status_message]
        )

        # Кнопки повернення
        # back_to_modes_btn (з видаленої форми логіну) ВИДАЛЕНО
        back_to_modes_btn2.click( # Кнопка з режиму студента
            fn=back_to_selection,
            inputs=[],
            outputs=[mode_selection, student_mode, teacher_dashboard_ui, status_message]
        )

        # Обробники подій для login_btn та login_status ВИДАЛЕНО
        # login_btn.click(...)
        # login_status.change(...)

    return demo

# Запуск додатку
if __name__ == "__main__":
    # Перевірка наявності токена перед запуском (опціонально, але корисно)
    moodle_token = os.getenv("API_MOODLE_TOKEN")
    if not moodle_token:
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print("!!! ПОПЕРЕДЖЕННЯ: Змінна оточення API_MOODLE_TOKEN не знайдена!")
        print("!!! Додайте токен у файл .env для роботи режиму викладача.  !")
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    else:
         print(f"Знайдено API_MOODLE_TOKEN (останні 6 символів): ...{moodle_token[-6:]}")


    print("Створення інтерфейсу Gradio...")
    demo = create_interface()
    print("Запуск інтерфейсу Gradio...")
    # Можна додати share=True для публічного доступу, якщо потрібно
    demo.launch()
    print("Додаток Gradio запущено.")