"""Telegram HTML report renderer for Robinhood Chain copy backtests."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, fields
from html import escape
from typing import Any, Mapping

from .analytics import DEFAULT_REFERRAL_URL, build_legacy_metrics
from .models import BacktestConfig, BacktestResult


TELEGRAM_TEXT_LIMIT = 4_096

SUPPORTED_LANGUAGES = ("en", "zh-CN", "zh-TW", "ja", "ko", "ru", "fr", "ar", "pt", "es")

_I18N: dict[str, dict[str, str]] = {
    "en": {
        "title": "RobinCop AI Copyable Wallet", "copy_trade": "Copy Trade", "score": "Core Score",
        "target_pnl": "Target PnL", "copy_pnl": "Copy PnL", "copy_loss": "Copy loss",
        "retention": "PnL retention", "extra_loss": "Extra loss", "last_2d": "Last 2D share",
        "target_wr": "Target win rate", "token_wr": "Token win rate", "sell_wr": "Sell win rate",
        "pl_ratio": "Profit/loss", "trading_days": "Trading days", "required_cash": "Required cash",
        "cash_roi": "Copy cash ROI", "trades": "Trades", "tokens": "Tokens", "volume": "Volume",
        "buys_sells": "Buys/Sells", "open_tokens": "Open tokens", "winning_roi": "Winning ROI",
        "avg_buy": "Avg buy price", "avg_sell": "Avg sell price", "avg_cost": "Avg cost/token",
        "avg_target": "Avg target PnL", "avg_copy": "Avg copy PnL", "median_hold": "Median hold",
        "last_active": "Last active", "categories": "Token Platform Categories",
        "other_platforms": "Other platforms", "recent": "Recent 20 Tokens (Strict Replay)",
        "loss": "Loss", "win_rate": "WR", "older": "Older: ", "daily": "Daily Performance (Recent 14 Days)",
        "warning": "Some sells depend on pre-window inventory and are excluded from zero-cost profit.",
        "copy_with": "Copy with RobinCop AI", "footer": "Based on the latest {count} valid spot trades; buy +{buy}%, sell -{sell}%.",
        "token_table": "Token        Target      Copy        Cost", "daily_table": "Date  Trades Volume   Target    Copy",
        "days": "Days", "hours": "Hours", "mins": "Mins",
    },
    "zh-CN": {
        "title": "RobinCop AI 发现可跟单钱包", "copy_trade": "一键跟单", "score": "核心评分",
        "target_pnl": "目标地址 PnL", "copy_pnl": "模拟跟单 PnL", "copy_loss": "跟单损耗",
        "retention": "利润保留率", "extra_loss": "额外亏损金额", "last_2d": "近两日利润占比",
        "target_wr": "目标地址胜率", "token_wr": "代币胜率", "sell_wr": "卖出胜率",
        "pl_ratio": "盈亏比", "trading_days": "交易天数", "required_cash": "所需起始资金",
        "cash_roi": "跟单资金回报率", "trades": "有效买卖", "tokens": "交易代币", "volume": "交易量",
        "buys_sells": "买入/卖出", "open_tokens": "未平仓代币", "winning_roi": "盈利代币回报率",
        "avg_buy": "平均买入价", "avg_sell": "平均卖出价", "avg_cost": "平均投入/代币",
        "avg_target": "平均目标PnL", "avg_copy": "平均跟单PnL", "median_hold": "中位持仓时间",
        "last_active": "最后活动", "categories": "代币平台分类", "other_platforms": "其余平台",
        "recent": "最近 20 个代币（严格回放）", "loss": "损耗", "win_rate": "胜率", "older": "其余：",
        "daily": "每日表现（近 14 天）", "warning": "最近窗口之前存在持仓，无法匹配的卖出未作为零成本利润。",
        "copy_with": "使用 RobinCop AI 跟单", "footer": "基于最近 {count} 条有效现货买卖；买入价 +{buy}%，卖出价 -{sell}%。",
        "token_table": "代币          目标PnL     跟单PnL     本金", "daily_table": "日期  笔数   交易量    目标PnL   跟单PnL",
        "days": "天", "hours": "小时", "mins": "分钟",
    },
    "zh-TW": {
        "title": "RobinCop AI 發現可跟單錢包", "copy_trade": "一鍵跟單", "score": "核心評分",
        "target_pnl": "目標地址 PnL", "copy_pnl": "模擬跟單 PnL", "copy_loss": "跟單損耗",
        "retention": "利潤保留率", "extra_loss": "額外虧損金額", "last_2d": "近兩日利潤佔比",
        "target_wr": "目標地址勝率", "token_wr": "代幣勝率", "sell_wr": "賣出勝率",
        "pl_ratio": "盈虧比", "trading_days": "交易天數", "required_cash": "所需起始資金",
        "cash_roi": "跟單資金回報率", "trades": "有效買賣", "tokens": "交易代幣", "volume": "交易量",
        "buys_sells": "買入/賣出", "open_tokens": "未平倉代幣", "winning_roi": "盈利代幣回報率",
        "avg_buy": "平均買入價", "avg_sell": "平均賣出價", "avg_cost": "平均投入/代幣",
        "avg_target": "平均目標PnL", "avg_copy": "平均跟單PnL", "median_hold": "中位持倉時間",
        "last_active": "最後活動", "categories": "代幣平台分類", "other_platforms": "其他平台",
        "recent": "最近 20 個代幣（嚴格回放）", "loss": "損耗", "win_rate": "勝率", "older": "其餘：",
        "daily": "每日表現（近 14 天）", "warning": "最近窗口之前存在持倉，無法匹配的賣出未作為零成本利潤。",
        "copy_with": "使用 RobinCop AI 跟單", "footer": "基於最近 {count} 條有效現貨買賣；買入價 +{buy}%，賣出價 -{sell}%。",
        "token_table": "代幣          目標PnL     跟單PnL     本金", "daily_table": "日期  筆數   交易量    目標PnL   跟單PnL",
        "days": "天", "hours": "小時", "mins": "分鐘",
    },
    "ja": {
        "title": "RobinCop AI コピー可能なウォレット", "copy_trade": "コピートレード", "score": "コアスコア",
        "target_pnl": "対象PnL", "copy_pnl": "コピーPnL", "copy_loss": "コピー損失率", "retention": "利益維持率",
        "extra_loss": "追加損失", "last_2d": "直近2日利益割合", "target_wr": "対象勝率", "token_wr": "トークン勝率",
        "sell_wr": "売却勝率", "pl_ratio": "損益比", "trading_days": "取引日数", "required_cash": "必要開始資金",
        "cash_roi": "コピー資金ROI", "trades": "有効取引", "tokens": "取引トークン", "volume": "取引高",
        "buys_sells": "買い/売り", "open_tokens": "未決済トークン", "winning_roi": "勝利トークンROI",
        "avg_buy": "平均購入価格", "avg_sell": "平均売却価格", "avg_cost": "平均投資/トークン",
        "avg_target": "平均対象PnL", "avg_copy": "平均コピーPnL", "median_hold": "保有時間中央値",
        "last_active": "最終活動", "categories": "トークンプラットフォーム分類", "other_platforms": "その他",
        "recent": "直近20トークン（厳密リプレイ）", "loss": "損失率", "win_rate": "勝率", "older": "その他：",
        "daily": "日次実績（直近14日）", "warning": "期間前の在庫に依存する売却はゼロコスト利益から除外されています。",
        "copy_with": "RobinCop AIでコピー", "footer": "直近{count}件の有効な現物取引に基づく；買い +{buy}%、売り -{sell}%。",
        "token_table": "トークン       対象PnL      コピーPnL    投資", "daily_table": "日付  取引数  出来高    対象PnL   コピーPnL",
        "days": "日", "hours": "時間", "mins": "分",
    },
    "ko": {
        "title": "RobinCop AI 카피 트레이딩 지갑", "copy_trade": "카피 트레이드", "score": "핵심 점수",
        "target_pnl": "대상 PnL", "copy_pnl": "카피 PnL", "copy_loss": "카피 손실률", "retention": "수익 유지율",
        "extra_loss": "추가 손실", "last_2d": "최근 2일 수익 비중", "target_wr": "대상 승률", "token_wr": "토큰 승률",
        "sell_wr": "매도 승률", "pl_ratio": "손익비", "trading_days": "거래 일수", "required_cash": "필요 시작 자금",
        "cash_roi": "카피 자금 ROI", "trades": "유효 거래", "tokens": "거래 토큰", "volume": "거래량",
        "buys_sells": "매수/매도", "open_tokens": "미결제 토큰", "winning_roi": "수익 토큰 ROI",
        "avg_buy": "평균 매수가", "avg_sell": "평균 매도가", "avg_cost": "토큰당 평균 투자",
        "avg_target": "평균 대상 PnL", "avg_copy": "평균 카피 PnL", "median_hold": "중앙 보유 시간",
        "last_active": "최근 활동", "categories": "토큰 플랫폼 분류", "other_platforms": "기타 플랫폼",
        "recent": "최근 20개 토큰（엄격 재생）", "loss": "손실률", "win_rate": "승률", "older": "기타: ",
        "daily": "일일 실적（최근 14일）", "warning": "기간 이전 보유분에 의존한 매도는 무원가 수익에서 제외됩니다.",
        "copy_with": "RobinCop AI로 카피", "footer": "최근 {count}건의 유효 현물 거래 기준; 매수 +{buy}%, 매도 -{sell}%.",
        "token_table": "토큰          대상PnL      카피PnL     투자", "daily_table": "날짜  거래수  거래량    대상PnL   카피PnL",
        "days": "일", "hours": "시간", "mins": "분",
    },
    "ru": {
        "title": "RobinCop AI Кошелёк для копирования", "copy_trade": "Копировать", "score": "Оценка",
        "target_pnl": "PnL адреса", "copy_pnl": "PnL копии", "copy_loss": "Потери копии", "retention": "Сохранение прибыли",
        "extra_loss": "Доп. убыток", "last_2d": "Доля за 2 дня", "target_wr": "Винрейт адреса", "token_wr": "Винрейт токенов",
        "sell_wr": "Винрейт продаж", "pl_ratio": "Прибыль/убыток", "trading_days": "Торговые дни", "required_cash": "Начальный капитал",
        "cash_roi": "ROI капитала", "trades": "Сделки", "tokens": "Токены", "volume": "Объём",
        "buys_sells": "Покупки/Продажи", "open_tokens": "Открытые токены", "winning_roi": "ROI прибыльных токенов",
        "avg_buy": "Средняя покупка", "avg_sell": "Средняя продажа", "avg_cost": "Средняя сумма/токен",
        "avg_target": "Средний PnL адреса", "avg_copy": "Средний PnL копии", "median_hold": "Медиана удержания",
        "last_active": "Последняя активность", "categories": "Платформы токенов", "other_platforms": "Другие платформы",
        "recent": "Последние 20 токенов (точный повтор)", "loss": "Потери", "win_rate": "Винрейт", "older": "Остальные: ",
        "daily": "Дневная статистика (14 дней)", "warning": "Продажи из позиций до окна исключены из прибыли с нулевой себестоимостью.",
        "copy_with": "Копировать с RobinCop AI", "footer": "На основе последних {count} спотовых сделок; покупка +{buy}%, продажа -{sell}%.",
        "token_table": "Токен        Цель        Копия       Сумма", "daily_table": "Дата  Сделки Объём    Цель      Копия",
        "days": "Дн.", "hours": "Час.", "mins": "Мин.",
    },
    "fr": {
        "title": "RobinCop AI Portefeuille à copier", "copy_trade": "Copier", "score": "Score principal",
        "target_pnl": "PnL cible", "copy_pnl": "PnL copié", "copy_loss": "Perte de copie", "retention": "Profit conservé",
        "extra_loss": "Perte supplémentaire", "last_2d": "Part des 2 derniers jours", "target_wr": "Réussite cible", "token_wr": "Réussite jetons",
        "sell_wr": "Réussite ventes", "pl_ratio": "Gain/perte", "trading_days": "Jours de trading", "required_cash": "Capital requis",
        "cash_roi": "ROI du capital", "trades": "Transactions", "tokens": "Jetons", "volume": "Volume",
        "buys_sells": "Achats/Ventes", "open_tokens": "Jetons ouverts", "winning_roi": "ROI jetons gagnants",
        "avg_buy": "Prix d'achat moyen", "avg_sell": "Prix de vente moyen", "avg_cost": "Invest. moyen/jeton",
        "avg_target": "PnL cible moyen", "avg_copy": "PnL copié moyen", "median_hold": "Détention médiane",
        "last_active": "Dernière activité", "categories": "Plateformes des jetons", "other_platforms": "Autres plateformes",
        "recent": "20 derniers jetons (rejeu strict)", "loss": "Perte", "win_rate": "Réussite", "older": "Autres : ",
        "daily": "Performance quotidienne (14 jours)", "warning": "Les ventes liées à un stock antérieur sont exclues du profit à coût nul.",
        "copy_with": "Copier avec RobinCop AI", "footer": "Basé sur les {count} dernières transactions spot valides ; achat +{buy}%, vente -{sell}%.",
        "token_table": "Jeton        Cible       Copie       Invest.", "daily_table": "Date  Trades Volume   Cible     Copie",
        "days": "Jours", "hours": "Heures", "mins": "Mins",
    },
    "ar": {
        "title": "RobinCop AI محفظة قابلة للنسخ", "copy_trade": "نسخ التداول", "score": "التقييم الأساسي",
        "target_pnl": "ربح العنوان", "copy_pnl": "ربح النسخ", "copy_loss": "خسارة النسخ", "retention": "الربح المحتفظ به",
        "extra_loss": "خسارة إضافية", "last_2d": "حصة آخر يومين", "target_wr": "فوز العنوان", "token_wr": "فوز الرموز",
        "sell_wr": "فوز البيع", "pl_ratio": "الربح/الخسارة", "trading_days": "أيام التداول", "required_cash": "رأس المال المطلوب",
        "cash_roi": "عائد رأس المال", "trades": "الصفقات", "tokens": "الرموز", "volume": "الحجم",
        "buys_sells": "شراء/بيع", "open_tokens": "رموز مفتوحة", "winning_roi": "عائد الرموز الرابحة",
        "avg_buy": "متوسط الشراء", "avg_sell": "متوسط البيع", "avg_cost": "متوسط الاستثمار/رمز",
        "avg_target": "متوسط ربح العنوان", "avg_copy": "متوسط ربح النسخ", "median_hold": "وسيط الاحتفاظ",
        "last_active": "آخر نشاط", "categories": "منصات الرموز", "other_platforms": "منصات أخرى",
        "recent": "آخر 20 رمزًا (إعادة دقيقة)", "loss": "الخسارة", "win_rate": "الفوز", "older": "البقية: ",
        "daily": "الأداء اليومي (14 يومًا)", "warning": "تم استبعاد المبيعات المعتمدة على رصيد سابق من أرباح التكلفة الصفرية.",
        "copy_with": "النسخ مع RobinCop AI", "footer": "استنادًا إلى آخر {count} صفقة فورية صالحة؛ شراء +{buy}%، بيع -{sell}%.",
        "token_table": "الرمز        الهدف       النسخ       الاستثمار", "daily_table": "التاريخ صفقات الحجم    الهدف     النسخ",
        "days": "أيام", "hours": "ساعات", "mins": "دقائق",
    },
    "pt": {
        "title": "RobinCop AI Carteira para copiar", "copy_trade": "Copiar trades", "score": "Pontuação principal",
        "target_pnl": "PnL alvo", "copy_pnl": "PnL da cópia", "copy_loss": "Perda da cópia", "retention": "Lucro retido",
        "extra_loss": "Perda adicional", "last_2d": "Participação de 2 dias", "target_wr": "Vitórias do alvo", "token_wr": "Vitórias dos tokens",
        "sell_wr": "Vitórias nas vendas", "pl_ratio": "Lucro/perda", "trading_days": "Dias de negociação", "required_cash": "Capital necessário",
        "cash_roi": "ROI do capital", "trades": "Transações", "tokens": "Tokens", "volume": "Volume",
        "buys_sells": "Compras/Vendas", "open_tokens": "Tokens abertos", "winning_roi": "ROI de tokens vencedores",
        "avg_buy": "Preço médio de compra", "avg_sell": "Preço médio de venda", "avg_cost": "Invest. médio/token",
        "avg_target": "PnL alvo médio", "avg_copy": "PnL médio da cópia", "median_hold": "Retenção mediana",
        "last_active": "Última atividade", "categories": "Plataformas dos tokens", "other_platforms": "Outras plataformas",
        "recent": "Últimos 20 tokens (replay estrito)", "loss": "Perda", "win_rate": "Vitórias", "older": "Outros: ",
        "daily": "Desempenho diário (14 dias)", "warning": "Vendas dependentes de estoque anterior foram excluídas do lucro de custo zero.",
        "copy_with": "Copiar com RobinCop AI", "footer": "Com base nas últimas {count} negociações spot válidas; compra +{buy}%, venda -{sell}%.",
        "token_table": "Token        Alvo        Cópia       Invest.", "daily_table": "Data  Trades Volume   Alvo      Cópia",
        "days": "Dias", "hours": "Horas", "mins": "Mins",
    },
    "es": {
        "title": "RobinCop AI Billetera para copiar", "copy_trade": "Copiar trades", "score": "Puntuación principal",
        "target_pnl": "PnL objetivo", "copy_pnl": "PnL de copia", "copy_loss": "Pérdida de copia", "retention": "Beneficio retenido",
        "extra_loss": "Pérdida adicional", "last_2d": "Parte de últimos 2 días", "target_wr": "Acierto objetivo", "token_wr": "Acierto de tokens",
        "sell_wr": "Acierto en ventas", "pl_ratio": "Ganancia/pérdida", "trading_days": "Días de operación", "required_cash": "Capital necesario",
        "cash_roi": "ROI del capital", "trades": "Operaciones", "tokens": "Tokens", "volume": "Volumen",
        "buys_sells": "Compras/Ventas", "open_tokens": "Tokens abiertos", "winning_roi": "ROI de tokens ganadores",
        "avg_buy": "Precio medio de compra", "avg_sell": "Precio medio de venta", "avg_cost": "Inversión media/token",
        "avg_target": "PnL objetivo medio", "avg_copy": "PnL de copia medio", "median_hold": "Tenencia mediana",
        "last_active": "Última actividad", "categories": "Plataformas de tokens", "other_platforms": "Otras plataformas",
        "recent": "Últimos 20 tokens (repetición estricta)", "loss": "Pérdida", "win_rate": "Acierto", "older": "Otros: ",
        "daily": "Rendimiento diario (14 días)", "warning": "Las ventas ligadas a inventario previo se excluyen del beneficio de coste cero.",
        "copy_with": "Copiar con RobinCop AI", "footer": "Basado en las últimas {count} operaciones spot válidas; compra +{buy}%, venta -{sell}%.",
        "token_table": "Token        Objetivo    Copia       Inversión", "daily_table": "Fecha Trades Volumen  Objetivo  Copia",
        "days": "Días", "hours": "Horas", "mins": "Mins",
    },
}


def normalize_language(lang: str) -> str:
    language_map = {key.lower(): key for key in SUPPORTED_LANGUAGES}
    return language_map.get((lang or "").lower(), "en")


def _t(lang: str, key: str) -> str:
    return _I18N[normalize_language(lang)].get(key, _I18N["en"][key])


def _money(value: Any, *, signed: bool = True) -> str:
    number = float(value or 0)
    prefix = "+" if signed and number >= 0 else ("-" if number < 0 else "")
    return f"{prefix}${abs(number):,.2f}"


def _percent(value: Any) -> str:
    return "N/A" if value is None else f"{float(value):.2f}%"


def _holding_time(seconds: Any, *, lang: str) -> str:
    value = float(seconds or 0)
    if value >= 86_400:
        return f"{value / 86_400:.1f} {_t(lang, 'days')}"
    if value >= 3_600:
        return f"{value / 3_600:.1f} {_t(lang, 'hours')}"
    return f"{value / 60:.1f} {_t(lang, 'mins')}"


def _identity(profile: Mapping[str, Any]) -> str:
    name = str(profile.get("name") or profile.get("twitter_name") or "")
    username = str(profile.get("twitter_username") or "")
    if not name and not username:
        return ""
    label = escape(name or username)
    if username:
        label += f" (@{escape(username)})"
    return label


@dataclass(frozen=True)
class _StoredReportContext:
    config: BacktestConfig
    data_quality: Mapping[str, Any]
    processed_trade_count: int


def _build_report(
    result: BacktestResult | _StoredReportContext,
    metrics: Mapping[str, Any],
    *,
    wallet_address: str,
    lang: str,
    profile: Mapping[str, Any],
    referral_url: str,
    recent_limit: int,
    daily_limit: int,
    show_older: bool,
) -> str:
    lang = normalize_language(lang)
    wallet = escape(wallet_address or "unknown")
    referral = escape(referral_url, quote=True)
    identity = _identity(profile)
    target_pnl = metrics["actual_pnl"]
    copy_pnl = metrics["copy_backtest_pnl"]

    def metric_line(key: str, value: str) -> str:
        label = _t(lang, key)
        display_width = sum(
            2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1
            for character in label
        )
        return label + (" " * max(1, 17 - display_width)) + value

    title = (
        f"💹 <b>{escape(_t(lang, 'title'))}:</b> <code>{wallet}</code>"
        + (f" (<b>{identity}</b>)" if identity else "")
        + f' / <a href="{referral}">⚡️ {escape(_t(lang, "copy_trade"))}</a>'
    )
    lines = [title, "", f"📈 <b>{escape(_t(lang, 'score'))}: {metrics['score']}/100</b>", "<pre>"]
    lines.extend(
        [
            metric_line("target_pnl", _money(target_pnl)),
            metric_line("copy_pnl", _money(copy_pnl)),
            metric_line("copy_loss", _percent(metrics["copy_loss_rate"])),
            metric_line("retention", _percent(metrics["pnl_retention_rate"])),
        ]
    )
    if target_pnl <= 0:
        lines.append(metric_line("extra_loss", _money(metrics["extra_loss_usd"], signed=False)))
    lines.extend(
        [
            metric_line("last_2d", f"{metrics['last_2d_profit_share']:.2f}%"),
            metric_line("target_wr", f"{metrics['target_token_win_rate']:.2f}%"),
            metric_line("token_wr", f"{metrics['token_win_rate']:.2f}%"),
            metric_line("sell_wr", f"{metrics['sell_win_rate']:.2f}%"),
            metric_line("pl_ratio", f"{metrics['avg_profit_loss_ratio']:.2f}"),
            metric_line("trading_days", str(metrics["trading_days"])),
            metric_line("required_cash", _money(metrics["required_starting_cash_usd"], signed=False)),
            metric_line("cash_roi", _percent(metrics["copy_roi_on_required_cash"])),
            "----------------------------",
            metric_line("trades", str(metrics["processed_trade_count"])),
            metric_line("tokens", str(metrics["tokens_traded"])),
            metric_line("volume", _money(metrics["trading_volume"], signed=False)),
            metric_line("buys_sells", f"{metrics['buy_count']}/{metrics['sell_count']}"),
            metric_line("open_tokens", str(metrics["open_token_count"])),
            metric_line("winning_roi", f"{metrics['winning_token_roi']:.2f}%"),
            metric_line("avg_buy", f"${metrics['avg_buy_in_price']:.6f}"),
            metric_line("avg_sell", f"${metrics['avg_sell_price']:.6f}"),
            metric_line("avg_cost", _money(metrics["avg_invest_per_token"], signed=False)),
            metric_line("avg_target", _money(metrics["avg_pnl_per_token"])),
            metric_line("avg_copy", _money(metrics["avg_copy_pnl_per_token"])),
            metric_line("median_hold", _holding_time(metrics["median_holding_time_seconds"], lang=lang)),
            metric_line("last_active", str(metrics["last_active"] or "-")),
            "----------------------------",
            "</pre>",
        ]
    )

    categories = list((metrics.get("categories") or {}).items())
    if categories:
        lines.extend(
            [
                f"<b>📊 {escape(_t(lang, 'categories'))}</b>",
                "<pre>",
            ]
        )
        displayed_categories = categories[:7]
        if len(categories) > 7:
            displayed_categories.append(
                (
                    _t(lang, "other_platforms"),
                    {
                        "total": sum(int(stats.get("total") or 0) for _, stats in categories[7:]),
                        "wins": sum(int(stats.get("wins") or 0) for _, stats in categories[7:]),
                    },
                )
            )
        for name, stats in displayed_categories:
            total = int(stats.get("total") or 0)
            wins = int(stats.get("wins") or 0)
            win_rate = wins / total * 100 if total else 0.0
            lines.append(f"• {escape(str(name))}: {total} ({win_rate:.0f}% WR)")
        lines.append("</pre>")

    recent_stats = metrics["recent_20_stats"]
    lines.extend(
        [
            f"<b>🕒 {escape(_t(lang, 'recent'))}</b>",
            "<pre>",
            f"{_t(lang, 'target_pnl')} {_money(recent_stats['actual_pnl'])} | "
            f"{_t(lang, 'copy_pnl')} {_money(recent_stats['copy_backtest_pnl'])}",
            f"{_t(lang, 'loss')} {_percent(recent_stats['copy_loss_rate'])} | "
            f"{_t(lang, 'win_rate')} {recent_stats['win_rate']:.1f}%",
        ]
    )
    if recent_stats["actual_pnl"] <= 0:
        lines.append(f"{_t(lang, 'extra_loss')} {_money(recent_stats['extra_loss_usd'], signed=False)}")
    lines.extend([_t(lang, "token_table"), "----------------------------------------------"])
    recent = list(metrics["recent_20_tokens"])
    for row in recent[:recent_limit]:
        symbol = escape(str(row.get("title") or row.get("token_address") or "")[:10])
        time_str = escape(str(row.get("time_str") or "")[:5])
        label = f"{symbol} {time_str}".strip()
        icon = "✅" if float(row["bt_copy_pnl"]) >= 0 else "❌"
        lines.append(
            f"{label:<15} {_money(row['actual_pnl']):>10} "
            f"{_money(row['bt_copy_pnl']):>10} {icon} ${float(row['invested']):,.0f}"
        )
    lines.append("</pre>")
    if show_older and len(recent) > recent_limit:
        older = " | ".join(
            f"{escape(str(row.get('title') or '')[:6])} {_money(row['bt_copy_pnl'])}"
            for row in recent[recent_limit:]
        )
        lines.extend(["<pre>", _t(lang, "older") + older, "</pre>"])

    daily = list(metrics["daily_stats"])[:daily_limit]
    lines.extend(
        [
            f"<b>📅 {escape(_t(lang, 'daily'))}</b>",
            "<pre>",
            _t(lang, "daily_table"),
            "---------------------------------------",
        ]
    )
    for row in daily:
        volume = float(row["volume"])
        volume_text = f"${volume / 1000:.1f}k" if volume >= 1000 else f"${volume:.0f}"
        lines.append(
            f"{row['date'][5:]} {int(row['trades']):>6} {volume_text:>7} "
            f"{_money(row['actual_pnl']):>9} {_money(row['bt_copy_pnl']):>9}"
        )
    lines.append("</pre>")

    if result.data_quality.get("starting_inventory_unknown"):
        lines.append(f"⚠️ {escape(_t(lang, 'warning'))}")
    buy_penalty = float(result.config.buy_price_penalty) * 100
    sell_penalty = float(result.config.sell_price_penalty) * 100
    max_sell_penalty = max(
        float(result.config.sell_price_penalty_10s),
        float(result.config.sell_price_penalty_30s),
        float(result.config.sell_price_penalty_60s),
    ) * 100
    lines.extend(
        [
            f'<a href="{referral}">⚡️ {escape(_t(lang, "copy_with"))}</a>',
            "<i>"
            + escape(
                _t(lang, "footer").format(
                    count=f"{result.processed_trade_count:,}",
                    buy=f"{buy_penalty:g}",
                    sell=f"{sell_penalty:g}–{max_sell_penalty:g}",
                )
            )
            + "</i>",
        ]
    )
    return "\n".join(lines)


def render_telegram_report(
    result: BacktestResult | None = None,
    *,
    wallet_address: str = "",
    lang: str = "zh-CN",
    profile: Mapping[str, Any] | None = None,
    metrics: Mapping[str, Any] | None = None,
    referral_url: str = DEFAULT_REFERRAL_URL,
    max_length: int = TELEGRAM_TEXT_LIMIT,
) -> str:
    """Render Telegram HTML from a backtest or stored metrics without recalculating."""
    context: BacktestResult | _StoredReportContext
    if result is None:
        if metrics is None:
            raise ValueError("A backtest result or complete stored metrics is required")
        config_keys = {field.name for field in fields(BacktestConfig)}
        context = _StoredReportContext(
            config=BacktestConfig.create(**{
                key: value for key, value in metrics["config"].items() if key in config_keys
            }),
            data_quality=metrics["data_quality"],
            processed_trade_count=int(metrics["processed_trade_count"]),
        )
        if profile is None:
            profile = (metrics.get("gmgn_stats_30d") or {}).get("common") or {}
    else:
        context = result
    profile = profile or {}
    if metrics is None:
        assert result is not None
        metrics = build_legacy_metrics(result, wallet_address=wallet_address, profile=profile)
    layouts = ((7, 14, True), (7, 7, False), (5, 5, False), (3, 3, False), (0, 0, False))
    for recent_limit, daily_limit, show_older in layouts:
        report = _build_report(
            context,
            metrics,
            wallet_address=wallet_address,
            lang=lang,
            profile=profile,
            referral_url=referral_url,
            recent_limit=recent_limit,
            daily_limit=daily_limit,
            show_older=show_older,
        )
        if len(report) <= max_length:
            return report
    raise ValueError("Telegram report summary exceeds the configured text limit")
