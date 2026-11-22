# 发布清单

从「代码写完」到「别人能下载用」，按顺序过一遍。

## 发版前

- [ ] 版本号只在一处定义（`APP_VER`），打包脚本和 Release tag 都从它读，不手抄
- [ ] `python -c "import ast; ast.parse(open('app.py',encoding='utf-8').read())"` 过语法
- [ ] 前端 `node --check ui/*.js` 过语法（没有 node 就用人眼 + 浏览器 Console）
- [ ] 空数据跑一遍：删掉 `config.json`、清空数据目录，能正常初始化而不是崩溃
- [ ] 非法输入跑一遍：接口传 `null` / `""` / 超大数 / 不存在的文件名，返回 4xx 且提示是人话
- [ ] 关掉网络跑一遍：不依赖网的功能全部可用
- [ ] 看一眼 `git status`：日志、`config.json`、`_build/`、`vendor/` 都不该出现在待提交里

## 打包

```bash
# 1. 每次用新的 distpath，避开旧目录被占用/被删不掉的问题
pyinstaller --noconfirm --distpath out5 --workpath work5 app.spec

# 2. 冒烟：起进程 → 等端口 → 打接口 → 收尸
python scripts/smoke.py out5/app/app.exe --browser

# 3. 打 zip（保持「解压出一个同名文件夹」的结构，别把文件散在根目录）
python scripts/mkzip.py 1.2.0 ./release
```

体积预期：纯标准库 + 内置 ffmpeg 大约 45–55 MB zip。突然翻倍通常是误把 `__pycache__`、日志或整个数据目录打进去了。

## 发布

```bash
gh release create v1.2.0 "release/AppName-v1.2.0-win64.zip" \
  --title "v1.2.0 · 一句话说清这版最重要的一件事" \
  --notes "## 修了什么
- ...
## 加了什么
- ...
## 去掉了什么
- ..."

# 必须校验：资产真的在、大小对
gh release view v1.2.0 --json assets --jq '.assets[] | "\(.name) \(.size)"'
```

发布说明三条原则：

1. **标题说结果，不说过程**——「图库缩略图修复」比「fix: tile src」有用
2. **用用户能懂的话**——「图片全灰」比「proxy 404」有用，根因放在正文第二层
3. **「去掉了什么」也要写**——删功能同样是变更，不写用户会以为坏了

## 发布后

- [ ] 未登录状态访问 Release 页和 zip 直链，都是 200（`curl -sIL -o /dev/null -w "%{http_code}"`）
- [ ] README 顶部「下载最新版」链接指向 `releases/latest`，不要写死版本号
- [ ] 更新 README 的变更点（新增功能要出现在功能列表里，删掉的功能要从列表里删）
- [ ] 如果仓库要转公开：确认 `.gitignore` 覆盖了配置/日志/二进制，并用
      `git log --all --diff-filter=A --name-only -- 敏感文件` 反查历史里没混进去过
- [ ] 公开仓库要配 `LICENSE`（MIT 最省事），否则别人不能合法复用
- [ ] README 配一张真机截图，比十行功能描述有效；截图记得裁掉本地路径

## 版本号约定

`主.次.修`：

- 修 bug → 修（1.2.1 → 1.2.2）
- 加功能、改动已有行为 → 次（1.2.x → 1.3.0）
- 数据格式不兼容、需要迁移 → 主（1.x → 2.0.0）

只有一个用户的小工具也别省这一步，回滚时全靠它。
