/* DOM-layer paste masking: complements the OS-level guard for web chat inputs.
   Config is cached in memory so preventDefault happens synchronously inside
   the paste event (async storage reads would miss the default-action window). */
(() => {
  const HOSTS = [
    "chatgpt.com", "claude.ai", "gemini.google.com", "copilot.microsoft.com",
    "poe.com", "perplexity.ai", "chat.deepseek.com", "kimi.com", "moonshot.cn",
    "tongyi.aliyun.com", "yiyan.baidu.com", "chatglm.cn", "doubao.com",
    "metaso.cn", "chat.qwen.ai", "grok.com", "chat.mistral.ai",
    "huggingface.co", "google.com",
  ];
  const cfg = { enabled: true, allSites: true };
  chrome.storage.local.get({ enabled: true, allSites: true }, (st) => {
    cfg.enabled = st.enabled;
    cfg.allSites = st.allSites;
  });
  chrome.storage.onChanged.addListener((changes) => {
    for (const k of Object.keys(changes)) {
      if (k in cfg) cfg[k] = changes[k].newValue;
    }
  });
  const host = location.hostname;
  const listed = HOSTS.some((h) => host === h || host.endsWith("." + h));

  function isChatInput(el) {
    if (!el) return false;
    if (el.tagName === "TEXTAREA") return true;
    if (el.isContentEditable) return true;
    return false;
  }

  function insertText(el, text) {
    if (el.tagName === "TEXTAREA" || (el.tagName === "INPUT" && el.type === "text")) {
      const s = el.selectionStart, e = el.selectionEnd;
      el.setRangeText(text, s, e, "end");
      el.dispatchEvent(new Event("input", { bubbles: true }));
    } else {
      document.execCommand("insertText", false, text);
    }
  }

  document.addEventListener("paste", (ev) => {
    if (!cfg.enabled || (!listed && !cfg.allSites)) return;
    const el = ev.target;
    if (!isChatInput(el)) return;
    const text = ev.clipboardData.getData("text/plain");
    if (!text) return;
    const r = PilayerRules.mask(text);
    if (!r.count) return;
    ev.preventDefault();
    ev.stopPropagation();
    insertText(el, r.text);
    chrome.storage.local.get({ mappings: [] }, (st) => {
      chrome.storage.local.set({ mappings: st.mappings.concat(r.entries).slice(-200) });
    });
  }, true);
})();