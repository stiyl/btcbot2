from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.components.v1 import html

from .alerts import AlertConfig, AlertManager, build_entry_alert, build_exit_alert, build_signal_alert
from .backtest import run_backtest
from .config import BacktestConfig, DashboardConfig
from .data import load_ohlcv_csv
from .downloader import (
    VALID_GRANULARITIES,
    default_download_path,
    download_coinbase_history,
    fetch_coinbase_live_snapshot,
)
from .paper import create_paper_account, paper_account_snapshot, process_live_price, process_paper_signal
from .storage import PaperStateStore, UISettingsStore
from .strategy import build_latest_signal_snapshot


@st.cache_data(ttl=900, show_spinner=False)
def _cached_download(product_id: str, granularity: int, days: int) -> str:
    path = default_download_path(product_id=product_id, granularity=granularity, days=days)
    download_coinbase_history(product_id=product_id, granularity=granularity, days=days, out_path=path)
    return str(path)


@st.cache_data(ttl=10, show_spinner=False)
def _cached_live_snapshot(product_id: str) -> dict[str, object]:
    return fetch_coinbase_live_snapshot(product_id=product_id)


def _enable_autorefresh(seconds: int) -> None:
    if seconds <= 0:
        return
    html(
        f"""
        <script>
        setTimeout(function() {{ window.parent.location.reload(); }}, {int(seconds * 1000)});
        </script>
        """,
        height=0,
        width=0,
    )


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(37, 99, 235, 0.10), transparent 28%),
                radial-gradient(circle at top right, rgba(16, 185, 129, 0.10), transparent 24%),
                linear-gradient(180deg, #0b1220 0%, #111827 100%);
        }
        .block-container { padding-top: 1.2rem; max-width: 1360px; }
        h1,h2,h3,h4,p,label,div { color: #e5eefc; }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f172a 0%, #111827 100%);
            border-right: 1px solid rgba(148, 163, 184, 0.12);
        }
        div[data-testid="stMetric"] {
            background: rgba(15, 23, 42, 0.72);
            border: 1px solid rgba(148, 163, 184, 0.14);
            border-radius: 18px;
            padding: 14px 16px;
            box-shadow: 0 12px 30px rgba(2, 6, 23, 0.20);
        }
        .hero-card, .card {
            padding: 1rem 1.2rem;
            border-radius: 22px;
            background: linear-gradient(135deg, rgba(30, 41, 59, 0.95), rgba(15, 23, 42, 0.95));
            border: 1px solid rgba(148, 163, 184, 0.14);
            box-shadow: 0 18px 45px rgba(2, 6, 23, 0.25);
            margin-bottom: 1rem;
        }
        .hero-kicker { text-transform: uppercase; letter-spacing: 0.12em; color: #93c5fd; font-size: 0.74rem; font-weight: 700; }
        .hero-title { font-size: 2rem; font-weight: 800; margin: 0.4rem 0; color: #f8fafc; }
        .hero-subtitle, .subtle { color: #bfd0ef; font-size: 0.95rem; }
        .chip-row { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.55rem; }
        .chip {
            padding: 0.35rem 0.65rem; border-radius: 999px; background: rgba(59, 130, 246, 0.14);
            border: 1px solid rgba(96, 165, 250, 0.25); color: #dbeafe; font-size: 0.82rem; font-weight: 600;
        }
        .status-buy, .status-sell, .status-watch, .status-hold {
            display: inline-block; padding: 0.34rem 0.7rem; border-radius: 999px; font-weight: 700; font-size: 0.82rem;
        }
        .status-buy { background: rgba(16, 185, 129, 0.18); color: #a7f3d0; border: 1px solid rgba(16, 185, 129, 0.28); }
        .status-sell { background: rgba(239, 68, 68, 0.18); color: #fecaca; border: 1px solid rgba(239, 68, 68, 0.28); }
        .status-watch { background: rgba(245, 158, 11, 0.18); color: #fde68a; border: 1px solid rgba(245, 158, 11, 0.28); }
        .status-hold { background: rgba(148, 163, 184, 0.18); color: #e2e8f0; border: 1px solid rgba(148, 163, 184, 0.24); }
        div[data-testid="stDataFrame"] { border-radius: 18px; overflow: hidden; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _metric_value(value, prefix: str = "", suffix: str = "", digits: int = 2, fallback: str = "—") -> str:
    if value is None:
        return fallback
    try:
        return f"{prefix}{float(value):,.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return fallback


def _status_badge(level: str) -> str:
    level = str(level or "HOLD").upper()
    css = {
        "BUY": "status-buy",
        "SELL": "status-sell",
        "WATCH": "status-watch",
        "HOLD": "status-hold",
    }.get(level, "status-hold")
    return f'<span class="{css}">{level}</span>'


def _section(title: str, caption: str) -> None:
    st.markdown(
        f"""
        <div class="card">
            <div style="font-size:1.08rem;font-weight:700;color:#f8fafc;">{title}</div>
            <div class="subtle">{caption}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_signal_alert(snapshot: dict[str, object]) -> None:
    level = str(snapshot.get("alert_level", "HOLD")).upper()
    message = str(snapshot.get("message", ""))
    signal = str(snapshot.get("signal", "HOLD")).upper()
    score = snapshot.get("score")
    regime = str(snapshot.get("regime", "range")).replace("_", " ").title()
    ts = snapshot.get("timestamp")
    ts_text = pd.to_datetime(ts).strftime("%Y-%m-%d %H:%M UTC") if ts is not None and not pd.isna(ts) else "—"
    st.markdown(
        f"""
        <div class="hero-card" style="margin-top:0.2rem;">
            <div>{_status_badge(level)} <span style="color:#dbeafe;font-weight:700;">Latest strategy state</span></div>
            <div style="font-size:1.08rem;font-weight:700;margin-top:0.8rem;color:#f8fafc;">{message}</div>
            <div class="subtle">Signal: <strong>{signal}</strong> · Score: <strong>{_metric_value(score, digits=2)}</strong> · Regime: <strong>{regime}</strong> · Signal bar: <strong>{ts_text}</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _performance_delta(history: pd.DataFrame) -> float | None:
    if history is None or len(history) < 2 or "equity" not in history.columns:
        return None
    try:
        return float(history["equity"].iloc[-1]) - float(history["equity"].iloc[-2])
    except Exception:
        return None




def _load_ui_defaults(cfg: DashboardConfig) -> dict[str, object]:
    return {
        "product_id": cfg.default_symbols[0],
        "granularity": int(cfg.default_granularity),
        "days": int(cfg.default_days),
        "refresh_seconds": int(cfg.refresh_seconds),
        "use_cached": True,
        "starting_cash": 10000.0,
        "risk_per_trade": 0.01,
        "fee_rate": 0.0006,
        "slippage_rate": 0.0008,
        "stop_atr_multiple": 1.8,
        "take_profit_atr_multiple": 4.8,
        "trailing_atr_multiple": 2.2,
        "use_trailing_stop": True,
        "max_holding_bars": 180,
        "allow_shorts": True,
        "paper_enabled": True,
        "persist_state": bool(cfg.persist_paper_state),
        "auto_execute": True,
        "mark_only": True,
        "alerts_enabled": False,
        "alert_min_level": "BUY",
        "discord_webhook_url": "",
        "telegram_bot_token": "",
        "telegram_chat_id": "",
    }


def _initialize_ui_settings(cfg: DashboardConfig) -> UISettingsStore:
    store = UISettingsStore(cfg.ui_settings_path)
    defaults = _load_ui_defaults(cfg)
    saved = store.load()
    for key, value in defaults.items():
        st.session_state.setdefault(key, saved.get(key, value))
    return store


def _current_ui_settings() -> dict[str, object]:
    keys = [
        "product_id",
        "granularity",
        "days",
        "refresh_seconds",
        "use_cached",
        "starting_cash",
        "risk_per_trade",
        "fee_rate",
        "slippage_rate",
        "stop_atr_multiple",
        "take_profit_atr_multiple",
        "trailing_atr_multiple",
        "use_trailing_stop",
        "max_holding_bars",
        "allow_shorts",
        "paper_enabled",
        "persist_state",
        "auto_execute",
        "mark_only",
        "alerts_enabled",
        "alert_min_level",
        "discord_webhook_url",
        "telegram_bot_token",
        "telegram_chat_id",
    ]
    return {key: st.session_state.get(key) for key in keys}


def render_dashboard(default_csv: str | Path | None = None, config: DashboardConfig | None = None) -> None:
    cfg = config or DashboardConfig()
    st.set_page_config(page_title=cfg.title, layout="wide")
    _inject_styles()

    ui_store = _initialize_ui_settings(cfg)
    store = PaperStateStore(cfg.state_path, cfg.history_path, cfg.trades_path)

    st.sidebar.markdown("## Control Center")
    with st.sidebar.form("dashboard_settings_form"):
        st.text_input("Product", key="product_id")
        st.selectbox(
            "Granularity",
            options=sorted(VALID_GRANULARITIES),
            key="granularity",
            help="Coinbase candle size in seconds.",
        )
        st.slider("Days of history", min_value=7, max_value=730, step=1, key="days")
        st.slider("Auto-refresh live data (seconds)", min_value=0, max_value=120, step=5, key="refresh_seconds")

        st.markdown("### Risk")
        st.number_input("Starting cash", min_value=1000.0, step=1000.0, key="starting_cash")
        st.slider("Risk per trade", min_value=0.001, max_value=0.03, step=0.001, key="risk_per_trade")
        st.number_input("Fee rate", min_value=0.0, step=0.0001, format="%.4f", key="fee_rate")
        st.number_input("Slippage rate", min_value=0.0, step=0.0001, format="%.4f", key="slippage_rate")
        st.number_input("Stop loss ATR multiple", min_value=0.5, step=0.1, format="%.2f", key="stop_atr_multiple")
        st.number_input("Take profit ATR multiple", min_value=0.5, step=0.1, format="%.2f", key="take_profit_atr_multiple")
        st.number_input("Trailing stop ATR multiple", min_value=0.5, step=0.1, format="%.2f", key="trailing_atr_multiple")
        st.number_input("Max holding bars", min_value=1, step=1, key="max_holding_bars")
        st.checkbox("Use trailing stop", key="use_trailing_stop")
        st.checkbox("Allow shorts", key="allow_shorts")

        st.markdown("### Paper trader")
        st.checkbox("Enable live paper trader", key="paper_enabled")
        st.checkbox("Persist dashboard paper state", key="persist_state")
        st.checkbox("Auto execute latest signal", key="auto_execute")
        st.checkbox("Mark open trades with live price", key="mark_only")
        st.checkbox("Use latest cached Coinbase history", key="use_cached")

        st.markdown("### Alerts")
        st.checkbox("Enable alerts", key="alerts_enabled")
        st.selectbox("Minimum alert level", options=["WATCH", "BUY"], key="alert_min_level")
        st.text_input("Discord webhook URL", key="discord_webhook_url", help="Optional. Leave blank to disable Discord alerts.")
        st.text_input("Telegram bot token", key="telegram_bot_token", type="password", help="Optional. Leave blank to disable Telegram alerts.")
        st.text_input("Telegram chat ID", key="telegram_chat_id")

        apply_settings = st.form_submit_button("Apply & save settings", use_container_width=True)

    if apply_settings:
        ui_store.save(_current_ui_settings())
        st.sidebar.success("Settings saved. They will survive a page refresh.")

    product_id = str(st.session_state.get("product_id", cfg.default_symbols[0])).strip().upper() or cfg.default_symbols[0]
    granularity = int(st.session_state.get("granularity", cfg.default_granularity))
    days = int(st.session_state.get("days", cfg.default_days))
    refresh_seconds = int(st.session_state.get("refresh_seconds", cfg.refresh_seconds))
    starting_cash = float(st.session_state.get("starting_cash", 10000.0))
    risk_per_trade = float(st.session_state.get("risk_per_trade", 0.01))
    fee_rate = float(st.session_state.get("fee_rate", 0.0006))
    slippage_rate = float(st.session_state.get("slippage_rate", 0.0008))
    stop_atr_multiple = float(st.session_state.get("stop_atr_multiple", 1.8))
    take_profit_atr_multiple = float(st.session_state.get("take_profit_atr_multiple", 4.8))
    trailing_atr_multiple = float(st.session_state.get("trailing_atr_multiple", 2.2))
    use_trailing_stop = bool(st.session_state.get("use_trailing_stop", True))
    max_holding_bars = int(st.session_state.get("max_holding_bars", 180))
    allow_shorts = bool(st.session_state.get("allow_shorts", True))
    paper_enabled = bool(st.session_state.get("paper_enabled", True))
    persist_state = bool(st.session_state.get("persist_state", cfg.persist_paper_state))
    auto_execute = bool(st.session_state.get("auto_execute", True))
    mark_only = bool(st.session_state.get("mark_only", True))
    use_cached = bool(st.session_state.get("use_cached", True))
    alerts_enabled = bool(st.session_state.get("alerts_enabled", False))
    alert_min_level = str(st.session_state.get("alert_min_level", "BUY")).upper()
    discord_webhook_url = str(st.session_state.get("discord_webhook_url", "")).strip()
    telegram_bot_token = str(st.session_state.get("telegram_bot_token", "")).strip()
    telegram_chat_id = str(st.session_state.get("telegram_chat_id", "")).strip()

    alert_manager = AlertManager(
        AlertConfig(
            enabled=alerts_enabled,
            min_level=alert_min_level,
            discord_webhook_url=discord_webhook_url,
            telegram_bot_token=telegram_bot_token,
            telegram_chat_id=telegram_chat_id,
        ),
        cfg.alerts_log_path,
    )

    reset_cols = st.sidebar.columns(2)
    if reset_cols[0].button("Reset paper account", use_container_width=True):
        store.reset()
        st.session_state.pop("paper_account", None)
        st.session_state.pop("paper_history", None)
        st.session_state.pop("paper_trades", None)
        st.sidebar.success("Paper account state reset.")
    if reset_cols[1].button("Reset UI settings", use_container_width=True):
        ui_store.reset()
        for key in _load_ui_defaults(cfg).keys():
            st.session_state.pop(key, None)
        st.session_state.pop("downloaded_csv", None)
        st.rerun()

    _enable_autorefresh(refresh_seconds)

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Data source")
    uploaded = st.sidebar.file_uploader("Upload OHLCV CSV", type=["csv"], help="Optional override. Leave empty to auto-download Coinbase history.")
    source = uploaded if uploaded is not None else (str(default_csv) if default_csv else None)

    if uploaded is None:
        if st.sidebar.button("Refresh Coinbase history now", use_container_width=True):
            _cached_download.clear()
            st.session_state.pop("downloaded_csv", None)
        if source is None and "downloaded_csv" not in st.session_state:
            with st.spinner(f"Downloading {product_id} history from Coinbase..."):
                st.session_state["downloaded_csv"] = _cached_download(product_id, int(granularity), int(days))
        elif use_cached:
            st.session_state["downloaded_csv"] = _cached_download(product_id, int(granularity), int(days))

    source = st.session_state.get("downloaded_csv", source)
    if source is None:
        st.info("Upload an OHLCV CSV or let the dashboard download Coinbase candles automatically.")
        return

    try:
        df = load_ohlcv_csv(source)
    except Exception as exc:
        st.error(f"Could not load data source: {exc}")
        return

    bt_cfg = BacktestConfig(
        starting_cash=starting_cash,
        risk_per_trade=risk_per_trade,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        allow_shorts=allow_shorts,
    )
    bt_cfg.strategy.stop_atr_multiple = stop_atr_multiple
    bt_cfg.strategy.take_profit_atr_multiple = take_profit_atr_multiple
    bt_cfg.strategy.trailing_atr_multiple = trailing_atr_multiple
    bt_cfg.strategy.use_trailing_stop = use_trailing_stop
    bt_cfg.strategy.max_holding_bars = max_holding_bars
    result = run_backtest(df, bt_cfg)
    signal_snapshot = build_latest_signal_snapshot(result.enriched_frame, bt_cfg.strategy)

    last_ts = df["timestamp"].iloc[-1] if not df.empty else None
    last_ts_text = pd.to_datetime(last_ts).strftime("%Y-%m-%d %H:%M UTC") if last_ts is not None and not pd.isna(last_ts) else "—"
    st.markdown(
        f"""
        <div class="hero-card">
            <div class="hero-kicker">Crypto Trading Dashboard</div>
            <div class="hero-title">Full refactor for UI, live paper trading, and deploy-ready monitoring.</div>
            <div class="hero-subtitle">Track <strong>{product_id}</strong> with Coinbase data, persistent paper trading state, and a cleaner layout built for Streamlit deployment.</div>
            <div class="chip-row">
                <span class="chip">{product_id}</span>
                <span class="chip">{granularity}s candles</span>
                <span class="chip">{days} days loaded</span>
                <span class="chip">Last candle: {last_ts_text}</span>
                <span class="chip">Auto-refresh: {'Off' if refresh_seconds == 0 else f'{refresh_seconds}s'}</span>
                <span class="chip">Persistence: {'On' if persist_state else 'Session only'}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    live: dict[str, object] = {}
    live_error = None
    try:
        live = _cached_live_snapshot(product_id)
    except Exception as exc:
        live_error = exc

    top1, top2, top3, top4 = st.columns(4)
    top1.metric("Ending equity", f"${result.summary['ending_equity']:,.2f}")
    top2.metric("Total return", f"{result.summary['total_return_pct']:.2f}%")
    top3.metric("Max drawdown", f"{result.summary['max_drawdown_pct']:.2f}%")
    top4.metric("Win rate", f"{result.summary['win_rate_pct']:.2f}%")

    _render_signal_alert(signal_snapshot)

    market_tab, strategy_tab, paper_tab, research_tab, raw_tab = st.tabs([
        "Overview",
        "Strategy",
        "Live Paper Trader",
        "Research",
        "Raw Data",
    ])

    with market_tab:
        left, right = st.columns([1.15, 1], gap="large")
        with left:
            _section("Live market snapshot", "Current public Coinbase state for the selected product.")
            if live_error is not None:
                st.warning(f"Live Coinbase snapshot unavailable right now: {live_error}")
            else:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Live price", _metric_value(live.get("price"), prefix="$"))
                c2.metric("24h change", _metric_value(live.get("pct_change_24h"), suffix="%"))
                c3.metric("Spread", _metric_value(live.get("spread"), prefix="$"))
                c4.metric("24h volume", _metric_value(live.get("volume_24h")))
                c5, c6, c7, c8 = st.columns(4)
                c5.metric("Bid", _metric_value(live.get("bid"), prefix="$"))
                c6.metric("Ask", _metric_value(live.get("ask"), prefix="$"))
                c7.metric("24h high", _metric_value(live.get("high_24h"), prefix="$"))
                c8.metric("24h low", _metric_value(live.get("low_24h"), prefix="$"))

            price_chart = result.enriched_frame[["timestamp", "close", "ema_fast", "ema_slow", "ema_trend"]].copy()
            st.line_chart(price_chart.set_index("timestamp"), height=370)
            st.caption("Close price with fast, slow, and trend EMAs.")

        with right:
            _section("Run status", "A quick summary of what the app is analyzing right now.")
            d1, d2 = st.columns(2)
            d1.metric("Rows loaded", f"{len(df):,}")
            d2.metric("Backtest trades", f"{int(result.summary['trade_count']):,}")
            d3, d4 = st.columns(2)
            d3.metric("Data source", "CSV upload" if uploaded is not None else "Coinbase cache")
            d4.metric("Shorts", "Enabled" if allow_shorts else "Disabled")
            d5, d6 = st.columns(2)
            d5.metric("Risk / trade", f"{risk_per_trade * 100:.2f}%")
            d6.metric("Starting cash", _metric_value(starting_cash, prefix="$", digits=0))
            st.markdown(
                f"""
                <div class="card">
                    <div style="font-size:1rem;font-weight:700;">Deploy note</div>
                    <div class="subtle">This app is ready for <code>streamlit run app.py</code> locally or Streamlit Community Cloud with <code>app.py</code> as the entry point.</div>
                    <div class="subtle" style="margin-top:0.6rem;">Current source: <strong>{source}</strong></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with strategy_tab:
        s_left, s_right = st.columns([1.25, 1], gap="large")
        with s_left:
            _section("Backtest equity curve", "Historical paper performance under the current configuration.")
            equity_chart = result.equity_curve[["timestamp", "equity", "cash"]].copy()
            st.line_chart(equity_chart.set_index("timestamp"), height=350)
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Sharpe-like", _metric_value(result.summary.get("sharpe_like"), digits=2))
            p2.metric("Profit factor", _metric_value(result.summary.get("profit_factor"), digits=2))
            p3.metric("Trade count", f"{int(result.summary['trade_count']):,}")
            p4.metric("Latest alert", str(signal_snapshot.get("alert_level", "HOLD")))
            focus_cols = ["timestamp", "rsi", "volume_z", "atr_pct", "score", "long_score", "short_score"]
            st.line_chart(result.enriched_frame[focus_cols].set_index("timestamp"), height=320)
        with s_right:
            _section("Latest model readout", "Current strategy state for the latest closed candle.")
            latest = result.enriched_frame.iloc[-1]
            cols = st.columns(2)
            cols[0].metric("Close", _metric_value(latest.get("close"), prefix="$"))
            cols[1].metric("RSI", _metric_value(latest.get("rsi"), digits=2))
            cols = st.columns(2)
            cols[0].metric("ATR %", _metric_value((latest.get("atr_pct") or 0) * 100, suffix="%"))
            cols[1].metric("Volume z-score", _metric_value(latest.get("volume_z"), digits=2))
            cols = st.columns(2)
            cols[0].metric("Long score", _metric_value(latest.get("long_score"), digits=2))
            cols[1].metric("Short score", _metric_value(latest.get("short_score"), digits=2))
            cols = st.columns(2)
            cols[0].metric("EMA fast", _metric_value(latest.get("ema_fast"), prefix="$"))
            cols[1].metric("EMA slow", _metric_value(latest.get("ema_slow"), prefix="$"))
            cols = st.columns(2)
            cols[0].metric("EMA trend", _metric_value(latest.get("ema_trend"), prefix="$"))
            cols[1].metric("Regime", str(latest.get("regime", "range")).replace("_", " ").title())

    with paper_tab:
        _section("Persistent live paper trader", "Simulates the newest signal against the latest live price and can survive app reruns when persistence is enabled.")
        if not paper_enabled:
            st.info("Enable the live paper trader from the sidebar to start simulating trades.")
        elif live_error is not None:
            st.warning("Live price is currently unavailable, so the paper trader cannot update right now.")
        else:
            live_price = None
            try:
                live_price = float(live.get("price")) if live.get("price") is not None else None
            except Exception:
                live_price = None

            if "paper_account" not in st.session_state:
                persisted = store.load_account() if persist_state else None
                st.session_state["paper_account"] = persisted or create_paper_account(float(starting_cash))

            account = st.session_state["paper_account"]
            if abs(account.starting_cash - float(starting_cash)) > 1e-9:
                account = create_paper_account(float(starting_cash))
                st.session_state["paper_account"] = account
                if persist_state:
                    store.reset()

            manual_cols = st.columns([1, 1, 3])
            manual_cols[0].markdown(f"<div class='subtle'>Auto execute: <strong>{'On' if auto_execute else 'Off'}</strong></div>", unsafe_allow_html=True)
            manual_cols[1].markdown(f"<div class='subtle'>Live marking: <strong>{'On' if mark_only else 'Off'}</strong></div>", unsafe_allow_html=True)
            manual_step = manual_cols[2].button("Run one paper update now", use_container_width=True)

            prior_trade_count = len(account.trades)
            prior_position_side = account.position.side if account.position is not None else "FLAT"
            latest_row = result.enriched_frame.iloc[-1] if not result.enriched_frame.empty else None

            if latest_row is not None and alerts_enabled and str(signal_snapshot.get("signal", "HOLD")).upper() in {"BUY", "SELL"}:
                level, title, body, event_id = build_signal_alert(signal_snapshot, product_id)
                alert_manager.emit(level=level, event_type="signal", title=title, body=body, event_id=event_id, metadata={"product_id": product_id})

            if live_price is not None and mark_only:
                process_live_price(account, live_price, pd.Timestamp.utcnow().isoformat(), bt_cfg)
            if live_price is not None and (auto_execute or manual_step) and latest_row is not None:
                process_paper_signal(account, latest_row, live_price, bt_cfg)

            if len(account.trades) > prior_trade_count:
                trade = account.trades[-1]
                level, title, body, event_id = build_exit_alert(trade, product_id)
                alert_manager.emit(level=level, event_type="exit", title=title, body=body, event_id=event_id, metadata=trade)

            new_position_side = account.position.side if account.position is not None else "FLAT"
            if prior_position_side != new_position_side and account.position is not None:
                level, title, body, event_id = build_entry_alert(account.position, product_id)
                alert_manager.emit(level=level, event_type="entry", title=title, body=body, event_id=event_id, metadata={"product_id": product_id})

            if persist_state:
                store.save_account(account)
                history = store.append_history(account, live_price)
                trades = store.sync_trades(account)
            else:
                history = st.session_state.get("paper_history", pd.DataFrame())
                snap_before = paper_account_snapshot(account, live_price)
                row = {
                    "timestamp": pd.Timestamp.utcnow(),
                    "equity": snap_before["equity"],
                    "cash": snap_before["cash"],
                    "realized_pnl": snap_before["realized_pnl"],
                    "unrealized_pnl": snap_before["unrealized_pnl"],
                    "position_side": snap_before["position_side"],
                    "mark_price": live_price,
                }
                history = pd.concat([history, pd.DataFrame([row])], ignore_index=True)
                if "timestamp" in history.columns:
                    history["timestamp"] = pd.to_datetime(history["timestamp"], utc=True, errors="coerce")
                    history = history.drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp")
                trades = pd.DataFrame(account.trades)
                st.session_state["paper_history"] = history
                st.session_state["paper_trades"] = trades

            snap = paper_account_snapshot(account, live_price)
            delta = _performance_delta(history)
            p1, p2, p3, p4, p5 = st.columns(5)
            p1.metric("Paper equity", _metric_value(snap.get("equity"), prefix="$"), delta=_metric_value(delta, prefix="$") if delta is not None else None)
            p2.metric("Paper cash", _metric_value(snap.get("cash"), prefix="$"))
            p3.metric("Realized PnL", _metric_value(snap.get("realized_pnl"), prefix="$"))
            p4.metric("Unrealized PnL", _metric_value(snap.get("unrealized_pnl"), prefix="$"))
            p5.metric("Position", str(snap.get("position_side", "FLAT")))

            q1, q2, q3, q4 = st.columns(4)
            q1.metric("Qty", _metric_value(snap.get("position_qty"), digits=6))
            q2.metric("Entry", _metric_value(snap.get("entry_price"), prefix="$"))
            q3.metric("Live mark", _metric_value(live_price, prefix="$"))
            q4.metric("Trades", str(snap.get("trade_count", 0)))

            if account.position is not None:
                r1, r2, r3 = st.columns(3)
                r1.metric("Stop", _metric_value(snap.get("stop_price"), prefix="$"))
                r2.metric("Take profit", _metric_value(snap.get("take_profit"), prefix="$"))
                r3.metric("Trail stop", _metric_value(snap.get("trail_stop"), prefix="$"))

            if not history.empty and "timestamp" in history.columns:
                hist_chart = history[["timestamp", "equity", "cash", "realized_pnl", "unrealized_pnl"]].copy()
                st.line_chart(hist_chart.set_index("timestamp"), height=280)
                st.caption("Persistent live paper account curve. This survives reruns when persistence is enabled.")

            if not trades.empty:
                st.dataframe(trades.tail(200), use_container_width=True, height=330)
            else:
                st.info("No paper trades yet. The trader will open a position when a new BUY or SELL signal appears.")

            st.markdown("### Alert feed")
            alerts_df = alert_manager.recent_alerts(100)
            if alerts_df.empty:
                st.caption("No alerts logged yet.")
            else:
                display_cols = [col for col in ["timestamp", "level", "event_type", "title", "body"] if col in alerts_df.columns]
                st.dataframe(alerts_df[display_cols], use_container_width=True, height=250)

    with research_tab:
        left, right = st.columns(2, gap="large")
        with left:
            _section("Backtest trades", "Recent simulated trades from the historical backtest.")
            st.dataframe(result.trades.tail(200), use_container_width=True, height=420)
        with right:
            _section("Recent model rows", "Useful for debugging thresholds, entries, and exits.")
            preview_cols = [
                "timestamp", "close", "signal", "alert_level", "score", "long_score", "short_score",
                "rsi", "atr_pct", "volume_z", "regime",
            ]
            st.dataframe(result.enriched_frame[preview_cols].tail(200), use_container_width=True, height=420)

    with raw_tab:
        _section("Loaded OHLCV data", "Raw candles feeding the backtest and live strategy logic.")
        st.dataframe(df.tail(300), use_container_width=True, height=430)
