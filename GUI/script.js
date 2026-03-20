function startBot() {
  const countStr = document.getElementById('count_input').value;
  const count = parseInt(countStr, 10);

  if (isNaN(count) || count <= 0) {
    alert("Please enter a valid positive number!");
    return;
  }
  
  // 1. Block the button and change its text
  document.getElementById('start_btn').disabled = true;
  document.getElementById('start_btn').innerText = "In Progress...";
  
  // 2. Green dot on and status text
  document.getElementById('dot').classList.add('active');
  document.getElementById('status_text').innerText = "Executing";
  

  
  // 3. Call the Python function to start the bot
  pywebview.api.main(count);
}

// Function to safely escape log messages for HTML display
function clear_log(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Called from Python to update the logs in the terminal
function update_log(message) {
  let logDiv = document.getElementById('log_area');

  const safeHtml = clear_log(message).replace(/\n/g, '<br>'); 
  logDiv.insertAdjacentHTML('beforeend', safeHtml + '<br>'); // new line after each message

  // Auto-scroll to the bottom
  logDiv.scrollTop = logDiv.scrollHeight;
}

// Called from Python when the loop is finished
function enable_start_button() {
  let btn = document.getElementById('start_btn');
  btn.disabled = false;
  btn.innerText = "Start";
  
  document.getElementById('dot').classList.remove('active');
  document.getElementById('status_text').innerText = "Waiting";
}