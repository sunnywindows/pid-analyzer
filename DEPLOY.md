# 在 Render 部署 P&ID 分析工具

此目录包含应用源码及有效的 `Dockerfile`。原始压缩包的源码位于压缩包根目录，上传仓库时应确保 `app.py`、`Dockerfile`、`requirements.txt`、`render.yaml` 在同一层级。

## 本次部署设置

- 服务类型：Web Service，运行环境：Docker。
- 计算方案：Free；免费方案的资源和使用限制以 Render 控制台为准。
- 区域：Oregon（美国）。部署区域本身不能保证 OpenAI 可用，仍需验证服务端实际网络。
- 环境变量：`PID_MODE=ai`，先验证本次需要的 AI 图纸分析功能。
- 健康检查路径：`/`。
- Root Directory：留空，前提是这些文件位于仓库根目录。
- Dockerfile Path：`./Dockerfile`。
- Docker Command：留空，使用 Dockerfile 中的启动命令。
- 应用读取平台提供的 `PORT`，监听 `0.0.0.0`；默认端口 8000。

免费实例只有 512 MB 内存，空闲后会休眠。大型图纸、多页 PDF 或本地 OCR 可能超出资源限制。若要恢复双引擎界面，把 `PID_MODE` 改为 `both`；选择付费方案前先确认费用。

## GitHub 与 Render

1. 在自己的 GitHub 账号下建立仓库。建议使用私有仓库，先检查样例图纸和源码是否适合上传。
2. 将此目录中的源码文件提交到仓库；不要上传 API Key、`.env`、本地验证依赖或日志。
3. 登录 Render，选择 New → Web Service，连接上述仓库。
4. 根据“本次部署设置”填写表单，确认使用 Free 计算方案后创建服务。
5. 等待构建和部署完成；以控制台实际结果为准，不保证固定的构建时间。
6. 打开 Render 给出的 HTTPS 地址，确认首页可加载。

也可用 Render 的 Blueprint 创建入口读取 `render.yaml`，该文件已经指定 Docker、Free、Oregon、`PID_MODE=ai` 和首页健康检查。

## 验证 OpenAI 连接

必须从实际部署服务的运行环境验证网络。本机能否连接 OpenAI 不能代替这项检查。

如部署方案允许进入服务终端，可以先不带密钥执行：

```sh
curl --connect-timeout 10 --max-time 20 -i https://api.openai.com/v1/models
```

收到来自 OpenAI 的缺少认证的 HTTP 401 响应，说明该次请求已连通到接口；这不代表密钥、模型权限、额度及实际图片分析都已通过。免费方案不提供服务终端时，可通过应用提交一次小图片分析来检查，并查看任务结果和部署日志。

接着在网页中选择 OpenAI，填写自己的 API Key，Base URL 使用 `https://api.openai.com/v1`，模型名称先使用 `gpt-6-luna`。提交一张允许上传到模型服务的图纸，再验证设备、仪表、管线和 Excel 导出。

## 密钥与运行限制

- 此版本仍采用原来的方式：用户在自己的浏览器中填写 Key，提交到应用后端，再由后端发出 API 请求；未增加共享的服务器密钥。
- 密钥不需要提交到 GitHub，也不要写入 Dockerfile、部署描述或日志。
- 应用没有读取 `OPENAI_API_KEY` 环境变量的逻辑，单独在 Render 填这个变量不会生效。若以后改为使用共享的服务器密钥，应同时考虑访问控制与模型服务地址限制。
- 分析任务暂存在单个进程内，服务重启或休眠后任务结果会丢失；当前部署应保持单实例、单工作进程。重要结果请及时导出。
- Docker 化只解决程序及依赖打包问题，不能消除部署平台的出站网络限制，也不保证模型服务在每个地区均可使用。

## 验证范围

本地验证不使用真实 API Key，也不产生模型费用。模拟模型响应只能验证上传、任务处理、结果解析、请求参数和导出流程。真实 OpenAI 调用与 Docker 云端构建必须在 Render 部署后另行确认。

官方资料：

- https://render.com/docs/web-services
- https://render.com/docs/free
- https://render.com/docs/compute-plans
- https://developers.openai.com/api/docs/guides/latest-model
