# Launch kit

Ready-to-post copy for the v0.3.0 launch. Keep claims honest: Windows-only,
local-only, keyboard-paste injection, menu-paste outside AI yields placeholders.

## Show HN

**Title:** Show HN: Privacy input layer – mask secrets before they reach any AI client (Windows, local-only)

**Body:**
> I built privacy-input-layer because proxy-style masking only covers custom
> baseUrl endpoints — platform-native models (Qoder/Cursor/Claude desktop, web
> chats) speak private protocols you can't hook. But every client reads data
> through the same OS doors: clipboard paste, screenshot paste, file upload.
>
> So the guard lives at the input boundary:
> - Focus-aware: masks only while an AI conversation client is foreground; your
>   normal copy/paste is untouched.
> - Zero-config detection: UIA signatures (model picker controls, "AI helper"
>   labels, chat inputs) + curated client list + self-learning. Works on web
>   widgets and installed page-as-app windows too.
> - Paste injection: Ctrl+V is intercepted and the masked text is injected as
>   keystrokes — the clipboard never holds our plaintext (Win+V history / cloud
>   clipboard safe).
> - Rules: CN phone/ID/bankcard (checksum+BIN), PEM/PGP keys, URI userinfo
>   passwords, assignment-style secrets, internal URLs, vendor tokens, IPv4/6.
> - Reversible: DPAPI-encrypted local mapping, one-key restore, 30-day TTL.
> - No network, no telemetry, MIT.
>
> Repo: https://github.com/FanKang2021/privacy-input-layer
> Demo GIF in README. 88 tests + CI on windows / macos / ubuntu(Xvfb) + node.
>
> Known limits: Windows only; image OCR races sub-second pastes after window
> switches; unsigned exe may trip EDR (allowlist guidance in SECURITY.md).

## 掘金 / V2EX / 少数派

**标题：** 给所有 AI 客户端加一层"隐私输入膜"：粘贴即脱敏，原文不出本机（开源）

**大纲：**
1. 痛点：中转站/平台自带模型都能看到你的明文；代理式脱敏覆盖不了原生模型
2. 思路转换：不拦网络，拦 OS 输入边界（剪贴板/粘贴/上传）
3. 零配置识别三层：UIA 签名 / 精选名单 / 自学习（含网页内嵌 widget、桌面化网页）
4. 注入式粘贴：剪贴板零明文，Win+V 历史与云剪贴板不再旁路
5. 安全设计：DPAPI 静态加密、TTL、日志脱敏、懒还原（对照 PCI/OWASP/GDPR）
6. 实测矩阵 + demo GIF + 已知限制诚实清单
7. 邀请：客户端名单 PR、规则 PR、NER/扩展路线图

## Reddit r/privacy / r/selfhosted

Title: "I open-sourced a local-only clipboard guard that masks secrets before
they enter ANY AI client (including native desktop models)" — link repo, lead
with the no-network guarantee and the DPAPI/TTL design, invite audits.

## Positioning table (use in posts/README discussions)

| | proxy-style masking | enterprise DLP | privacy-input-layer |
|---|---|---|---|
| Platform-native models | no | agent-level only | yes |
| Web chats / widgets | no | partial | yes |
| Local-only, no cloud | yes | no | yes |
| Reversible restore | yes | rare | yes |
| Clipboard-history safe | n/a | n/a | yes (injection) |
| Install friction | baseUrl config | agent rollout | double-click exe |

## Checklist

- [ ] demo GIF visible in README above the fold
- [ ] release exe attached (unsigned; SmartScreen note in SECURITY.md)
- [ ] CI badge green
- [ ] post Show HN weekday morning US; 掘金/V2EX same day CN evening
- [ ] reply to every issue/PR within 48h during launch week