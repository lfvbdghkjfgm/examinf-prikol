import requests
import re
import time
from tqdm import tqdm





base = 'https://examinf.ru/'
credents = ('your_login','your_password')


#  Эта функция отправляет post запросы на сайт, пока не исчезнет ошибка
#  Потенциально может перегрузить сайт!!! 

#  принимает на вход:
#  (часть ссылки после https://examinf.ru/ (например api/auth/register),
#  requests сессию от которой будет выполняться запрос
#  (опционально) json с данными для post запроса, которые отправятся как json)


def post_requests(api:str,s:requests.session,json:dict ={}):
    while True:
        try:
            r = s.post(base+api,json=json)
            t = r.json()
            return t
        except:
            pass

# регистрирует аккаунт

# принимает на вход:
# (номер аккаунта, аккаунты типовые, в никах отличается только номер)
    
def register_account(num: int):
    with open('creds.txt','r') as f:
        if f"lfvb_test_{num} 1234" in f.readlines():
            return None 
    s = requests.session()
    r = s.post(base+'api/auth/register/',json={'username': f"lfvb_test_{num}", 'password': '1234', 'email': f"test_{num}@123.ru"})
    r = s.post(base+'api/auth/register-confirm/',json={'username': f"lfvb_test_{num}", 'password': '1234', 'email': f"test_{num}@123.ru",'code':''})

    with open('creds.txt','a') as f:
        f.write(f'lfvb_test_{num} 1234\n')

# создает requests сессию кокретного пользователя

# принимает на вход:
# (логин от аккаунта,
#  пароль от аккаунта)

def create_session(login:str,password:str):
    s = requests.session()
    r = post_requests('api/auth/login/',s,json={"usernameOrEmail":login,"password":password})
    check = r.get('error',0)
    if check:
        return
    s.cookies.update({'token':r['result']['token']})
    return s

def get_tasks(task_type:int):
    return requests.get(base+f'api/tasks/ids/ege/{task_type}/').json()['result']

# ставит лайки на все задания кокретного типа от лица 1 пользователя

# принимает на вход:
# (логин,
#  пароль,
#  тип задания (число от 1 до 27),
#  действие (1 - лайк, -1 - дизлайк, 0 - отмена лайка или дизлайка))

def magic(login:str,password:str,task_type:int,action:int):
    s = create_session(login,password)
    if not s:
        return
    if action == 1:
        st = 'like'
    elif action == -1:
            st = 'dislike'
    else:
        st = 'unlike'
    for task in tqdm(get_tasks(task_type)):
        post_requests(f'api/task/{task}/{st}/',s)

# ставит лайки на все решенные задания от лица 1 пользователя

# принимает на вход:
# (логин,
#  пароль,
#  действие (1 - лайк, -1 - дизлайк, 0 - отмена лайка или дизлайка))

def another_magic(login:str,password:str,action:int):
    s = create_session(login,password)
    if not s:
        return
    if action == 1:
        st = 'like'
    elif action == -1:
            st = 'dislike'
    else:
        st = 'unlike'
    for task in tqdm(range(1700)):
        r = s.get(base+f'api/task/{task}/answer_v2/my_answer/').json()
        solve = r.get('result',0)
        if solve:
            post_requests(f'api/task/{task}/{st}/',s)

# проверяет твой прогресс в выполнении заданий
# Может учитывать скрытые задания, недоступные для выполнения!

# принимает на вход:
# (логин,
#  пароль,
#  тип задания (число от 1 до 27))

def check_progress(login:str,password:str,task_type:int):
    if task_type not in range(1,28):
        return None
    s = create_session(login,password)
    if not s:
        return
    tasks = get_tasks(task_type)
    solves = 0
    for task in tasks:
        r = s.get(base+f'api/task/{task}/answer_v2/my_answer/').json()
        solve = r.get('result',0)
        if solve:
            solves+=1
    print(f'Вы решили заданий {task_type} типа: {solves}/{len(tasks)}')
    print(f'Это составляет {int(solves*100/len(tasks))}%')


# функция для накрутки лайков на конркетное задание
# аккаунты проверяются (например если данный аккаунт уже ставил лайк на задание, то код просто пропустит этот аккаунт
# поэтому даже в случае небольшого количества необходимых лайков, он может сделать намного больше итераций)

# принимает на вход:
# (номер задания,
#  действие (1 - лайк, -1 - дизлайк, 0 - отмена лайка или дизлайка),
#  количество лайков, которые надо поставить)

# количество лайков, которые в итоге будут поставлены считается как min(количество аккаунтов, указанное количество лайков)

def nacrutka(task:int,action:int,number:int):
    with open('creds.txt') as f:
        creds = f.readlines()
    if action == 1:
            st = 'like'
    elif action == -1:
        st = 'dislike'
    else:
        st = 'unlike'
    for num, cred in tqdm(enumerate(creds,1)):
        login,password = cred.split()
        s = create_session(login,password)
        r = s.get(base+f'api/task/{task}/additionalInfo/').json()
        if r['result']['likedByMe'] == True and action == 1 or r['result']['dislikedByMe'] == True and action == -1 or r['result']['dislikedByMe'] == False and r['result']['likedByMe'] == False and action == 0:
            number+=1
            continue
        post_requests(f'api/task/{task}/{st}/',s)
        if num == number:
            break


