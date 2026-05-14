import asyncio
import requests
import re
import threading
from tqdm import tqdm
from dotenv import find_dotenv, load_dotenv
import os

load_dotenv(find_dotenv())


base = "https://examinf.ru/"
credents = (os.getenv("LOGIN"), os.getenv("PASSWORD"))
MAX_CONCURRENT_REQUESTS = 200
BATCH_SIZE = 100
CREDS_FILE_LOCK = threading.Lock()


def _chunked(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


#  Эта функция отправляет post запросы на сайт, пока не исчезнет ошибка
#  Потенциально может перегрузить сайт!!!

#  принимает на вход:
#  (часть ссылки после https://examinf.ru/ (например api/auth/register),
#  requests сессию от которой будет выполняться запрос
#  (опционально) json с данными для post запроса, которые отправятся как json)


async def post_requests(api: str, s: requests.session, json: dict = {}):
    while True:
        try:
            r = await asyncio.to_thread(s.post, base + api, json=json)
            t = await asyncio.to_thread(r.json)
            return t
        except:
            pass


# регистрирует аккаунт

# принимает на вход:
# (номер аккаунта, аккаунты типовые, в никах отличается только номер)


async def register_account(num: int):
    def _has_credentials():
        with CREDS_FILE_LOCK:
            with open("creds.txt", "r") as f:
                return f"lfvb_test_{num} 1234" in f.readlines()

    if await asyncio.to_thread(_has_credentials):
        return None
    s = requests.session()
    r = await asyncio.to_thread(
        s.post,
        base + "api/auth/register/",
        json={
            "username": f"lfvb_test_{num}",
            "password": "1234",
            "email": f"test_{num}@123.ru",
        },
    )
    r = await asyncio.to_thread(
        s.post,
        base + "api/auth/register-confirm/",
        json={
            "username": f"lfvb_test_{num}",
            "password": "1234",
            "email": f"test_{num}@123.ru",
            "code": "",
        },
    )

    def _append_credentials():
        with CREDS_FILE_LOCK:
            with open("creds.txt", "a") as f:
                f.write(f"lfvb_test_{num} 1234\n")

    await asyncio.to_thread(_append_credentials)


async def register_accounts(
    start: int, count: int, limit: int = MAX_CONCURRENT_REQUESTS
):
    sem = asyncio.Semaphore(limit)

    async def _worker(num: int):
        async with sem:
            await register_account(num)

    await asyncio.gather(*(_worker(num) for num in tqdm(range(start, start + count))))


# создает requests сессию кокретного пользователя

# принимает на вход:
# (логин от аккаунта,
#  пароль от аккаунта)


async def create_session(login: str, password: str):
    s = requests.session()
    r = await post_requests(
        "api/auth/login/", s, json={"usernameOrEmail": login, "password": password}
    )
    check = r.get("error", 0)
    if check:
        return
    s.cookies.update({"token": r["result"]["token"]})
    return s


async def get_tasks(task_type: int):
    r = await asyncio.to_thread(requests.get, base + f"api/tasks/ids/ege/{task_type}/")
    t = await asyncio.to_thread(r.json)
    return t["result"]


# ставит лайки на все задания кокретного типа от лица 1 пользователя

# принимает на вход:
# (логин,
#  пароль,
#  тип задания (число от 1 до 27),
#  действие (1 - лайк, -1 - дизлайк, 0 - отмена лайка или дизлайка))


async def magic(login: str, password: str, task_type: int, action: int):
    s = await create_session(login, password)
    if not s:
        return
    if action == 1:
        st = "like"
    elif action == -1:
        st = "dislike"
    else:
        st = "unlike"
    sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    tasks = await get_tasks(task_type)

    async def _worker(task):
        async with sem:
            await post_requests(f"api/task/{task}/{st}/", s)

    pbar = tqdm(total=len(tasks))
    for chunk in _chunked(tasks, BATCH_SIZE):
        await asyncio.gather(*(_worker(task) for task in chunk))
        pbar.update(len(chunk))
    pbar.close()


# ставит лайки на все решенные задания от лица 1 пользователя

# принимает на вход:
# (логин,
#  пароль,
#  действие (1 - лайк, -1 - дизлайк, 0 - отмена лайка или дизлайка))


async def another_magic(login: str, password: str, action: int):
    s = await create_session(login, password)
    if not s:
        return
    if action == 1:
        st = "like"
    elif action == -1:
        st = "dislike"
    else:
        st = "unlike"
    sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    all_tasks = list(range(1700))

    async def _worker(task):
        async with sem:
            res = await asyncio.to_thread(
                s.get, base + f"api/task/{task}/answer_v2/my_answer/"
            )
            r = await asyncio.to_thread(res.json)
            solve = r.get("result", 0)
            if solve:
                await post_requests(f"api/task/{task}/{st}/", s)

    pbar = tqdm(total=len(all_tasks))
    for chunk in _chunked(all_tasks, BATCH_SIZE):
        await asyncio.gather(*(_worker(task) for task in chunk))
        pbar.update(len(chunk))
    pbar.close()


# проверяет твой прогресс в выполнении заданий
# Может учитывать скрытые задания, недоступные для выполнения!

# принимает на вход:
# (логин,
#  пароль,
#  тип задания (число от 1 до 27))


async def check_progress(login: str, password: str, task_type: int):
    if task_type not in range(1, 28):
        return None
    s = await create_session(login, password)
    if not s:
        return
    tasks = await get_tasks(task_type)
    sem = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async def _worker(task):
        async with sem:
            res = await asyncio.to_thread(
                s.get, base + f"api/task/{task}/answer_v2/my_answer/"
            )
            r = await asyncio.to_thread(res.json)
            solve = r.get("result", 0)
            if solve:
                return 1
            return 0

    solves = 0
    pbar = tqdm(total=len(tasks))
    for chunk in _chunked(tasks, BATCH_SIZE):
        solves += sum(await asyncio.gather(*(_worker(task) for task in chunk)))
        pbar.update(len(chunk))
    pbar.close()
    print(f"Вы решили заданий {task_type} типа: {solves}/{len(tasks)}")
    print(f"Это составляет {int(solves*100/len(tasks))}%")


# функция для накрутки лайков на конркетное задание
# аккаунты проверяются (например если данный аккаунт уже ставил лайк на задание, то код просто пропустит этот аккаунт
# поэтому даже в случае небольшого количества необходимых лайков, он может сделать намного больше итераций)

# принимает на вход:
# (номер задания,
#  действие (1 - лайк, -1 - дизлайк, 0 - отмена лайка или дизлайка),
#  количество лайков, которые надо поставить)

# количество лайков, которые в итоге будут поставлены считается как min(количество аккаунтов, указанное количество лайков)


async def nacrutka(task: int, action: int, number: int):
    def _read_creds():
        with open("creds.txt") as f:
            return f.readlines()

    creds = await asyncio.to_thread(_read_creds)
    if action == 1:
        st = "like"
    elif action == -1:
        st = "dislike"
    else:
        st = "unlike"
    for num, cred in tqdm(enumerate(creds, 1)):
        login, password = cred.split()
        s = await create_session(login, password)
        res = await asyncio.to_thread(s.get, base + f"api/task/{task}/additionalInfo/")
        r = await asyncio.to_thread(res.json)
        if (
            r["result"]["likedByMe"] == True
            and action == 1
            or r["result"]["dislikedByMe"] == True
            and action == -1
            or r["result"]["dislikedByMe"] == False
            and r["result"]["likedByMe"] == False
            and action == 0
        ):
            number += 1
            continue
        await post_requests(f"api/task/{task}/{st}/", s)
        if num == number:
            break


async def main():
    pass


if __name__ == "__main__":
    asyncio.run(main())
