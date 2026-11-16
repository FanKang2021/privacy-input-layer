from pilayer.focus import classify_target, looks_like_url, url_host

CFG = {
    "ai_targets": {
        "processes": ["Qoder CN.exe", "Claude.exe"],
        "browsers": ["chrome.exe", "msedge.exe"],
        "url_patterns": ["chatgpt.com", "claude.ai"],
    }
}


def test_process_whitelist():
    assert classify_target("qoder cn.exe", None, CFG)
    assert not classify_target("notepad.exe", None, CFG)


def test_browser_url_match():
    assert classify_target("chrome.exe", "https://chatgpt.com/c/abc", CFG)
    assert classify_target("msedge.exe", "https://sub.claude.ai/", CFG)
    assert not classify_target("chrome.exe", "https://github.com/foo", CFG)
    assert not classify_target("chrome.exe", None, CFG)


def test_non_browser_url_ignored():
    assert not classify_target("notepad.exe", "https://chatgpt.com", CFG)


def test_title_patterns():
    cfg = {"ai_targets": {"browsers": ["chrome.exe"], "title_patterns": ["ChatGPT", "Claude"]}}
    assert classify_target("chrome.exe", None, cfg, "ChatGPT - Google Chrome")
    assert classify_target("chrome.exe", None, cfg, "Claude - Tabbit")
    assert not classify_target("chrome.exe", None, cfg, "GitHub - Tabbit")


def test_newtab_title_rule():
    cfg = {
        "ai_targets": {
            "browsers": ["tabbit browser.exe"],
            "newtab_chat_browsers": ["Tabbit Browser.exe"],
            "newtab_titles": ["新标签页", "New Tab"],
        }
    }
    from pilayer.focus import ForegroundWatcher
    fw = ForegroundWatcher(cfg, lambda ai: None)
    assert fw._is_newtab_chat("tabbit browser.exe", "", "新标签页 - Tabbit")
    assert not fw._is_newtab_chat("tabbit browser.exe", "https://github.com", "GitHub - Tabbit")
    assert not fw._is_newtab_chat("chrome.exe", "", "新标签页 - Chrome")


def test_looks_like_url():
    assert looks_like_url("chatgpt.com/c/x")
    assert looks_like_url("https://claude.ai")
    assert not looks_like_url("1.2")
    assert not looks_like_url("192.168.1.50")
    assert not looks_like_url("hello world")
    assert not looks_like_url("v1.2")


def test_url_host():
    assert url_host("https://ChatGPT.com/c/x") == "chatgpt.com"
    assert url_host("chatgpt.com/c/x") == "chatgpt.com"


def test_chat_input_markers():
    from pilayer.focus import _CHAT_INPUT_RE
    assert _CHAT_INPUT_RE.search("Ask Telly a question")
    assert _CHAT_INPUT_RE.search("AI helper")
    assert _CHAT_INPUT_RE.search("prompt")
    assert _CHAT_INPUT_RE.search("想聊点什么?")
    assert not _CHAT_INPUT_RE.search("Search")
    assert not _CHAT_INPUT_RE.search("Address and search bar")
    assert not _CHAT_INPUT_RE.search("用户名")


def test_model_picker_markers():
    from pilayer.focus import _MODEL_RE
    for name in ("spark-x2.6", "Qwen3.8-Max", "Qwen4-Max", "gpt-4o", "claude-sonnet-4", "Gemini 2.5"):
        assert _MODEL_RE.search(name), name
    for name in ("Search", "提交", "用户名", "Star"):
        assert not _MODEL_RE.search(name), name


def test_ai_disclaimer_markers():
    from pilayer.focus import _AI_DISCLAIMER_RE
    assert _AI_DISCLAIMER_RE.search("内容由 AI 生成，请核实重要信息")
    assert _AI_DISCLAIMER_RE.search("AI helper")
    assert _AI_DISCLAIMER_RE.search("Powered by inkeep")
    assert not _AI_DISCLAIMER_RE.search("本文讨论了 AI 生成内容在法律实践中的若干问题与展望")

def test_newtab_title_with_browser_suffix():
    from pilayer.focus import ForegroundWatcher
    cfg = {
        "ai_targets": {
            "newtab_chat_browsers": ["Tabbit Browser.exe"],
            "newtab_titles": ["新标签页", "New Tab"],
        }
    }
    fw = ForegroundWatcher(cfg, lambda ai: None)
    assert fw._is_newtab_chat("tabbit browser.exe", "搜索，或输入网址", "新标签页 - Tabbit")
    assert fw._is_newtab_chat("tabbit browser.exe", "", "新标签页 - Tabbit")
    assert not fw._is_newtab_chat("tabbit browser.exe", "https://github.com", "GitHub - Tabbit")
