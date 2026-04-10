import random
import time

from selenium.webdriver.common.action_chains import ActionChains

class HumanBehavior:
    def __init__(self, driver, show_cursor=True):
        self.driver = driver
        self.show_cursor = show_cursor
        self.last_mouse_position = [
            random.randint(100, 500),
            random.randint(100, 500)
        ]
    
    def _draw_debug_cursor(self, x, y, color="red"):
        """Draw a debug cursor on the page"""
        if not self.show_cursor:
            return
        
        script = f"""
        let cursor = document.getElementById('selenium-bot-cursor');
        if (!cursor) {{
            cursor = document.createElement('div');
            cursor.id = 'selenium-bot-cursor';
            cursor.style.width = '12px';
            cursor.style.height = '12px';
            cursor.style.background = '{color}';
            cursor.style.position = 'absolute';
            cursor.style.borderRadius = '50%';
            cursor.style.zIndex = '9999999';
            cursor.style.pointerEvents = 'none'; // Allow clicks to pass through
            cursor.style.boxShadow = '0 0 5px rgba(0,0,0,0.5)';
            cursor.style.transition = 'background 0.2s';
            document.body.appendChild(cursor);
        }}
        // Center the cursor on the (x, y) position
        cursor.style.left = (arguments[0] - 6) + 'px';
        cursor.style.top = (arguments[1] - 6) + 'px';
        """
        self.driver.execute_script(script, x, y)

    def _ease_in_out(self, t):
        """Ease in-out function for smoother mouse movement (smoothstep)"""
        return t * t * (3 - 2 * t)
    
    def scroll_page(self):
        """
        Generate random scroll divisor with probability
        70% of the time: scroll small portion (2-10 = 10% to 50%)
        30% of the time: scroll to end or near end (1-1.5 = 67% to 100%)
        Based on studies showing users typically scroll 10-30% of a page
        """
        if random.random() < 0.7:
            random_scroll_divisor = random.uniform(2, 10)
        else:
            random_scroll_divisor = random.uniform(1, 1.5)

        # JS script for smooth scroll down to mimic human behavior
        smooth_scroll_script = f"""
            let currentScroll = 0;
            let maxScroll = document.body.scrollHeight / {random_scroll_divisor};

            function humanScroll() {{
                // Random step between 30 and 70 pixels (Math.random() * (max - min + 1)) + min)
                let randomStep = Math.floor(Math.random() * (70 - 10 + 1)) + 10;

                // Random delay between 30 and 120 milliseconds (Math.random() * (max - min + 1)) + min)
                let randomDelay = Math.floor(Math.random() * (120 - 30 + 1)) + 30;

                window.scrollBy(0, randomStep);
                currentScroll += randomStep;

                if (currentScroll < maxScroll) {{
                    setTimeout(humanScroll, randomDelay);
                }}
            }}

            // Start the human-like scrolling
            setTimeout(humanScroll, 50);
        """

        # Execute the smooth scroll script
        self.driver.execute_script(smooth_scroll_script)

        # Wait a bit after scrolling
        time.sleep(random.uniform(5, 10))
    
    def move_to_element(self, element, steps=None):
        """Move mouse to the given element in a human-like manner"""
        start_x, start_y = self.last_mouse_position
        location = element.location_once_scrolled_into_view
        size = element.size

        # Move to the center of the element with some random offset
        target_x = location['x'] + random.randint(5, size['width'] - 5)
        target_y = location['y'] + random.randint(5, size['height'] - 5)

        # Sometimes make a "miss"
        miss = random.random() < 0.2
        if miss:
            target_x += random.randint(-30, 30)
            target_y += random.randint(-30, 30)

        # Control point (for Bezier curve)
        control_x = (start_x + target_x) / 2 + random.randint(-150, 150)
        control_y = (start_y + target_y) / 2 + random.randint(-150, 150)

        if steps is None:
            distance = ((target_x - start_x)**2 + (target_y - start_y)**2) ** 0.5
            steps = int(distance / random.uniform(8, 15))
            steps = max(10, min(40, steps))

        last_x, last_y = start_x, start_y

        for i in range(steps + 1):
            t = i / steps
            t = self._ease_in_out(t)

            curr_x = int((1 - t)**2 * start_x + 2 * (1 - t) * t * control_x + t**2 * target_x)
            curr_y = int((1 - t)**2 * start_y + 2 * (1 - t) * t * control_y + t**2 * target_y)

            # Micro-vibration
            curr_x += random.randint(-2, 2)
            curr_y += random.randint(-2, 2)

            delta_x = curr_x - last_x
            delta_y = curr_y - last_y

            # Move the mouse by the delta using ActionChains
            if delta_x != 0 or delta_y != 0:
                actions = ActionChains(self.driver)
                actions.move_by_offset(delta_x, delta_y).perform()
            
            # Draw debug cursor at the current position
            self._draw_debug_cursor(curr_x, curr_y)

            last_x, last_y = curr_x, curr_y

            # Variable pause to mimic human movement speed changes
            if i < steps * 0.3:
                pause = random.uniform(0.005, 0.02)
            elif i < steps * 0.7:
                pause = random.uniform(0.01, 0.04)
            else:
                pause = random.uniform(0.02, 0.06)

            if random.random() < 0.05:
                pause += random.uniform(0.05, 0.15)

            time.sleep(pause)

        # If we missed the target, do a quick correction move
        if miss:
            time.sleep(random.uniform(0.05, 0.2))
            self.move_to_element(element, steps=random.randint(5, 10))
            return

        # Final micro-correction before clicking
        for _ in range(random.randint(1, 3)):
            delta_x = random.randint(-2, 2)
            delta_y = random.randint(-2, 2)
            ActionChains(self.driver).move_by_offset(delta_x, delta_y).perform()
            last_x += delta_x
            last_y += delta_y
            self._draw_debug_cursor(last_x, last_y)
            time.sleep(random.uniform(0.01, 0.03))

        time.sleep(random.uniform(0.1, 0.4))
        self.last_mouse_position = [last_x, last_y]

    def click_element(self, element):
        """Full cycle: move to element, highlight in green (click), then click"""
        self.move_to_element(element)
        time.sleep(random.uniform(0.1, 0.3))
        
        # Change the cursor color to green at the moment of clicking
        self._draw_debug_cursor(self.last_mouse_position[0], self.last_mouse_position[1], color="green")
        element.click()
        time.sleep(0.1)
        
        # Return the cursor color to red after clicking
        self._draw_debug_cursor(self.last_mouse_position[0], self.last_mouse_position[1], color="red")