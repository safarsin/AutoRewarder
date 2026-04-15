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
});