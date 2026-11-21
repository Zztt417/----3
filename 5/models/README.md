# 本地嵌入模型

默认目录：`models/bge-small-zh-v1.5`，供 `mybot/long_memory.py` 使用。

- 模型：`BAAI/bge-small-zh-v1.5`（中文，512 维）
- `model.safetensors` 约 96 MB
- 模型已放在项目内时，克隆后无需额外配置即可运行
- 若模型文件未提交，克隆后运行 `python setup_memory.py` 下载到项目内模型目录
- 若仓库使用 Git LFS 管理模型，克隆后执行 `git lfs pull`

> 注意：model.safetensors 约 91.4 MiB。GitHub 单文件上限为 100 MiB，可直接提交；若托管平台限制更严格，建议使用 Git LFS，或只提交 setup_memory.py 让使用者克隆后自行下载。
