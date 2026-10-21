# MyBot Web UI

Vue 3 + Vite 前端，调用同目录项目中的 FastAPI Agent 服务。

## 开发模式

先从项目根目录启动 API：

```powershell
python api_server.py
```

再启动前端：

```powershell
cd ui
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。Vite 会把 `/api` 代理到 `http://127.0.0.1:8000`。

## 生产构建

```powershell
cd ui
npm install
npm run build
```

构建产物位于 `ui/dist`。仓库中已包含一份构建好的 `dist`，克隆后直接启动 FastAPI 即可；修改前端源码后重新执行 `npm run build`。重启 `python api_server.py` 后，FastAPI 会自动托管该目录，直接访问 `http://127.0.0.1:8000` 即可。

## 环境变量

复制 `.env.example` 为 `.env.local` 可覆盖 API 地址：

```text
VITE_API_BASE_URL=http://127.0.0.1:8000
```

留空时使用相对路径 `/api`。