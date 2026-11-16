chrome.storage.local.get({ mappings: [], enabled: true, allSites: false }, (st) => {
  document.getElementById("count").textContent = st.mappings.length;
  document.getElementById("enabled").checked = st.enabled;
  document.getElementById("allSites").checked = st.allSites;
});
document.getElementById("enabled").addEventListener("change", (e) => {
  chrome.storage.local.set({ enabled: e.target.checked });
});
document.getElementById("allSites").addEventListener("change", (e) => {
  chrome.storage.local.set({ allSites: e.target.checked });
});
document.getElementById("clear").addEventListener("click", () => {
  chrome.storage.local.set({ mappings: [] }, () => {
    document.getElementById("count").textContent = 0;
  });
});