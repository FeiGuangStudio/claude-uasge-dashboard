# 右上角动画 + DONE 提示音 / 5h 重置提示音

> 默认动画和声音素材来源于 https://pixabay.com/ 免费素材网站。

## 发给别人用：自带 seed 机制

把 `claude用量监控.exe` 发给朋友，他双击运行的瞬间，exe 旁边会自动生成两个文件夹：

```
朋友放 exe 的位置/
├── claude用量监控.exe
├── asset/
│   ├── gif/        ← 默认桌宠 GIF
│   └── sound/      ← 默认提示音
└── claude_widget_config.json   ← 存认证 / 偏好
```

之后他想换素材：

- 直接把自己喜欢的 GIF 拖进 `asset/gif/` → 打开 widget 的 SETTINGS 面板，桌宠下拉里会出现新文件，hover 即预览
- 把 mp3 / wav 拖进 `asset/sound/` → SETTINGS 里完成音 / 重置音下拉就能选，hover 即试听

**seed 行为**：仅当目标子目录"不存在"时才复制（首次运行）。之后 widget 永远不再覆盖用户文件，删/加/改都尊重用户管理。如要恢复默认，删掉对应子文件夹再启动 exe 即可。

---

## 资源目录

- `asset/gif/u_mey4kjj5ww-angry-2498.gif` — **V3 默认桌宠**（`MASCOT_PRIMARY_NAME`），找不到时回退到目录里任意 `.gif`
- `asset/gif/*.gif` — 桌宠候选池，SETTINGS 下拉里都能选
- `asset/sound/dragon-studio-new-notification-3-398649.mp3` — **V3 默认完成音**（`DONE_SOUND_DEFAULT`）
- `asset/sound/universfield-new-notification-09-352705.mp3` — **V3 默认重置音**（`RESET_SOUND_DEFAULT`）
- `asset/sound/*.mp3` / `*.wav` — 提示音池

> 换素材：直接把新文件拖进 `asset/gif/` 或 `asset/sound/`，然后在 widget 的 **S（SETTINGS）面板**用下拉框选中并保存即可——桌宠会立刻热重载，声音下次触发就用新文件，不用重启 widget。下拉里 hover 文件名会**即时预览 GIF / 试听音效**。

### 桌宠 GIF 行为

- 独立 Toplevel 悬浮窗，背景透明，置顶
- 基准 bbox **100×100**，按 `cfg.mascot_scale`（0.4–3.0，默认 1.0）等比缩放
- **左键拖动**：直接按住桌宠拖到任意位置；松手时把"相对主窗左上角的偏移"写入 `claude_widget_config.json` 的 `mascot_off_x` / `mascot_off_y`
- **右键 → 缩放滑块**（紧凑模式禁用）：
  - 无边框透明小菜单，PIL 风格滑块 + 黄色百分比文字
  - 范围 20%–200%，步进 10%
  - 滑块菜单 Y 贴桌宠**顶部**（不够空间降级到下方）
  - 缩放时**桌宠右上角不动**，向左下扩展（`anchor="top_right"`）
  - **关闭菜单：屏幕任意位置右键** / Esc（全屏 `-alpha=0.01` 覆盖层捕获 `<Button-3>`）
  - 关闭时把 scale 写入 `cfg.mascot_scale`
- **跟随主窗**：
  - 拖动主窗 → 桌宠按记录的偏移同步移动
  - **紧凑模式**：双击进紧凑时 x **强制贴屏右边**（屏宽 - 桌宠宽），y 用进入紧凑前那一刻的桌宠 y；紧凑模式下桌宠**不可拖动、不可缩放**（光标变默认箭头，右键无反应）；恢复正常时按偏移回到变紧凑前的位置
  - 没拖过时给的默认偏移就是"贴主窗外部右上角、向下 3 像素"
- **显示开关**：SETTINGS 面板「桌宠」label 后的 pill 开关，OFF 时立刻销毁桌宠 Toplevel；状态保存到 `cfg.mascot_show`
- 想恢复默认偏移 / 缩放：删 `mascot_off_x` / `mascot_off_y` / `mascot_scale` 后重启

### SETTINGS 面板的预览窗

- 打开"桌宠"下拉后，鼠标 **悬停** 在某个 GIF 文件名上，主窗右边会贴出一个 **H×H 透明正方形预览悬浮窗**（H = 主窗高度，目前 180）播放对应 GIF
- 鼠标在下拉里上下滑动，预览跟着切换；点击选中或关掉下拉时预览窗销毁
- 预览窗背景透明（GIF 透明像素直接透出桌面），不再有黑底
- **完成音 / 重置音 下拉同样支持 hover 试听**：鼠标滑过某个音频文件名就单次播放该文件；滑到下一项会立刻停掉上一段开始播新的；关掉下拉时停止

## 触发逻辑

| 事件 | 行为 |
|---|---|
| 启动后 | 在保存位置或主窗外部右上角悬浮播放 `asset/gif/<cfg.mascot_file>` |
| 拖动桌宠 | 落地位置写入 cfg，后续启动直接用该位置 |
| 拖主窗 / 紧凑模式 | 若桌宠未被拖过则跟随；已拖过则原地不动 |
| 5-hour 倒计时归零 | 播放 `asset/sound/<cfg.reset_sound>` 并触发一次刷新 |
| 监测到 `temp/claude_done.flag` 文件出现 | 播放 `asset/sound/<cfg.done_sound>`，然后删除该 flag |

播放使用 Windows MCI（`winmm.mciSendStringW`），原生支持 mp3/wav，不需要额外依赖。

## Claude Code DONE 提示音配置

widget 监听项目根目录下的 `temp/claude_done.flag` 文件，mtime 变化即触发提示音。推荐用 Claude Code 的 Stop hook 调用 V3 自带的 `claude_done_flag.ps1`，避开 hook 命令字符串里的中文/空格路径转义难题。

### 方案一：调用项目自带 ps1（推荐）

V3 项目根目录有 `claude_done_flag.ps1`：

```powershell
$d = 'C:\Users\vickyi\Desktop\授权文件夹\claude code usage\temp'
New-Item -ItemType Directory -Force $d | Out-Null
New-Item -ItemType File -Force (Join-Path $d 'claude_done.flag') | Out-Null
```

在 `~/.claude/settings.json` 的 `Stop` 钩子里追加：

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "shell": "powershell",
            "command": "powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\\Users\\vickyi\\Desktop\\授权文件夹\\claude code usage\\claude_done_flag.ps1\"",
            "async": true,
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

之后每次 Claude Code 任务结束（Stop hook 触发），ps1 touch 一下 flag → widget 约 800ms 内轮询到 → 播 done 提示音 → 自动删 flag。

### 方案二：内联命令

如果不想用 ps1 中转：

```json
{
  "type": "command",
  "command": "powershell -NoProfile -Command \"New-Item -ItemType File -Force -Path 'C:/Users/vickyi/Desktop/授权文件夹/claude code usage/temp/claude_done.flag' | Out-Null\""
}
```

PowerShell 单引号包裹的字符串里中文 / 空格无需转义。

## 关闭某项功能

- 想关 GIF 动画：清空 `asset/gif/` 文件夹（没有任何 .gif 时不会创建悬浮窗）
- 想关 done 提示音：移除上面 settings.json 的 Stop hook
- 想关 5h 重置提示音：在 SETTINGS 里把"重置音"换成不存在的文件名，或把 `_tick_overlay` 里那行 `play_sound_async` 注释掉（MCI 找不到文件时会 fallback 到一次 MessageBeep）
