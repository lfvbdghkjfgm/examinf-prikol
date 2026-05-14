import requests
from tqdm import tqdm
import os
import re

base = "https://examinf.ru/"


def post_requests(api: str, s: requests.session, json: dict = {}):
    while True:
        try:
            r = s.post(base + api, json=json)
            t = r.json()
            return t
        except:
            pass


def create_session(login: str, password: str):
    s = requests.session()
    r = post_requests(
        "api/auth/login/", s, json={"usernameOrEmail": login, "password": password}
    )
    check = r.get("error", 0)
    if check:
        return
    s.cookies.update({"token": r["result"]["token"]})
    return s


def get_tasks(task_type: int):
    return requests.get(base + f"api/tasks/ids/ege/{task_type}/").json()["result"]


def save_from_examinf(tasks_folder_path: str, login: str, password: str):
    s = create_session(login, password)
    if not s:
        exit()
    for num in range(1, 27):
        if num in [20, 21]:
            continue
        tasks = get_tasks(num)
        print()
        print(num)
        print()
        for task in tqdm(tasks):
            js = s.get(base + f"api/task/{task}/user/me/solution/").json()
            r = js.get("result", 0)
            if r:
                text = r["resources"]
                if text:
                    text = text[0]
                    text = text.get("text", 0)
                    if not text:
                        continue
                    if "python" in text:
                        text = text[10:-3].strip()
                    else:
                        text = text[3:-3].strip()
                    with open(f"{tasks_folder_path}/{num}/{task}.py", "w") as f:
                        text = (
                            bytes(text, encoding="utf-8").replace(
                                b"\xc2\xa0 \xc2\xa0 ", b"    "
                            )
                        ).decode()
                        if "https://lfvb.ru" not in text:
                            text = (
                                "\n# Solved by lfvbdghkjfgm\n# https://lfvb.ru\n\n"
                                + text
                            )
                        f.write(text)


def send_to_examinf(tasks_folder_path: str, login: str, password: str):
    s = create_session(login, password)
    if not s:
        exit()
    task_types = [i for i in os.listdir(tasks_folder_path) if i.isdigit()]
    task_types = sorted(list(map(int, task_types)))
    for r in task_types:
        tasks = os.listdir(tasks_folder_path + "/" + str(r))
        for task in tasks:
            num = re.findall(r"\d+", task)
            if num:
                num = num[0]
                with open(f"{tasks_folder_path}/{r}/{task}") as f:
                    text = f.read()
                js = {
                    "solution": {
                        "resources": [
                            {"kind": "text", "text": f"```python\n{text}\n```"}
                        ]
                    }
                }
                post_requests(f"api/task/{num}/user/me/solution/", s, js)
                post_requests(
                    f"api/task/{num}/user/me/solution/publish/", s, {"comment": ""}
                )


send_to_examinf("../examinf/tasks", "lfvbdghkjfgm", "15761576")
