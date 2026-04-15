document.addEventListener('DOMContentLoaded', () => {

  // Settings section handler
  const settingsBtn = document.getElementById('settingsBtn');
  const closeSettingsBtn = document.getElementById('closeSettingsBtn');
  const settingsPanel = document.getElementById('settingsPanel');

  // Open settings panel
  settingsBtn.addEventListener('click', () => {
    settingsPanel.classList.toggle('open');
  });

  // Close settings panel
  closeSettingsBtn.addEventListener('click', () => {
    settingsPanel.classList.remove('open');
  });

  // Settings elements
  const autoStartUp = document.getElementById('autoStartUp');
  const advancedScheduling = document.getElementById('advancedScheduling');
  const advSchedulingWrapper = document.getElementById('advSchedulingWrapper');
  const runDurationWrapper = document.getElementById('runDurationWrapper');
  const saveSettingsBtn = document.getElementById('saveSettingsBtn');

  // The main checkbox
  if (autoStartUp) {
    autoStartUp.addEventListener('change', function() {
      if (this.checked) {
        advSchedulingWrapper.classList.remove('disabled');
        advancedScheduling.disabled = false;
      } else {
        advSchedulingWrapper.classList.add('disabled');
        advancedScheduling.disabled = true;
        advancedScheduling.checked = false;
        runDurationWrapper.classList.add('hidden');
      }
    });
  }

  // The dependent checkbox
  if (advancedScheduling) {
    advancedScheduling.addEventListener('change', function() {
      if (this.checked) {
        runDurationWrapper.classList.remove('hidden');
      } else {
        runDurationWrapper.classList.add('hidden');
      }
    });
  }

  // Save settings button
  if (saveSettingsBtn) {
    saveSettingsBtn.addEventListener('click', function() {
      const settingsData = {
        autoStartUp: autoStartUp.checked,
        advancedScheduling: advancedScheduling.checked,
        runDuration: parseInt(document.getElementById('runDuration').value, 10)
      };
        
      // Here I must call the python to save the settings
      // pywebview.api.save_user_settings(settingsData); or sth similar
        
      // Close the settings panel after saving
      settingsPanel.classList.remove('open');
    });
  }
});