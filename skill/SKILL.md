---
name: mcprobe
description: 诊断麦当劳中国 MCP 的 Token、网络、Streamable HTTP 协议、35 项工具契约与只读调用状态，生成脱敏 HTML/JSON 体检报告。用于“麦当劳 MCP 连不上”“菜单工具为空”“tools/list 异常”“为什么某个麦当劳 Skill 失效”等排查。
---

# McProbe · 麦门接口体检站

## 何时使用

当用户出现以下任一需求时使用：

- 麦当劳 MCP 客户端显示连接失败；
- `tools/list` 为空、工具数量不对或缺少某个工具；
- 菜单、活动、账户等只读能力突然不可用；
- 刚换 Token，需要验证是否真的生效；
- 开发麦当劳 MCP Skill，需要在发布前跑一次 smoke test；
- 需要把故障证据发给别人，但不想泄露 Token、订单、地址或券码。

## 安全规则

1. 永远不要把用户的 Token 写进对话、命令参数、输出、文件名或报告。
2. 只从环境变量 `MCD_MCP_TOKEN` 读取 Token。
3. 默认不调用任何可写工具：
   - 不下单；
   - 不取消订单；
   - 不领券；
   - 不抽奖；
   - 不兑换积分；
   - 不新增地址。
4. 用户没有明确要求账户检查时，不加 `--account`。
5. 不把 WARN 擅自说成服务故障；工具新增通常只是契约变化。

## 执行流程

### 1. 先确认环境

只检查变量是否存在，不打印变量值：

```powershell
if ($env:MCD_MCP_TOKEN) { "MCD_MCP_TOKEN=SET" } else { "MCD_MCP_TOKEN=NOT_SET" }
```

如果未配置，告诉用户去 <https://open.mcd.cn/mcp> 获取，并让用户在当前终端设置：

```powershell
$env:MCD_MCP_TOKEN = "粘贴自己的 Token"
```

不要让用户把 Token 发给你。

### 2. 运行实时体检

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m mcprobe doctor `
  --out reports/mcprobe-live.html `
  --json-out reports/mcprobe-live.json
```

用户明确需要验证账户读取时，才添加：

```powershell
--account
```

### 3. 解读结果

按以下顺序解释：

1. 先报整体 PASS / WARN / FAIL；
2. 先说第一个 FAIL，再提其他 WARN；
3. 给出报告中“建议动作”；
4. 把 HTML 报告路径给用户；
5. 需要开发者复现时，再附 JSON 路径。

不要复述全部 35 个工具，除非用户要求审计契约。

### 4. 无 Token 时

可以运行离线演示，但必须明确它不是实时状态：

```powershell
python -m mcprobe doctor --demo `
  --out reports/mcprobe-demo.html `
  --json-out reports/mcprobe-demo.json
```

## 常见诊断

| 报告结果 | 解释 |
|---|---|
| `未找到 MCD_MCP_TOKEN` | 只差凭证，不是服务坏了 |
| `HTTP 401/403` | Token 无效、过期或没有对应权限 |
| `HTTP 404` | 地址或传输方式错误，应使用 `https://mcp.mcd.cn` |
| `HTTP 429` | 请求太频繁，等待后再试 |
| `连接失败` | DNS、代理、TLS、防火墙或系统时间问题 |
| `工具比基线少` | 服务契约变化或账号能力被裁剪 |
| `工具比基线多` | 服务新增工具，报告为 WARN，不代表失败 |
| `query-my-account 失败` | 账户读取权限或登录态问题；报告不含余额 |

## 输出要求

最终回复至少包含：

- 整体状态；
- 最关键的一个原因；
- 一条可执行修复动作；
- HTML 报告的绝对路径。

如报告为实时 PASS，说明“本次连接、35 项工具契约与只读探针均通过”，不要说“永久正常”。
