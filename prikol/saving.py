import requests
from tqdm import tqdm
import os
import re
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv())

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
    return s


def get_tasks(task_type: int):
    return requests.get(base + f"api/tasks/ids/ege/{task_type}/").json()["result"]


def save_from_examinf(tasks_folder_path: str, login: str, password: str):
    s = create_session(login, password)
    if not s:
        exit()
    for num in range(1, 28):
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
                solve_string = ""
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
                    text = (
                        bytes(text, encoding="utf-8").replace(
                            b"\xc2\xa0 \xc2\xa0 ", b"    "
                        )
                    ).decode()
                    if "https://lfvb.ru" not in text:
                        text = (
                            "\n# Solved by lfvbdghkjfgm\n# https://lfvb.ru\n\n" + text
                        )
                    solve_string += text + "\n\n"

                js = s.get(base + f"api/task/{task}/publicSolutions/").json()
                result = js.get("result", 0)
                if not result:
                    continue
                for data in result:
                    id, name = data["id"], data["studentDisplayName"]
                    if "Алексей Т." in name:
                        continue
                    solve = post_requests(
                        f"api/task/{task}/publicSolution/{id}/view/", s
                    )
                    result = solve.get("result", 0)
                    if not result:
                        continue
                    solution = result.get("solution", 0)
                    if not solution:
                        continue
                    resources = solution.get("resources", 0)
                    if not resources:
                        continue
                    text = resources[0].get("text", 0)
                    if not text:
                        continue
                    text = text.strip("`")
                    if text.startswith("python"):
                        text = text[6:]
                        text = text.strip()
                    solve_string += f"# Solved by {name}\n\n{text}\n\n"
                if not solve_string:
                    continue
                solve_string = solve_string.encode().replace(b"\xc2\xa0", b"").decode()
                if num == 6 and "вперед" in solve_string:
                    ex = "kum"
                elif "/*" in text and "*/" in text:
                    ex = "c"
                else:
                    ex = "py"
                with open(
                    f"{tasks_folder_path}/{num}/{task}.{ex}", "w", encoding="utf-8"
                ) as f:
                    solve_string = (
                        bytes(solve_string, encoding="utf-8").replace(
                            b"\xc2\xa0 \xc2\xa0 ", b"    "
                        )
                    ).decode()
                    f.write(solve_string)


def send_to_examinf(tasks_folder_path: str, login: str, password: str):
    s = create_session(login, password)
    if not s:
        exit()
    task_types = [i for i in os.listdir(tasks_folder_path) if i.isdigit()]
    task_types = sorted(list(map(int, task_types)))
    ct = 0
    for r in task_types:
        tasks = os.listdir(tasks_folder_path + "/" + str(r))
        for task in tasks:
            num = re.findall(r"\d+", task)
            if num:
                num = num[0]
                with open(f"{tasks_folder_path}/{r}/{task}", encoding="utf-8") as f:
                    text = f.read()
                text = text.split("# Solved")
                text = ["# Solved" + i for i in text]
                text = [i for i in text if "lfvb.ru" in i]
                if not text:
                    continue
                text = text[0]
                text = text.replace("lfvbdghkfjgm", "lfvbdghkjfgm")
                js = {
                    "solution": {
                        "resources": [
                            {"kind": "text", "text": f"```python\n{text}\n```"}
                        ]
                    }
                }
                post_requests(f"api/task/{num}/user/me/solution/", s, js)
                post_requests(
                    f"api/task/{num}/user/me/solution/publish/",
                    s,
                    {"comment": "Решение загружено кодом"},
                )
                ct += 1
    print(f"Загружено {ct} решений")


save_from_examinf("../examinf/tasks", os.getenv("LOGIN"), os.getenv("PASSWORD"))
