let isSetupDone = false;

function start_first_setup() {
  document.getElementById('start_btn').disabled = true;
  
  let setupBtn = document.getElementById('setup_btn');
  if (setupBtn) {
    setupBtn.disabled = true;
  }

  pywebview.api.first_setup();
}

function hide_setup_button() {
  isSetupDone = true;
  let setupBtn = document.getElementById('setup_btn');
  if (setupBtn) {
    setupBtn.style.display = 'none';
  }
}

function enable_setup_button() {
  const setupBtn = document.getElementById('setup_btn');
  if (setupBtn) {
      setupBtn.disabled = false;
  }
}

function start_bot() {

  if (isSetupDone === false) {
    alert("Please complete the First Setup before starting!");
    return;
  }

  const countStr = document.getElementById('count_input').value;
  const count = parseInt(countStr, 10);

  if (isNaN(count) || count <= 0) {
    alert("Please enter a valid positive number!");
    return;
  }

  if (count > 99) {
    alert("Please enter a number less than or equal to 99!");
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

function show_history() {
  pywebview.api.open_history_window();
}

function hideBrowserToggle() {
  const toggle = document.getElementById('hideBrowserToggle');
  if (!toggle) {
    return;
  }

  pywebview.api.set_hide_browser(Boolean(toggle.checked));
}

let loaderInterval;

function start_loader() {
  clearInterval(loaderInterval);

  let startBtn = document.getElementById('start_btn');
  if (startBtn) {
    startBtn.disabled = true;
  }

  let setupBtn = document.getElementById('setup_btn');
  // Avoid running First Setup while warmup uses the same browser profile.
  if (setupBtn && isSetupDone === false) {
    setupBtn.disabled = true;
  }

  const tryShowLoader = () => {
    pywebview.api.check_driver_status().then(isLoading => {
      if (isLoading === true && !document.getElementById('inline_loader')) {
        let logDiv = document.getElementById('log_area');
        let loaderHTML = `
          <div id="inline_loader" style="margin: 10px 0;">
            <span style="color: var(--accent);">> System: Preparing Web Driver...</span>
            <div class="progress-bar-indeterminate" style="margin-top: 5px;"></div>
          </div>`
        logDiv.insertAdjacentHTML('beforeend', loaderHTML);
        logDiv.scrollTop = logDiv.scrollHeight;
      }

      // If loading is done, stop the loader and enable the start button
      if (isLoading === false) {
        stop_loader();
      }
    }).catch(error => {
      console.error('Failed to check driver status:', error);
      pywebview.api.log("Failed to check driver status: " + String(error));
      stop_loader();
    });
  };

  // Check immediately, then poll until Python reports warmup completed.
  tryShowLoader();
  loaderInterval = setInterval(tryShowLoader, 500);
}

function stop_loader() {
  clearInterval(loaderInterval);

  let inlineLoader = document.getElementById('inline_loader');
  if (inlineLoader) {
    inlineLoader.remove();
  }

  let startBtn = document.getElementById('start_btn');
  if (startBtn && isSetupDone) {
    startBtn.disabled = false;
  }

  let setupBtn = document.getElementById('setup_btn');
  // Re-enable First Setup only if setup was not completed yet.
  if (setupBtn && isSetupDone === false) {
    setupBtn.disabled = false;
  }
}

document.addEventListener('DOMContentLoaded', function() {
  const toggle = document.getElementById('hideBrowserToggle');
  if (toggle) {
    toggle.addEventListener('change', hideBrowserToggle);
  }
});

window.addEventListener('pywebviewready', function() {
    
  pywebview.api.get_settings().then(function(settings) {
    // Sync UI from persisted settings before user interaction.
    if (settings.first_setup_done === true) {
      hide_setup_button();
    } else {
      pywebview.api.log("Please complete the First Setup before starting the bot!");
    }

    start_loader();

    const toggle = document.getElementById('hideBrowserToggle');
    if (toggle) {
      toggle.checked = Boolean(settings.hide_browser);
    }

  });
});