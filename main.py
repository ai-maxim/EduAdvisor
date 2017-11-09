import re
import redis
import telebot
import sqlite3
import csv
from vk_info import *

from enum import Enum, unique

from flask import Flask, request, abort

from model import *

#WEBHOOK_URL_BASE = 'https://bot.shadowservants.ru'
WEBHOOK_PATH = '/hook'

TOKEN = '498529639:AAFOt8w_u_7LquJWlyEiPUUfFdxL6R7AIIk'

app = Flask(__name__)

bot = telebot.TeleBot(TOKEN, threaded=False)

bot.remove_webhook()
#bot.set_webhook(url=WEBHOOK_URL_BASE + WEBHOOK_PATH, certificate=open('ssl/YOURPUBLIC.pem', 'r'))

r = redis.StrictRedis(host='localhost', port=6379, db=0)



def recommender(klimov, cl1, cl2):
    proffs = [
        [['Product manager', 'IT-recruitment'], ['SMM', 'Тех поддержка']],
        [['Робототехник', 'Системный инженер'], ['Специалист по информационной безопасности', 'Системный администратор']], 
        [['Системный архитектор', 'ERP-специалист'], ['Бизнес аналитик', 'QA-инженер']], 
        [['Data scientist', 'Backend dev'], ['Технический писатель', 'Junior Developer']], 
        [['UI прототипирование','Frontend dev'], ['3d modelist', 'SEO']]
        ]
    return proffs[klimov][cl1][cl2]


class RedisStorage(object):
    def __init__(self, red):
        self._st = red

    def get(self, key):
        return self._st.get(key).decode()

    def set(self, key, value):
        return self._st.set(key, value)


class SimpleFuckingStorage(object):
    def __init__(self):
        self._st = {}

    def get(self, key):
        return self._st.get(key)

    def set(self, key, value):
        self._st[key] = value

    def __str__(self):
        return str(self._st)


ss = SimpleFuckingStorage()


def check_email(text):
    return re.match('[^@]+@[^@]+\.[^@]+', text) is not None

@unique
class KlimovCategory(Enum):
    HUMAN = 0
    TECHNICS = 1
    WORLD = 2
    SIGN = 3
    ART = 4


class KlimovTestVariant(object):
    def __init__(self, text, category: KlimovCategory):
        self.text = text
        self.category = category

class KlimovTestQuestion(object):
    def __init__(self, text="Что вы выберете?"):
        self.variants = []
        self.text = text

    def add_variant(self, variant: KlimovTestVariant):
        self.variants.append(variant)
        return self

    def check_category(self, text):
        if self.variants[0].text == text:
            return self.variants[0].category
        else:
            return self.variants[1].category

    def create_question_markup(self):
        markup = telebot.types.ReplyKeyboardMarkup(one_time_keyboard=True)
        for variant in self.variants:
            markup.row(telebot.types.KeyboardButton(variant.text))
        return markup


klimov_questions = []

with open("klimov_questions.txt", "r") as kq:
    for line in kq:
        question = line.rstrip().split(";")
        v1 = KlimovTestVariant(question[0], question[2])
        v2 = KlimovTestVariant(question[1], question[3])
        klimov_questions.append(KlimovTestQuestion().add_variant(v1).add_variant(v2))

# klimov_questions = []



class TestQuestions(object):
    def __init__(self, questions):
        self.st = RedisStorage(r)
        self.questions = questions

    def question_router(self, message: telebot.types.Message):
        index = self.st.get('chat_{}_question'.format(message.chat.id)) or '0'
        index = int(index)
        if index >= len(self.questions):
            return None
        return self.questions[index]

    def send_question_to_user(self, message: telebot.types.Message):
        question = self.question_router(message)
        if not question:
            send_result(message)
            # send_result(message)
            print('finish here')
            return
        markup = question.create_question_markup()
        new_message = bot.send_message(message.chat.id, question.text, reply_markup=markup)

        bot.register_next_step_handler(new_message, self.check_answer)

    def check_answer(self, message):
        question = self.question_router(message)
        if not question:
            bot.send_message(message.chat.id,'Что-то пошло не так. Попробуйте снова )')
            return

        category = question.check_category(message.text)
        print(category)
        points = self.st.get('chat_{}_{}_points'.format(message.chat.id, str(category))) or '0'
        points = int(points) + 1
        self.st.set('chat_{}_{}_points'.format(message.chat.id, str(category)), str(points))

      
        ind = self.st.get('chat_{}_question'.format(message.chat.id)) or '0'
        ind = int(ind) + 1

        self.st.set('chat_{}_question'.format(message.chat.id), str(ind))
        self.send_question_to_user(message)


tq = TestQuestions(klimov_questions)



@bot.message_handler(commands=['help', 'start'])
def send_welcome(message: telebot.types.Message):
    markup = telebot.types.ReplyKeyboardMarkup(one_time_keyboard=True)
    markup.add(telebot.types.InlineKeyboardButton(text='Да!'))
    m = bot.send_message(message.chat.id,
                         'Привет. Я бот EduAdvisor. Я помогу тебе профориентироваться в IT \n'
                         'Ну что, {}, ты готов ?'.format(message.from_user.first_name), reply_markup=markup,
                         )

    tq.st.set('chat_{}_question'.format(m.chat.id), '0')
    for i in range(5):
        tq.st.set('chat_{}_{}_points'.format(m.chat.id, str(i)), '0')

    bot.register_next_step_handler(m, tq.send_question_to_user)


def get_user_data(m: telebot.types.Message):
    try:
        dicter = get_info_by_url(m.text)
        l = predict(dicter)
        cl1 = int(l[0])
        cl2 = int(l[1])
        maxx = -1
        maxi = -1
        for i in range(5):
            pts = tq.st.get('chat_{}_{}_points'.format(m.chat.id, str(i))) or '0'
            if int(pts) > maxx:
                maxx = int(pts)
                maxi = i
        bot.send_message(m.chat.id, 'Мы считаем, что вам наиболее всего подойдёт профессия {}. Желаем успехов!'.format(recommender(maxi, cl1, cl2)))
    except Exception as e:
        print(e)
        print(m.text)
        bot.send_message(m.chat.id, 'Извините, произошла ошибка, попробуйте ещё раз чуть-позже. Разработчики уже в курсе. <3')
    # markup = telebot.types.ReplyKeyboardMarkup(one_time_keyboard=True)
    # markup.add(telebot.types.KeyboardButton('Отправить номер телефона', request_contact=True))
    # nm = bot.send_message(m.chat.id,
    #                       "Введи свои контактные данные и узнай результат! Нажми на кнопку или введите почту :)",
    #                       reply_markup=markup)
    # bot.register_next_step_handler(nm, send_result)


def send_result(m: telebot.types.Message):

    # for i in range(5):
    #     pts = tq.st.get('chat_{}_{}_points'.format(m.chat.id, str(i))) or '0'
    #     bot.send_message(m.chat.id, 'Вы набрали {} очков по категории {}'.format(pts, KlimovCategory(i).name))

    # markup = telebot.types.ReplyKeyboardMarkup(one_time_keyboard=True)
    # markup.add(telebot.types.KeyboardButton('Осталось указать профиль vk'))
    nm = bot.send_message(m.chat.id,
                          "Остадось указать профиль vk. Введи его")
    bot.register_next_step_handler(nm, get_user_data)


@app.route('/')
def ind():
    return 'lol'


@app.route(WEBHOOK_PATH, methods=['POST'])
def hook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        return abort(403)

bot.polling()
