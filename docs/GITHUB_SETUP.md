# 发布到 GitHub

仓库建议名称：`weibo-mood-radar`，可见性：Public，开源许可：MIT。

## 首次发布

本地代码、测试、README 示例与工作流都准备完成后，使用已登录的 GitHub CLI，在仓库根目录运行：

```console
gh auth login
gh repo create weibo-mood-radar --public --source=. --remote=origin --push
```

若尚未初始化本地 Git 仓库，先执行：

```console
git init -b main
git add .
git commit -m "feat: publish weekly and monthly Weibo emotion reports"
```

GitHub CLI 由 [GitHub 官方提供](https://cli.github.com/)。也可在 GitHub 网页新建一个空的公开仓库，再按网页给出的命令添加远程和推送。

## 启用真实数据更新

1. 在仓库 Settings → Secrets and variables → Actions 添加 `DATA_SOURCE_URL`；有鉴权时添加 `DATA_SOURCE_TOKEN`。
2. 数据接口需返回[约定格式](DATA_SOURCE.md)的每日历史快照。它不是当前热门榜 URL。
3. 确保默认分支包含 `.github/workflows/reports.yml`，并允许 GitHub Actions 执行。
4. 工作流声明 `contents: write`，用于提交 README 和报告。若默认分支有保护规则禁止机器人推送，需要将报告发布改为 PR 流程。
5. 到 Actions → Update weekly and monthly reports → Run workflow 执行首次更新，检查运行日志及自动提交。
6. 首次真实更新成功后，修改 README 顶部“真实数据接口尚未配置”的说明。

每周一北京时间 09:17 更新周报，每月 1 日北京时间 09:37 更新上月报告。GitHub 调度可能延迟，Fork 的定时任务需要在 Actions 页面启用；无仓库活动超过 60 天可能自动停用。详见 [GitHub 官方 schedule 文档](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

## 失败处理

数据源未配置时，工作流正常更新日期与“暂无数据”状态，并保留已有报告。已配置接口但鉴权失败、JSON 格式无效或重算覆盖率下降时，任务失败并保留已有报告。通过 Actions 检查具体步骤，修复后点击 Re-run jobs。重跑相同数据不会产生重复报告。推送冲突时也应重跑，以最新默认分支重新生成。

本项目不依赖本地电脑常开；定时任务在 GitHub runner 上执行。接口提供方仍需每天保留历史快照。
