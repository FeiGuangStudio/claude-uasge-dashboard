需要看源码的看.pyw文件
需要直接使用的去releases（右边）下载EXE文件


# Claude 用量监控悬浮组件 V3

一个运行在 Windows 桌面的悬浮小工具，实时监控你的 claude.ai 用量配额。

以双圆环的形式直观展示 5 小时窗口用量与本周累计用量，始终置顶、无需切换页面。内置桌宠 GIF 动画、任务完成提示音（支持 Claude Code Stop hook 联动）、DPAPI 凭证加密存储，以及带动画效果的账户与设置面板。

✦ 功能亮点
- 双环实时显示 5-Hour / Weekly 利用率，色阶随负载自动切换（绿 / 橙 / 红）
- 5-Hour 用尽时内圆叠加倒计时，不足 5 分钟自动切秒级读秒
- 双击主窗切换紧凑模式（贴屏右侧，50% 缩放）
- 桌宠 GIF 悬浮窗，支持右键缩放滑块（20%–200%）与拖拽定位
- Claude Code Stop hook 联动：任务结束自动播放提示音
- sessionKey / orgId 以 Windows DPAPI 加密落盘，密文绑定当前账户
- 设置面板支持刷新频率、桌宠开关、GIF 与提示音热替换
- 账户 / 设置面板均可通过屏幕任意位置右键单击（或 Esc）一键关闭

---

A Windows desktop overlay widget for real-time monitoring of your claude.ai usage quotas.

Displays your 5-hour window usage and weekly cumulative usage as dual animated rings — always on top, no browser tab required. Ships with a mascot GIF, task-completion sound alerts (with Claude Code Stop hook integration), DPAPI-encrypted credential storage, and animated account & settings panels.

✦ Highlights
- Dual-ring display of 5-Hour / Weekly utilization with color thresholds (green / amber / red)
- Countdown overlay when the 5-hour quota is exhausted; switches to second-by-second readout under 5 minutes
- Double-click to toggle compact mode (docked to screen right, 50% scale)
- Floating mascot GIF with right-click scale slider (20%–200%) and drag-to-position support
- Claude Code Stop hook integration: plays a chime automatically when a task finishes
- Credentials (sessionKey / orgId) encrypted on disk via Windows DPAPI, bound to the current user account
- Settings panel supports live hot-swap of refresh interval, mascot visibility, GIF, and alert sounds
- Right-click anywhere on screen (or press Esc) to dismiss the account / settings panel instantly

---

Windows 桌面悬浮小工具，实时显示 claude.ai 的 **5 小时窗口用量** 和 **本周用量**，双环呈现，始终置顶。

V3 在 V2 基础上新增：

- **桌宠显示开关**：SETTINGS 面板「桌宠」标签后多了 pill 风格开关（默认 ON=GREEN），可临时隐藏桌宠
- **桌宠右键缩放滑块**：右键桌宠弹出无边框透明滑块（20%–200%，步进 10%），实时缩放，右上角锚定不动
- **SETTINGS 重排版**：完成音 / 重置音拆成两行，三个下拉框（桌宠/完成音/重置音）左右像素级对齐
- **关闭面板：屏幕任意位置右键单击**（全屏透明捕获层）或 Esc
- **一气呵成的关闭动画**：widgets 由四角向中心收缩 → 背景层全屏收缩到中心 → 自动回到主窗口
- 默认素材换成 `u_mey4kjj5ww-angry-2498.gif` + `dragon-studio-new-notification-3-398649.mp3` + `universfield-new-notification-09-352705.mp3`
- 配套 `claude_done_flag.ps1` 自动写 flag，Stop hook 一行命令即可
- **凭证安全加固**：`session_key` / `org_id` 在 `claude_widget_config.json` 中以 **Windows DPAPI** 加密形态存储（绑定当前 Windows 账户）；ACCOUNT 面板的 sessionKey 输入框不再提供明文切换，且禁止复制 / 剪切 / 右键

---

## 文件结构

```
claude code usage/
├── claude_usage_widget_V3.pyw      # V3 主程序（当前）
├── claude_usage_widget_V2.pyw      # V2（保留对照）
├── claude_usage_widget.pyw         # V1（保留对照）
├── claude_done_flag.ps1            # Stop hook 调用脚本，touch claude_done.flag
├── claude_widget_config.json       # 自动生成：认证 + 频率 + 桌宠/声音/偏移/缩放/显示
├── asset/                          # 资源目录
│   ├── icon/                       # 界面 PNG 图标
│   ├── gif/                        # 桌宠 GIF 池
│   └── sound/                      # 提示音池（mp3 / wav）
├── temp/                           # 临时（含 Stop hook 写入的 claude_done.flag）
├── docs/                           # 项目文档
│   ├── CHANGELOG.md
│   └── animation_and_sound.md
├── 启动悬浮组件.bat
├── 调试运行.bat
└── README.md
```

---

## 快速开始

### 1. 安装 Python

前往 https://python.org 下载安装，勾选 **Add Python to PATH**。首次运行会自动安装 `requests` 和 `Pillow`。

### 2. 获取认证信息

**sessionKey**：浏览器登录 claude.ai → Settings → Usage → F12 → Network → F5 → 搜索 `sessionKey`，复制 `sk-ant-...` 的值。

**Organization ID**：claude.ai → 右上角头像 → Settings → Account，复制 Organization ID。

### 3. 启动

双击 `启动悬浮组件.bat`，首次启动若无认证信息，账户面板自动弹出。填两个字段点保存即可。

---

## 主窗口（300×180）

```
┌──────────────────────────────────┐
│  🅒  20:53 更新          👤  ⚙  ✕ │
│     ╭────╮          ╭────╮       │
│     │5-Hour│        │Weekly│     │
│     │ 85% │        │  7% │       │
│     │1h56m│        │35h06m│      │
│     ╰────╯          ╰────╯       │
└──────────────────────────────────┘
```

每次启动窗口都居中。右上角图标：账户（橙）/ 齿轮（绿）/ ✕（白），悬停变色。

- **左环单击** = 立即刷新数据（光标会变手型 + 显示大刷新图标）
- **双击主窗** = 切到屏幕右边的紧凑模式（仅显示 5-Hour 环，整体 50%、文字额外放大 20%），再次双击复原
- **5-Hour 用尽倒计时**：左环利用率 ≥ ~100% 且未到重置时间时，内圆叠 80% 遮罩 + 大字号倒计时；< 5 分钟自动切 `M:SS` 读秒；归零播提示音并刷新

环色阈值：< 50% 绿、< 75% 橙、否则红。

---

## ACCOUNT 面板（👤）

带两阶段动画的覆盖面板：背景层圆角矩形从中心扩散展开 → 控件由中心向四角插值到最终位置。

- **sessionKey**：始终密文 `•` 显示，**无眼睛切换**，**禁止复制/剪切/右键菜单**（防止明文外泄）+ ⓘ 悬停提示
- **Organization ID**：默认密文 `•`，点眼睛可切显隐 + ⓘ 悬停提示
- 两个输入框**未激活时边框为白色**，激活时变橙色（YELLOW）
- **保存** 按钮：写入配置 + 触发一次刷新
- **关闭**：屏幕任意位置 **右键** 或按 **Esc**（左键空白点击已废弃）
- 关闭动画：widgets 四角→中心收缩 + 背景中心收缩，一次触发完整播放

---

## SETTINGS 面板（⚙）

```
┌─────────────────────────────────────┐
│  刷新频率  ●━━━○━━━━  5  分钟       │
│  桌宠      [ON ] ▼ u_mey4kjj5ww...gif │
│  完成音           ▼ dragon-studio...mp3│
│  重置音           ▼ universfield-...mp3│
│                                     │
│       [恢复默认]    [保  存]        │
│  ⚠ 低于 3 分钟可能导致提取数据失败    │
└─────────────────────────────────────┘
```

### 行布局

- **刷新频率**：滑块 1–30 分钟（默认 5），PIL 超采样圆角滑槽 + 白色 knob
- **桌宠**：「桌宠」标签 + pill 显示开关 + GIF 下拉
  - 显示开关：默认 ON = `GREEN`，OFF = 灰；保存时写 `mascot_show`，立即应用（创建 / 销毁悬浮窗）
  - GIF 下拉 hover：主窗右边出 H×H 透明预览悬浮窗循环播放该 GIF
- **完成音 / 重置音**：独立两行，下拉 hover 单次试听，切到下一项立刻 stop 上一段；下拉关闭也 stop
- 三个下拉框（桌宠 / 完成音 / 重置音）**统一 `ST_combo_x` / `ST_combo_w`** → 左右像素级对齐
- **底部按钮**：恢复默认（左）+ 保存（右），与重置音行有 26px 视觉留白；与底部警告有 8px 间距

### 操作

- **关闭面板**：屏幕任意位置 **右键** 或 **Esc**（左键空白点击已废弃，避免误触）
- **保存**：写 `refresh_min` / `mascot_file` / `mascot_show` / `done_sound` / `reset_sound`；重置周期定时器；桌宠 / 显示状态若变了自动热重载
- **恢复默认**：所有值回默认（5 分钟 + 默认 GIF + 默认两个声音 + 显示 ON），需点保存才落盘
- **关闭动画**：与 ACCOUNT 一致 —— widgets 由四角→中心 + 背景由全屏→中心，一次完成

---

## 桌宠

- 独立透明 Toplevel，置顶，**100×100 等比缩放**为基准 bbox（缩放 = `mascot_scale`）
- 默认位置：主窗外部右上角向下 3px
- **左键拖动**：拖到任意位置，松手把 `(gx-mx, gy-my)` 写入 cfg.`mascot_off_x/y`；之后桌宠按这个偏移跟随主窗
- **右键 → 缩放滑块**（紧凑模式禁用）：
  - 滑块菜单 Y 贴桌宠顶部（不够空间降级到底部）
  - 范围 20%–200%，步进 10%，PIL 风格滑槽 + 黄色已选段 + 白色 knob
  - 缩放时**桌宠右上角不动**（`anchor="top_right"`），向左下扩展
  - 透明背景（无方框），值文字黄色
  - 关闭方式：**屏幕任意位置右键** 或 **Esc**
  - 关闭时把 `scale` 写入 `cfg.mascot_scale`
- **紧凑模式**：双击主窗变紧凑时，桌宠 x 固定贴屏右边、y 保持进入紧凑前的 y；紧凑模式下桌宠不可拖、不可缩放（右键无反应）

---

## 提示音

| 事件 | 行为 |
|---|---|
| Claude Code Stop hook 写入 `temp/claude_done.flag` | 播 `asset/sound/<cfg.done_sound>` 后删 flag |
| 5-hour 倒计时归零 | 播 `asset/sound/<cfg.reset_sound>` + 触发一次刷新 |

默认：`done_sound = dragon-studio-new-notification-3-398649.mp3`，`reset_sound = universfield-new-notification-09-352705.mp3`。

播放走 Windows MCI（`winmm.mciSendStringW`），原生支持 mp3 / wav，无需额外依赖；中文 / 空格路径用 `GetShortPathNameW` 转 8.3 短路径再喂给 MCI 规避问题。

### Stop hook 配置（done 提示音）

V3 提供 `claude_done_flag.ps1`，在 `~/.claude/settings.json` 的 `Stop` 钩子追加一条：

```json
{
  "type": "command",
  "shell": "powershell",
  "command": "powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\\Users\\vickyi\\Desktop\\授权文件夹\\claude code usage\\claude_done_flag.ps1\"",
  "async": true,
  "timeout": 5
}
```

之后每次 Claude Code 任务结束 → Stop hook → ps1 touch flag → widget 约 800ms 内轮询到 → 播 done 提示音 → 删 flag。

---

## 数据来源

```
GET https://claude.ai/api/organizations/{org_id}/usage
Cookie: sessionKey=...
Anthropic-Client-Platform: web_claude_ai
```

响应字段：

- `five_hour.utilization` / `five_hour.resets_at` → 左环（5-Hour）
- `seven_day.utilization` / `seven_day.resets_at` → 右环（Weekly）

按 SETTINGS 的刷新频率（默认 5 分钟）自动刷新；左环单击手动刷新。

---

## 配置文件 `claude_widget_config.json`

| 键 | 含义 |
|---|---|
| `session_key_enc` / `org_id_enc` | 认证（**Windows DPAPI 加密 + base64**，绑定当前 Windows 账户）|
| `refresh_min` | 自动刷新分钟（默认 5）|
| `mascot_file` | 桌宠 GIF 文件名（默认 `u_mey4kjj5ww-angry-2498.gif`）|
| `mascot_show` | 桌宠是否显示，bool（默认 `true`）|
| `mascot_scale` | 桌宠缩放比，float 0.4–3.0（默认 `1.0`）|
| `mascot_off_x` / `mascot_off_y` | 桌宠相对主窗左上角偏移 |
| `done_sound` / `reset_sound` | 提示音文件名 |

---

## 主要常量

```python
# 颜色
BG     = "#4B4D52"   # 透明色键，勿改
PANEL  = "#111827"
GREEN  = "#22d3a5"
YELLOW = "#D97757"
RED    = "#ef4444"

# 尺寸
RO = 60                       # 环外半径
W, H = RO*4 + RO_GAP*3, RO*2 + RO_GAP*3   # 300, 180

# 桌宠
MASCOT_BBOX_W = MASCOT_BBOX_H = 100
MASCOT_SCALE_MIN = 0.4
MASCOT_SCALE_MAX = 3.0
MASCOT_PRIMARY_NAME = "u_mey4kjj5ww-angry-2498.gif"
DONE_SOUND_DEFAULT  = "dragon-studio-new-notification-3-398649.mp3"
RESET_SOUND_DEFAULT = "universfield-new-notification-09-352705.mp3"

# 刷新
REFRESH_MIN_DEFAULT = 5
REFRESH_MIN_MIN, REFRESH_MIN_MAX = 1, 30
REFRESH_MIN_WARN = 3

# 动画
ACCOUNT_BG_ANIM_STEPS    = 14
ACCOUNT_PANEL_ANIM_STEPS = 14
ACCOUNT_ANIM_MS          = 11
ACCOUNT_PANEL_ALPHA      = 0.80

# 紧凑
COMPACT_SCALE = 0.5
COMPACT_W = COMPACT_H = int(RO * 2 * COMPACT_SCALE) + 4   # 64
```

---

## 常见问题

**Q：启动后没出现悬浮窗** → 用 `调试运行.bat` 看控制台报错。

**Q：⚠ 401 / 403** → sessionKey 过期，重新拿一次。

**Q：⚠ 404** → Organization ID 填错，Network 面板重新确认。

**Q：完成音不响** → 检查 `~/.claude/settings.json` 的 Stop hook 是否调用了 `claude_done_flag.ps1`；手动跑一次 ps1 看是否能生成 `temp/claude_done.flag`。

**Q：桌宠看不见** → 检查 SETTINGS 桌宠开关是否被关掉了，或 `cfg.mascot_show` 是否为 `false`。

**Q：桌宠太大 / 太小** → 右键桌宠 → 拖滑块。或编辑 `cfg.mascot_scale`。

**Q：紧凑模式为什么是方形不是圆形？** → Windows tk 的 `-transparentcolor` 是硬色键、不支持抗锯齿，圆形面板边缘会出杂色。紧凑模式采用实心方形保证边缘干净。

---

## 依赖

| 包 | 用途 |
|---|---|
| `requests` | claude.ai API |
| `Pillow` | PIL 超采样渲染（环 / 滑槽 / 遮罩 / 桌宠帧）|
| `tkinter` | GUI（Python 内置）|

首次运行 .pyw 时缺失会自动 pip 安装。

---

## 凭证安全说明

- `session_key` / `org_id` 写盘前用 **Windows DPAPI**（`CryptProtectData`）加密，再 base64 编码存入 `claude_widget_config.json` 的 `session_key_enc` / `org_id_enc` 字段
- DPAPI 密文绑定到**当前 Windows 用户账户**，他人拷走 JSON 到另一台机器 / 另一个 Windows 账户**无法解密**
- 程序运行时全自动解密到内存，调用方无感知；无需用户输入主密码
- ACCOUNT 面板的 sessionKey 输入框：仅圆点显示、不可复制 / 剪切 / 右键菜单 / 中键粘贴
- 若换 Windows 账户 / 重装系统导致解密失败，对应字段自动清空，重新填一次即可

仅使用 Python 标准库 `ctypes`（调用 `crypt32.dll`），无新增依赖。

---

## 致谢

默认动画和声音素材来源于 https://pixabay.com/ 免费素材网站。

Claude 品牌名称、UI 配色与 logo 商标归 Anthropic, PBC. 所有。
