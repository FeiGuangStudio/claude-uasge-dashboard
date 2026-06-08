# 更新日志

## V3（当前）

### 重置提示音触发逻辑修复

- **问题**：原先 `reset_sound` 只在 5-Hour 用量打满（≥99.5%）进入"重置倒计时覆盖层"后归零的瞬间播放；若重置发生时用量未打满，倒计时定时器从未启动，提示音不会响。
- **修复**：在 `_done()` 中比对每次刷新返回的 `five_reset_at`，发现该时间戳比上一次往后跳了 >60 秒（说明服务端开启了新的 5 小时窗口），即播放一次 `reset_sound`，与用量是否打满解耦。
- 新增实例字段 `_last_five_reset_at` 缓存上一次的重置时间。

### 凭证安全加固

- **DPAPI 加密落盘**：`session_key` / `org_id` 写入 `claude_widget_config.json` 前用 Windows DPAPI（`CryptProtectData`）加密 + base64 编码，存为 `session_key_enc` / `org_id_enc` 字段
  - 密文绑定**当前 Windows 用户账户**，别人拷走 JSON 无法解密
  - 旧版明文键自动迁移：首次启动检测到明文字段会立即加密回写
  - 解密失败（如换账户）时自动清空字段，UI 提示重新填
  - 仅用 Python 标准库 `ctypes`（调用 `crypt32.dll`），无新增依赖
- **ACCOUNT 面板 sessionKey 输入框**：
  - 取消明文显示入口（移除眼睛切换图标），始终圆点 `•`
  - 屏蔽 Ctrl+C / Ctrl+X / Ctrl+Insert / Shift+Delete / 右键菜单 / 中键粘贴（Tk 默认 show=• 仅影响渲染，剪贴板仍是明文，必须显式拦截）
- **ACCOUNT 面板两个输入框**：未激活边框由 `BORDER` 改为 `WHITE`

### 文档 / 资源清理

- 移除从 Clawd on Desk 项目复制的所有 GIF / 提示音 / LICENSE / NOTICE 文件
- 删除 `docs/Clawd on Desk/` 文件夹及 README / animation_and_sound.md 中的相关致谢、说明

### 桌宠

- **默认 GIF 改为** `u_mey4kjj5ww-angry-2498.gif`（`MASCOT_PRIMARY_NAME` 常量）
- **显示开关**（SETTINGS）：「桌宠」label 后的 pill 风格小开关，默认 ON 显示 `GREEN`、OFF 显示灰；
  - 状态写入 `cfg.mascot_show`，保存时立即应用（`_apply_mascot_visibility`：创建或销毁桌宠 Toplevel）
- **右键缩放滑块**：右键桌宠弹出无边框透明滑块菜单
  - 范围 20%–200%，步进 10%
  - PIL 风格滑槽（圆角 / 黄色已选段 / 白色 knob，与 SETTINGS 刷新频率一致）
  - 透明背景（`-transparentcolor BG`），没有方形外框
  - Y 坐标贴桌宠**顶部**（不够空间降级到底部）
  - 缩放时**桌宠右上角不动**（`anchor="top_right"`），向左下扩展
  - 关闭：**屏幕任意位置右键** / Esc（全屏透明覆盖层捕获）
  - 关闭时把 scale 写入 `cfg.mascot_scale`
  - 紧凑模式禁用（右键无反应）
- 缩放范围常量：`MASCOT_SCALE_MIN = 0.4`，`MASCOT_SCALE_MAX = 3.0`

### 提示音

- **默认完成音改为** `dragon-studio-new-notification-3-398649.mp3`（`DONE_SOUND_DEFAULT`）
- **默认重置音改为** `universfield-new-notification-09-352705.mp3`（`RESET_SOUND_DEFAULT`）
- 新增 `claude_done_flag.ps1`（项目根目录）：Claude Code Stop hook 调用即可 touch `temp/claude_done.flag`，避开 hook 命令字符串里的中文/空格路径转义难题

### SETTINGS 面板

- 完成音 / 重置音从「并排两列同一行」拆为**独立两行**
- 三个下拉框（桌宠 / 完成音 / 重置音）**统一 `ST_combo_x` / `ST_combo_w`**，左右像素级对齐
- 左侧标签统一宽度 `ST_LBL_W = 56`，左对齐
- 字体逻辑回归：标签 9 bold / OptionMenu 8 / 保存 10 bold / 恢复默认 9 bold / 警告 8
- 按钮↔上方行间距 = 26px，按钮↔警告 = 8px（视觉留白明显）

### 面板关闭

- **关闭方式：屏幕任意位置右键单击**（全屏透明 `-alpha=0.01` 覆盖层捕获 `<Button-3>`），或按 Esc
- 原「左键空白处关闭」已移除（容易误触保存输入框）
- **关闭动画一气呵成**：
  1. widgets 由四角向中心收缩（`_do_panel_anim(1.0, 0.0)`）
  2. 背景层由全屏收缩到中心（`_do_bg_anim(1.0, 0.0)`）
  3. 销毁 Toplevel → 回到主窗口
- 修复了上一版的「先到空白页 → 需要再点一次才回主窗口」两步关闭 bug

### 配置文件新增键

| 键 | 含义 |
|---|---|
| `mascot_show` | 桌宠是否显示（bool，默认 true）|
| `mascot_scale` | 桌宠缩放比（float 0.4–3.0，默认 1.0）|
| `session_key_enc` / `org_id_enc` | DPAPI 加密 + base64 后的凭证（替代旧的明文 `session_key` / `org_id`）|

---

## V2

### 可分发 exe

- 资源分流：图标走打包内，桌宠 GIF / 提示音走 **exe 同目录的 `asset/gif/` `asset/sound/`**
- **首次运行 seed**：exe 首次启动检测到 exe 旁没有 `asset/gif` 或 `asset/sound` 时，自动从打包内复制默认素材出来；之后永远不再覆盖
- 用户直接拖文件进对应文件夹即可在 SETTINGS 里选用，无需重打包

### 桌宠 + 提示音

- 资产目录搬到 `asset/` 下：`asset/icon/` `asset/gif/` `asset/sound/`
- 右上角桌宠：100×100 透明 Toplevel，可拖动、保存相对主窗偏移；紧凑模式下 x 固定贴屏右边、y 用进入紧凑前的 y、不可拖动
- Claude Code DONE 提示音：监听 `temp/claude_done.flag` 文件，配合 Stop hook 触发
- 5h 用尽倒计时归零提示音
- SETTINGS 面板：刷新频率 + 桌宠下拉 + 完成音/重置音并排下拉
  - 桌宠下拉 hover：主窗右边出 H×H 透明预览悬浮窗，即时播放该 GIF
  - 声音下拉 hover：单次试听，切到下一项立刻停掉上一段；关下拉自动停止
- MCI 播放走短路径（`GetShortPathNameW`）规避中文 + 空格路径

### V2 基础

- 可配置刷新频率的设置面板
- 5h 用尽倒计时遮罩
- 双击切到屏幕右边的紧凑模式
- 面板控件 100% 不透明、背景层 80% 透明
- 每次启动屏幕居中
