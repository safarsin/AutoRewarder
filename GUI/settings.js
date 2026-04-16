document.addEventListener('DOMContentLoaded', () => {

  // Settings section handler
  const settingsBtn = document.getElementById('settingsBtn');
  const closeSettingsBtn = document.getElementById('closeSettingsBtn');
  const settingsPanel = document.getElementById('settingsPanel');

  if ( settingsBtn && closeSettingsBtn && settingsPanel ) {
    
    // Open settings panel
    settingsBtn.addEventListener('click', () => {
      settingsPanel.classList.add('open');
    });

    // Close settings panel
    closeSettingsBtn.addEventListener('click', () => {
      settingsPanel.classList.remove('open');
    });

  }

  // Settings elements
  const autoStartUp = document.getElementById('autoStartUp');
  const advancedScheduling = document.getElementById('advancedScheduling');
  const advSchedulingWrapper = document.getElementById('advSchedulingWrapper');
  const runDurationWrapper = document.getElementById('runDurationWrapper');
  const totalQueriesWrapper = document.getElementById('totalQueriesWrapper');
  const queriesPerHourWrapper = document.getElementById('queriesPerHourWrapper');
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
        totalQueriesWrapper.classList.add('hidden');
        queriesPerHourWrapper.classList.add('hidden');
      }
    });
  }

  // The dependent checkbox
  if (advancedScheduling) {
    advancedScheduling.addEventListener('change', function() {
      if (this.checked) {
        runDurationWrapper.classList.remove('hidden');
        totalQueriesWrapper.classList.remove('hidden');
        queriesPerHourWrapper.classList.remove('hidden');
      } else {
        runDurationWrapper.classList.add('hidden');
        totalQueriesWrapper.classList.add('hidden');
        queriesPerHourWrapper.classList.add('hidden');
      }
    });
  }

  // Save settings button
  if (saveSettingsBtn) {
    saveSettingsBtn.addEventListener('click', function() {
      const isAdvancedSchedulingEnabled = advancedScheduling.checked;
      let runDurationValue;
      let parsedTotalQueries;
      let parsedQueriesPerHour;

      if (isAdvancedSchedulingEnabled) {
        const inputValue = document.getElementById('runDuration').value.trim();
        const parsedRunDuration = parseInt(inputValue, 10);

        if (isNaN(parsedRunDuration) || parsedRunDuration <= 0) {
          alert('Please enter a valid positive number for run duration.');
          return; // Stop saving if the input is invalid
        } 

        if (parsedRunDuration > 24) {
          alert('Run duration can\'t exceed 24 hours.');
          return;
        }

        // If the input is valid, assign it to runDurationValue
        runDurationValue = parsedRunDuration;
      }

      const settingsData = {
        autoStartUp: autoStartUp.checked,
        advancedScheduling: isAdvancedSchedulingEnabled,
      };

      if (runDurationValue !== undefined) {
        settingsData.runDuration = runDurationValue;
      }

      // Read and validate total queries
      const totalQueriesRaw = document.getElementById('totalQueries').value.trim();
      parsedTotalQueries = parseInt(totalQueriesRaw, 10);

      if (isNaN(parsedTotalQueries) || parsedTotalQueries <= 0) {
        alert('Please enter a valid positive number for total queries.');
        return;
      }

      // Read and validate queries per hour
      const queriesPerHourRaw = document.getElementById('queriesPerHour').value.trim();
      parsedQueriesPerHour = parseInt(queriesPerHourRaw, 10);

      if (isNaN(parsedQueriesPerHour) || parsedQueriesPerHour <= 0) {
        alert('Please enter a valid positive number for queries per hour.');
        return;
      }

      settingsData.totalQueries = parsedTotalQueries;
      settingsData.queriesPerHour = parsedQueriesPerHour;

      // Call Python to save the settings (if running inside pywebview/UI)
      try {
        if (typeof pywebview !== 'undefined' && pywebview.api && pywebview.api.save_settings) {
          pywebview.api.save_settings(settingsData).catch(err => alert('Save settings failed:', err));
        } else if (typeof pywebview !== 'undefined' && pywebview.api) {
          // Fallback: call even if function presence is unknown (pywebview proxies calls)
          pywebview.api.save_settings(settingsData);
        } else {
          alert('pywebview API not available; settings not sent to Python.');
        }
      } catch (e) {
        alert('Error while calling save_settings:', e);
      }
        
      // Close the settings panel after saving
      settingsPanel.classList.remove('open');
    });
  }
});