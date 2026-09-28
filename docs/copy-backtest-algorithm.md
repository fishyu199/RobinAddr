# 罗宾汉链现货跟单回测算法

## 口径

每个地址先去重，再按时间选取最新 5,000 条买卖，最后按时间从旧到新回放。只接受普通现货 `buy` 和 `sell`；Polymarket 的 `REDEEM`、`MERGE`、`SPLIT` 不进入罗宾汉链计算。

默认复制原脚本的数量口径：跟单账户买卖与目标地址相同的代币数量，而不是维持相同的美元支出。

- 目标买入价：`P`
- 跟单买入价：`P × 1.025`
- 目标卖出价：`P`
- 跟单卖出价根据该代币距离最近一次买入的时间确定：
  - 10 秒内（含 10 秒）：`P × 0.80`，卖出滑点 20%。
  - 超过 10 秒至 30 秒（含 30 秒）：`P × 0.85`，卖出滑点 15%。
  - 超过 30 秒至 60 秒（含 60 秒）：`P × 0.90`，卖出滑点 10%。
  - 超过 60 秒：`P × 0.975`，卖出滑点 2.5%。

因此，目标地址用 100 美元买入 100 枚，并在超过 60 秒后以 120 美元卖出时：

- 目标 PnL：`120 - 100 = 20`
- 跟单 PnL：`120 × 0.975 - 100 × 1.025 = 14.5`

这里没有 Polymarket 的每份最高 1 美元限制，也没有赎回或结算收入。

## 盈亏记账

每个代币合约独立建立 FIFO 持仓批次：

- 已实现盈亏 = 卖出净收入 − 卖出数量对应的 FIFO 成本。
- 未实现盈亏 = 当前持仓价值 − 剩余 FIFO 成本。
- 总盈亏 = 已实现盈亏 + 未实现盈亏。
- 跟单未平仓默认按 `当前价格 × 0.975` 估值，表示此刻卖出时仍会承受 2.5% 的卖出价差。

如果有独立的实时价格，可在回测时传入；否则使用这 5,000 条记录中该代币最后一次成交价。

## 5000 条窗口的边界

窗口第一条记录可能是卖出，但它对应的买入发生在窗口之前。由于缺少历史成本，算法不会把该卖出当成零成本利润，而会将超出窗口内可用持仓的数量记为 `unmatched_sell_quantity`。结果中的 `starting_inventory_unknown` 会提示该地址存在这种情况。

GMGN 卖单若提供 `buy_cost_usd`，算法另外输出 `target_reported_realized_pnl_usd`，作为包含窗口前成本信息的参考值；它与严格按窗口重放得到的 PnL 分开呈现。

## GMGN 数据格式

罗宾汉链不沿用 Polymarket 的 `conditionId / asset / size / usdcSize`。适配层读取 GMGN `wallet_activity` 的原生字段：

| 统一字段 | GMGN 字段 |
| --- | --- |
| 买卖方向 | `event_type` |
| 代币合约 | `token.address` |
| 代币符号 | `token.symbol` |
| 代币数量 | `token_amount` |
| 成交美元金额 | `cost_usd` |
| 成交美元价 | `price_usd`，缺失时用 `cost_usd / token_amount` |
| 已售部分历史成本 | `buy_cost_usd` |
| 可选手续费 | `gas_usd + dex_usd` |
| 排序时间 | `timestamp` |

`transferIn`、`transferOut` 等非交易事件不作为跟单信号；它们会记录在数据质量统计里。GMGN `wallet_activity` 单页最多读取 50 条，分页返回的 `next` 会作为下一页 `cursor`，直到取满 5,000 条或没有下一页。客户端不做固定等待；仅在服务端实际返回 429 时，按 `X-RateLimit-Reset` 动态等待并重试一次。

## 主要输出

- `target`：目标地址的买入额、卖出额、已实现/未实现/总 PnL、ROI、胜率等。
- `copy`：相同数量、买入价增加 2.5%，并按持有时间应用 2.5%–20% 卖出滑点后的同组指标。
- `pnl_gap_usd`：目标总 PnL − 跟单总 PnL。
- `pnl_retention_ratio`：跟单总 PnL ÷ 目标总 PnL。
- `per_token`：每个代币的持仓和盈亏。
- `equity_curve`：逐笔回放后的目标/跟单累计 PnL。
- `trade_results`：逐笔目标价、跟单价、成交数量、手续费和已实现盈亏。

中位持仓时间仍会计算并展示，但不再参与评分。Recent 20 Copy Loss 在目标近期 PnL 为正且损耗率超过 30% 时扣 10 分；无论损耗率多高，该项最多扣 10 分。

## 运行

读取已保存的 GMGN `wallet_activity` JSON：

```bash
python -m copybot.cli --input wallet_activity.json --output result.json
```

直接读取一个罗宾汉链地址的最新 5,000 条 GMGN 活动：

```bash
python -m copybot.cli --wallet 0xYourWallet --output result.json
```

真实请求通过 `GMGN_API_KEY` 环境变量读取 API key，代码与输出文件都不保存密钥：

```bash
export GMGN_API_KEY='gmgn_...'
```

如果已经运行过 `gmgn-cli config --apply`，脚本也会自动读取 `~/.config/gmgn/.env`，无需重复导出。

手续费默认不计，可使用命令行参数单独开启或设置。

生成 Telegram HTML 报告：

```bash
python -m copybot.cli --wallet 0xYourWallet --format telegram --lang zh-CN
```

也提供了与旧 Polymarket 脚本相同调用习惯的入口：

```bash
python run_robinhood.py 0xYourWallet zh-CN
```

其中 `analyze_wallet(wallet_address, ...)` 返回 `report_text` 和 `metrics` 两部分。
