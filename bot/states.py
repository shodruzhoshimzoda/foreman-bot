from aiogram.fsm.state import State, StatesGroup


class NewTask(StatesGroup):
    content = State()   # шеф присылает текст / фото / голосовое
    priority = State()  # выбирает важность
    foremen = State()   # выбирает прорабов и отправляет
