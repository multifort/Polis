---
description: 基于模板起草一条新的架构决策记录(ADR)
---
依据 `docs/decisions/0000-adr-template.md` 起草一条新的 ADR：

1. 扫描 `docs/decisions/`，取现有最大编号 +1 作为 `NNNN`（四位，补零）。
2. 文件名 `docs/decisions/NNNN-<kebab-标题>.md`，按模板填写：背景 / 选项 / 决定 / 后果，状态先 `proposed`，日期取今天。
3. 主题：$ARGUMENTS
4. 写完在 `docs/README.md` 的 ADR 表格追加一行索引。
5. 不要臆造背景，缺信息就向我确认。
