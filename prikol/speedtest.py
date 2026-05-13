import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as Ec

driver = webdriver.Chrome()
wait = WebDriverWait(driver, 10)


def click_button(xpath: str):
    button = wait.until(Ec.element_to_be_clickable((By.XPATH, xpath)))
    button.click()


def login(login: str, password: str):
    driver.get("https://examinf.ru/")
    time.sleep(0.5)
    click_button("//button[text()='Войти']")

    login_field = driver.find_element(
        By.XPATH, '//*[@id="authOpenButtons"]/div[1]/div/form/input[1]'
    )
    password_field = driver.find_element(
        By.XPATH, '//*[@id="authOpenButtons"]/div[1]/div/form/input[2]'
    )
    login_field.send_keys(login)
    password_field.send_keys(password)
    time.sleep(0.5)
    click_button('//*[@id="authOpenButtons"]/div[1]/div/form/input[3]')


def speedtest():
    driver.get("https://examinf.ru/")
    click_button('//*[@id="ROOT"]/div/header/div/a[3]')
    click_button('//*[@id="ROOT"]/div/div[2]/div[2]/div/div[3]/a')
    click_button('//*[@id="ROOT"]/div/div[2]/div/div/button')

    lines = wait.until(
        lambda d: d.find_elements(
            By.CSS_SELECTOR, ".CodeMirror-code pre.CodeMirror-line"
        )
    )

    code = "\n".join(line.text for line in lines).strip()
    # tm = len(code) * 60 / 725
    tm = len(code) * 60 / 600
    time.sleep(tm)

    driver.execute_script(
        """
        const editor = document.querySelector('#examinf-typing-cm-mount .CodeMirror').CodeMirror;
        editor.setValue(arguments[0]);
        editor.focus();
    """,
        code,
    )
    input()


def set_data(name_inp, surname_inp):
    driver.get("https://examinf.ru/account/")
    name = wait.until(
        Ec.element_to_be_clickable(
            (By.XPATH, '//*[@id="ROOT"]/div/div[2]/div[2]/div/div[1]/div/input[1]')
        )
    )
    surname = wait.until(
        Ec.element_to_be_clickable(
            (By.XPATH, '//*[@id="ROOT"]/div/div[2]/div[2]/div/div[1]/div/input[2]')
        )
    )
    surname.clear()
    name.clear()
    surname.send_keys(surname_inp)
    name.send_keys(name_inp)
    time.sleep(0.5)


k = 0
for x in open("creds.txt"):
    log, password = x.split()

    driver.get("https://examinf.ru/")

    login(log, password)

    # speedtest()

    set_data("by lfvbdghkjfgm", "pwned")

    click_button('//*[@id="ROOT"]/div/div[2]/div[1]/button')
    k += 1
    if k == 5:
        break
