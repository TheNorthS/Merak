# 构建与发布

## 上传 GitHub

将 Merak 源码目录的内容作为仓库根目录：根目录直接包含 `package.json`、`pyproject.toml`、`README.md` 和 `.github/`。不要上传父目录的参考项目或整个科研工作区。

直接在现有源码目录提交即可，无需复制到另一个目录。`npm run export:source` 是可选的源码归档方式，生成 `release/Merak-Source-<版本>.zip`，排除个人配置、数据库、生成输出、依赖和 Git 历史；不影响原目录上传。

已有 Git 仓库和 `origin` 时，在包含 `package.json` 的原目录执行：

```powershell
git status --short
git remote -v
git add .
git diff --cached --stat
git diff --cached --name-only
git commit -m "release: prepare 0.1.1 public test release"
git push -u origin HEAD
```

`HEAD` 表示当前分支；推送前用 `git branch --show-current` 核对分支。若远端拒绝非快进推送，先核对并整合远端提交，不用强制推送覆盖历史。只有新建目录且尚无 Git 仓库时才执行 `git init -b main`；只有没有 `origin` 时才用 `git remote add origin <你的仓库地址>`。

提交前检查暂存文件列表。`.env`、数据库、用户设置、`output/`、依赖和安装包由 `.gitignore` 排除；`.env.example`、截图、锁文件和新增回归测试需要保留。忽略规则不影响已经跟踪的文件，不应使用 `git add -f` 上传本地配置或构建目录。

`release/` 中的安装器和校验文件作为 Release 附件单独上传，不随源码 push。若使用本地构建包，先提交对应源码；`build-info.json` 中 `working_tree_modified=true` 表示构建时包含未提交修复，不能将旧 HEAD 当作该包完整的来源。源码 ZIP 依赖 Git 文件清单，首次导出前须初始化仓库。

## 本地构建

使用 Windows x64、Node.js 22、Python 3.11，预留约 5 GB 构建空间：

```powershell
npm ci
python -m venv .venv
.venv/Scripts/Activate.ps1
.venv/Scripts/python -m pip install --require-hashes -r requirements.lock
npm run verify:local
npm run test:packaging
npm run build
npm run verify:package
npm run release:checksums
```

默认优先使用 `.venv/Scripts/python.exe`，或用 `MERAK_BUILD_PYTHON` 指定独立打包环境。锁文件包含应用、开发和 PyInstaller 依赖。

| 产物 | 内容 |
| --- | --- |
| `release/Merak-Setup-<版本>-x64.exe` | NSIS 安装程序 |
| `release/win-unpacked/` | 安装前烟测的完整应用 |
| `release/package-smoke.json` | 后端启动和认证烟测结果 |
| `release/desktop-smoke.json` | 安装版主窗口 WebSocket 连接、重连、子页面隔离与设置落库结果 |
| `release/resume-smoke.json` | 随包后端的图形生产者源码指纹及 13 个节点恢复指纹检查 |
| `release/SHA256SUMS.txt` | 安装包校验和 |
| `release/build-info.json` | 版本、源码状态和后端来源标识 |

打包只包含前端产物、Electron、随包 Python 环境及技能资源。用户数据存储于应用用户数据目录；卸载不会主动清除它们。

## GitHub CI/CD

所有 Actions 都由维护者手动启动。推送分支、Pull Request 和推送标签不触发构建或检查。

`local-verification.yml` 提供手动运行入口，也可被手动安装包工作流调用。
`windows-installer.yml` 仅使用 `workflow_dispatch`：先验证，再构建安装包、执行随包
检查、生成校验和并上传 Actions artifact。构建成功后，发布任务下载同次构建产物，
核对校验和、版本、构建提交与测试结果，然后自动创建标签并发布 GitHub Release。

发布步骤：

1. 同步 `package.json`、`package-lock.json`、`pyproject.toml`、`server/main.py`
   以及设置面板和状态栏中的显示版本；执行版本检查与桌面烟测确认一致。
2. 提交并推送源码。
3. 选择本地 `npm run build`，或进入 GitHub **Actions → Windows installer → Run workflow**，
   选择待构建分支，手动启动。工作流文件需要先存在于默认分支。
4. GitHub 构建成功后，`publish` 任务自动发布 `v<版本>`，安装包、SHA-256 文件和
   构建验证记录自动成为 Release 附件。标签指向这次构建的提交，不指向移动后的分支最新提交。
5. 进入仓库 **Releases** 下载发布结果。发布说明来自 `docs/RELEASE_<版本>.md`。
   当前公开测试版使用 **Pre-release** 标记并立即公开，不保留为草稿。

检查与构建任务使用仓库只读权限，只有 `publish` 任务申请 `contents: write`，使用
GitHub 自动提供的 `GITHUB_TOKEN`。不需要模型密钥、GPU 凭据或个人访问令牌。
已有同版本 Release 不会覆盖；重复运行会在发布步骤明确失败。若同名标签指向另一
提交也会拒绝发布。需要发布更新时提高版本号并新增对应发布说明。
只推送源码不会生成安装包；手动运行 Windows installer 才会构建并自动发布。
本地 `npm run build` 不会上传，需要自行创建 Release 和上传附件。

默认产物未签名。拥有签名证书后可按 electron-builder 配置仓库 Secrets，不要将证书提交到源码。未签名测试包可能显示发布者未知或 SmartScreen 提示。

## 验证边界

`npm run verify:package` 检查随包后端健康、桌面认证、内置技能和无科研数据的基础绘图，随后用空白用户目录启动打包后的桌面应用，验证 `file://` 主窗口的工作流 WebSocket 心跳与重连、子页面访问拒绝，以及首次保存设置确实写入 SQLite。检查需要本机 8011 端口空闲，结束后清理测试进程与临时目录。不调用真实模型、不启动科研流程、训练或远程任务。

桌面检查还会延迟身份验证响应，观察整个页面启动过程，确保不会闪现密码表单，并验证本地连接认证失败后提供重连入口、恢复后自动进入工作区。浏览器部署的登录保护由独立回归检查覆盖。

源码快照包含生产 Python 文件和 `.tmpl` 模板，模板同时按运行资源路径打包。发布检查使用随包解释器计算全部 13 个节点的恢复指纹，缺失或修改模板即阻止发布；检查不恢复任何真实科研流程。

首次分发建议在干净 Windows 机器安装，检查启动、模型连接、打开项目、PDF 预览及外部工具。本地构建成功不代表 GitHub 已执行，手动触发后的 Actions 日志才是远端证据。

同一 `appId` 的 NSIS 安装器会识别已有注册安装，即使选择另一安装目录，也可能先卸载旧程序；
更换目录不能当作并行隔离安装。安装测试应在独立 Windows 用户或虚拟机进行，或按升级流程
保留原安装包并确认目标目录。应用配置和科研项目须独立保留，测试后核对快捷方式与实际安装位置。

更新依赖后重新生成锁文件：

```powershell
uv pip compile pyproject.toml --extra dev --extra production --extra build --universal --generate-hashes --output-file requirements.lock
```

参考：[GitHub artifacts](https://github.com/actions/upload-artifact)、[GitHub CLI Release](https://cli.github.com/manual/gh_release_create)、[electron-builder](https://www.electron.build/)。

## 品牌与升级兼容

显示名称与发布文件前缀使用 `Merak`。内部命名统一为 `merak-ide`、`merak-ide-server`、`com.merak.ide`、`MERAK_*` 环境变量和 `.merak/` 项目记录。API 使用 `/api/merak`，桌面桥接使用 `window.merakIDE`，随包后端为 `merak-backend.exe`。

早期 ARIS 命名版本与 Merak 使用不同安装身份，不能假定配置会自动迁移。同为 Merak 应用身份的版本会按 NSIS 升级路径替换旧程序；安装器配置为保留用户数据，但升级前仍应备份配置和科研项目。不要把指定新安装目录当作并行保留旧版的方法。历史运行格式兼容性按版本说明判断，不要批量替换记录中的路径或哈希。

图标以 M 形轮廓与星芒表达北斗指引，几何定义在 `scripts/generate-icon.py`。运行 `python scripts/generate-icon.py` 生成深色 `resources/icon.svg`、白色 `resources/icon-light.svg` 和 Windows 多尺寸 ICO。界面图标随主题切换。

软件作者、MIT 许可证署名及 Windows 安装包版权信息统一使用 `NorthS Team`；第三方材料保留原有来源及许可证。
