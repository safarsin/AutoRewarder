import time
import random

# Human-like typing with random delays between keystrokes
def human_typing(element, text):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.18))