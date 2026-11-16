# privacy-input-layer

**AI 隐私输入层**：在内容进入任何 AI 客户端之前完成脱敏。不挑平台、不挑模型——平台自带模型、网页版、桌面端全部通用，因为拦截发生在数据进入客户端**之前**，而不是网络出站时。

全部本地运行：规则引擎 + 本地 OCR + 本地 sqlite 映射，原文永远不离开你的机器。

## 为什么需要它

代理式脱敏（改 baseUrl 的反向代理）只能覆盖自定义端点，对平台自带模型无效——私有协议没有可改的入口。但任何客户端拿数据都绕不开三个 OS 级入口：**剪贴板粘贴、截图粘贴、文件上传**。守住这些入口，就守住了所有平台。

## 覆盖能力

| 场景 | 效果 | 用户操作 |
|---|---|---|
| 复制文本 → 粘贴进任意 AI 客户端 | 自动替换为占位符（手机号/身份证/银行卡/邮箱/PEM 私钥/IPv4/API 令牌/自定义词） | 零 |
| 复制 AI 回复（含占位符） | 自动还原为真实值 | 零 |
| 截图 / 复制图片 → 粘贴 | OCR 定位敏感文字区域，像素打码（不可逆） | 零 |
| 复制文件 → 粘贴上传 | 剪贴板中的文件路径自动替换为脱敏副本 | 零 |
| 右键文件 → 发送到 → 脱敏副本 | 生成 `.masked` 副本供上传 | 一步 |
| AI 产出的文件回填 | `restore-file` 将占位符换回真实值 | 一条命令 |

支持文件：`txt / md / csv / json / log / docx / xlsx`。

## 快速开始

```bash
python -m venv .venv
.venv\Scripts\activate        # PowerShell: .venv\Scripts\Activate.ps1
pip install -e .            # 文本 + 文件脱敏
pip install -e .[image]     # 加上图片 OCR 打码
pilayer run                 # 托盘常驻，开始守卫
pilayer install-sendto      # 可选：右键「发送到 -> 脱敏副本」
```

不想开终端：双击项目根目录的 `启动守卫.bat`（无控制台窗口）。

托盘图标：蓝色 = 守卫开启，灰色 = 暂停。单击图标切换开关。

### CLI

```bash
pilayer mask-text "张三的手机 13800138000"     # -> 张三的手机 [PHONE_1]
pilayer restore-text "手机 [PHONE_1]"          # -> 手机 13800138000
pilayer mask-file report.docx                  # -> report.masked.docx
pilayer restore-file ai-output.docx            # -> ai-output.restored.docx
pilayer stats                                  # 本地映射统计
```

占位符与原文的映射保存在 `%APPDATA%/pilayer/mappings.db`（sqlite，仅本机）。同一原文在多轮对话中复用同一占位符，保证 AI 上下文一致。

## 配置

`%APPDATA%/pilayer/config.yaml`（首次运行自动生成，模板见 [config.example.yaml](config.example.yaml)）：

- `guard.*`：文本 / 图片 / 文件路径 / 自动还原 / 通知 各自开关
- `rules.custom_keywords`：自定义敏感词（人名、项目代号等），如 `["张三", "Project-X"]`
- `image.min_score` / `image.fill`：OCR 置信度阈值与打码颜色

## 工作原理

1. **事件监听**：`AddClipboardFormatListener` 消息窗口，复制瞬间触发，非轮询。
2. **规则引擎**：手机号 / 身份证（校验位验证）/ 银行卡（Luhn 校验）/ 邮箱正则 + 自定义词，毫秒级，挡在粘贴之前。
3. **防自触发**：写入剪贴板后记录序列号，跳过自己引发的事件，避免脱敏↔还原死循环。
4. **图片**：剪贴板 DIB → RapidOCR 定位文字行 → 命中规则则整行像素填充。
5. **文件**：复制文件粘贴时生成脱敏副本并替换剪贴板路径；docx 段落级处理（PII 可能跨 run 拆分），xlsx 仅处理字符串单元格、保留公式。

## 已知限制

- **仅 Windows**（macOS / Linux 在路线图）。
- 图片打码粒度为 OCR 文字行，会连带遮盖同行的非敏感文字（宁多勿漏）。
- 触发脱敏重写剪贴板时会清空富文本格式（HTML/RTF），只保留纯文本/位图——这是为了防止客户端从 HTML 格式里读到原文。
- 复制→粘贴间隔极短（<100ms）时存在竞态窗口；规则引擎足够快，实测正常手速无感。
- 文件**上传后**客户端直接读磁盘，用户态无法透明拦截，因此文件走"脱敏副本"一步操作；pdf 暂不支持。
- 人名等无规则特征的 PII 首版靠 `custom_keywords`，NER 模型在路线图。
- 截图打码不可逆：打码后的图片不含原文，这正是目的。

## 路线图

- [ ] NER 本地模型识别人名 / 地址 / 机构名
- [ ] pdf 脱敏副本
- [ ] macOS（NSPasteboard 监听）/ Linux
- [ ] 浏览器扩展：网页端输入框直接拦截
- [ ] 映射过期与清理策略

## 隐私声明

本工具不发起任何网络请求。OCR 模型本地推理，映射存本地 sqlite。卸载即删除 `%APPDATA%/pilayer` 即可清除全部数据。

## License

MIT