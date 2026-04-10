from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import random

def human_like_click(driver, element):
    """
    Плавный клик без левых библиотек. 
    Работает на любом разрешении и в headless!
    """
    actions = ActionChains(driver)
    
    # Слегка скроллим к элементу, чтобы он просто был в зоне видимости (необязательно по центру)
    driver.execute_script("arguments[0].scrollIntoView({block: 'nearest'});", element)
    time.sleep(0.2)
    
    # 1. Наводимся на элемент
    actions.move_to_element(element).perform()
    time.sleep(random.uniform(0.1, 0.3)) # Пауза (человек прицелился)
    
    # 2. Делаем микро-дрожание мышки в пределах кнопки
    jitter_x = random.choice([-2, 1, 2])
    jitter_y = random.choice([-1, 1])
    ActionChains(driver).move_by_offset(jitter_x, jitter_y).perform()
    time.sleep(random.uniform(0.05, 0.15))
    
    # 3. Кликаем
    ActionChains(driver).click().perform()

# === ОСНОВНОЙ КОД ===
driver = webdriver.Edge()

try:
    driver.get("https://www.bing.com/search?q=Selenium+WebDriver")
    
    # Используем WebDriverWait вместо time.sleep() — это профессиональнее и быстрее
    wait = WebDriverWait(driver, 10)
    
    # Ждем, пока вкладка появится в коде и станет видимой
    images_tab = wait.until(EC.visibility_of_element_located((By.XPATH, "//a[contains(@href, '/images')]")))
    print("Нашли вкладку Images!")

    time.sleep(1)  # Небольшая пауза перед движением (имитация раздумий)

    # Делаем дела! Вызываем нашу надежную функцию
    print("Имитируем движение мыши и клик...")
    human_like_click(driver, images_tab)
    
    print("Успешно перешли!")
    time.sleep(5)  # Просто чтобы ты глазами увидел результат

finally:
    driver.quit()