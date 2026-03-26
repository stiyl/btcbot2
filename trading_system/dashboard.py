from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.components.v1 import html

from .backtest import run_backtest
from .config import BacktestConfig, DashboardConfig
from .data import load_ohlcv_csv
from .downloader import (
    VALID_GRANULARITIES,
    default_download_path,
    download_coinbase_history,
    fetch_coinbase_live_snapshot,
)
from .paper import create_paper_account, paper_account_snapshot, process_paper_signal
from .strategy import build_latest_signal_snapshot


@st.cache_data(ttl=900, show_spinner=False)
def _cached_download(product_id: str, granularity: int, days: int) -> str:
    path = default_download_path(product_id=product_id, granularity=granularity, days=days)
    download_coinbase_history(product_id=product_id, granularity=granularity, days=days, out_path=path)
    return str(path)


@st.cache_data(ttl=10, show_spinner=False)
def _cached_live_snapshot(product_id: str) -> dict[str, object]:
    return fetch_coinbase_live_snapshot(product_id=product_id)


def _enable_autorefresh(seconds: int):
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
        .block-container {
            padding-top: 1.4rem;
            padding-bottom: 2rem;
            max-width: 1350px;
        }
        h1, h2, h3, h4, p, label, div {
            color: #e5eefc;
        }
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
        div[data-testid="stMetric"] label {
            color: #9fb3d9 !important;
            font-size: 0.88rem !important;
        }
        div[data-testid="stMetricValue"] {
            color: #f8fafc;
        }
        .hero-card {
            padding: 1.25rem 1.4rem;
            border-radius: 22px;
            background: linear-gradient(135deg, rgba(30, 41, 59, 0.95), rgba(15, 23, 42, 0.95));
            border: 1px solid rgba(148, 163, 184, 0.14);
            box-shadow: 0 18px 45px rgba(2, 6, 23, 0.25);
            margin-bottom: 1rem;
        }
        .hero-kicker {
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: #93c5fd;
            font-size: 0.74rem;
            margin-bottom: 0.4rem;
            font-weight: 700;
        }
        .hero-title {
            font-size: 2.1rem;
            font-weight: 800;
            margin-bottom: 0.45rem;
            line-height: 1.1;
            color: #f8fafc;
        }
        .hero-subtitle {
            color: #bfd0ef;
            font-size: 0.98rem;
            margin-bottom: 0.75rem;
        }
        .chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-top: 0.25rem;
        }
        .chip {
            padding: 0.35rem 0.65rem;
            border-radius: 999px;
            background: rgba(59, 130, 246, 0.14);
            border: 1px solid rgba(96, 165, 250, 0.25);
            color: #dbeafe;
            font-size: 0.82rem;
            font-weight: 600;
        }
        .section-card {
            background: rgba(15, 23, 42, 0.72);
            border: 1px solid rgba(148, 163, 184, 0.12);
            border-radius: 22px;
            padding: 1rem 1rem 0.75rem 1rem;
            box-shadow: 0 15px 35px rgba(2, 6, 23, 0.18);
            margin-bottom: 1rem;
        }
        .section-title {
            font-size: 1.12rem;
            font-weight: 700;
            color: #f8fafc;
            margin-bottom: 0.15rem;
        }
        .section-caption {
            color: #9fb3d9;
            margin-bottom: 0.9rem;
            font-size: 0.92rem;
        }
        .status-buy, .status-sell, .status-watch, .status-hold {
            display: inline-block;
            padding: 0.34rem 0.7rem;
            border-radius: 999px;
            font-weight: 700;
            font-size: 0.82rem;
            margin-right: 0.55rem;
        }
        .status-buy { background: rgba(16, 185, 129, 0.18); color: #a7f3d0; border: 1px solid rgba(16, 185, 129, 0.28); }
        .status-sell { background: rgba(239, 68, 68, 0.18); color: #fecaca; border: 1px solid rgba(239, 68, 68, 0.28); }
        .status-watch { background: rgba(245, 158, 11, 0.18); color: #fde68a; border: 1px solid rgba(245, 158, 11, 0.28); }
        .status-hold { background: rgba(148, 163, 184, 0.18); color: #e2e8f0; border: 1px solid rgba(148, 163, 184, 0.24); }
        div[data-testid="stDataFrame"], div[data-testid="stPlotlyChart"], div[data-testid="stVegaLiteChart"] {
            border-radius: 18px;
            overflow: hidden;
            border: 1px solid rgba(148, 163, 184, 0.12);
        }
        .mini-note {
            color: #9fb3d9;
            font-size: 0.85rem;
            margin-top: 0.35rem;
        }
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


def _section_header(title: str, caption: str) -> None:
    st.markdown(
        f"""
        <div class="section-card">
            <div class="section-title">{title}</div>
            <div class="section-caption">{caption}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_signal_alert(snapshot: dict[str, object]):
    level = str(snapshot.get("alert_level", "HOLD")).upper()
    message = str(snapshot.get("message", ""))
    signal = str(snapshot.get("signal", "HOLD")).upper()
    score = snapshot.get("score")
    regime = snapshot.get("regime")
    ts = snapshot.get("timestamp")
    ts_text = pd.to_datetime(ts).strftime("%Y-%m-%d %H:%M UTC") if ts is not None and not pd.isna(ts) else "—"

    st.markdown(
        f"""
        <div class="hero-card" style="margin-top:0.2rem;">
            <div>{_status_badge(level)} <span style="color:#dbeafe;font-weight:700;">Latest model state</span></div>
            <div style="font-size:1.15rem;font-weight:700;margin-top:0.75rem;color:#f8fafc;">{message}</div>
            <div class="mini-note">Signal: <strong>{signal}</strong> · Score: <strong>{_metric_value(score, digits=2)}</strong> · Regime: <strong>{str(regime).replace('_', ' ').title()}</strong> · Signal bar: <strong>{ts_text}</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard(default_csv: str | Path | None = None, config: DashboardConfig | None = None):
    cfg = config or DashboardConfig()
    st.set_page_config(page_title=cfg.title, layout="wide")
    _inject_styles()

    st.sidebar.markdown("## Control Center")
    product_id = st.sidebar.text_input("Product", value=cfg.default_symbols[0]).strip().upper() or cfg.default_symbols[0]
    granularity = st.sidebar.selectbox(
        "Granularity",
        options=sorted(VALID_GRANULARITIES),
        index=sorted(VALID_GRANULARITIES).index(cfg.default_granularity) if cfg.default_granularity in VALID_GRANULARITIES else 3,
        help="Coinbase candle size in seconds.",
    )
    days = st.sidebar.slider("Days of history", min_value=7, max_value=730, value=cfg.default_days, step=1)
    refresh_seconds = st.sidebar.slider("Auto-refresh live data (seconds)", min_value=0, max_value=120, value=cfg.refresh_seconds, step=5)
    _enable_autorefresh(refresh_seconds)

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Data source")
    uploaded = st.sidebar.file_uploader("Upload OHLCV CSV", type=["csv"], help="Optional override. Leave empty to auto-download Coinbase history.")
    source = uploaded if uploaded is not None else (str(default_csv) if default_csv else None)

    use_cached = True
    if uploaded is None:
        use_cached = st.sidebar.checkbox("Use latest cached Coinbase history", value=True)
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

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Backtest + risk")
    starting_cash = st.sidebar.number_input("Starting cash", min_value=1000.0, value=10000.0, step=1000.0)
    risk_per_trade = st.sidebar.slider("Risk per trade", min_value=0.001, max_value=0.03, value=0.01, step=0.001)
    fee_rate = st.sidebar.number_input("Fee rate", min_value=0.0, value=0.0006, step=0.0001, format="%.4f")
    slippage_rate = st.sidebar.number_input("Slippage rate", min_value=0.0, value=0.0008, step=0.0001, format="%.4f")
    allow_shorts = st.sidebar.checkbox("Allow shorts", value=True)

    st.sidebar.markdown("---")
    st.sidebar.markdown("### Live paper trader")
    paper_enabled = st.sidebar.checkbox("Enable live paper trader", value=True)
    if st.sidebar.button("Reset paper account", use_container_width=True):
        st.session_state.pop("paper_account", None)
        st.session_state.pop("paper_history", None)

    bt_cfg = BacktestConfig(
        starting_cash=starting_cash,
        risk_per_trade=risk_per_trade,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        allow_shorts=allow_shorts,
    )
    result = run_backtest(df, bt_cfg)
    signal_snapshot = build_latest_signal_snapshot(result.enriched_frame, bt_cfg.strategy)

    last_ts = df["timestamp"].iloc[-1] if not df.empty else None
    last_ts_text = pd.to_datetime(last_ts).strftime("%Y-%m-%d %H:%M UTC") if last_ts is not None and not pd.isna(last_ts) else "—"
    st.markdown(
        f"""
        <div class="hero-card">
            <div class="hero-kicker">Crypto Trading Dashboard</div>
            <div class="hero-title">Better visibility for live monitoring, paper trading, and backtest review.</div>
            <div class="hero-subtitle">Track <strong>{product_id}</strong> with Coinbase market data, cleaner analytics, and a more useful layout for decisions.</div>
            <div class="chip-row">
                <span class="chip">{product_id}</span>
                <span class="chip">{granularity}s candles</span>
                <span class="chip">{days} days loaded</span>
                <span class="chip">Last candle: {last_ts_text}</span>
                <span class="chip">Auto-refresh: {'Off' if refresh_seconds == 0 else f'{refresh_seconds}s'}</span>
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
            _section_header("Live market snapshot", "Current public Coinbase state for the selected product.")
            if live_error is not None:
                st.warning(f"Live Coinbase snapshot unavailable right now: {live_error}")
            else:
                live_cols = st.columns(4)
                live_cols[0].metric("Live price", _metric_value(live.get("price"), prefix="$"))
                live_cols[1].metric("24h change", _metric_value(live.get("pct_change_24h"), suffix="%", digits=2))
                live_cols[2].metric("Spread", _metric_value(live.get("spread"), prefix="$", digits=2))
                live_cols[3].metric("24h volume", _metric_value(live.get("volume_24h"), digits=2))
                more_live = st.columns(4)
                more_live[0].metric("Bid", _metric_value(live.get("bid"), prefix="$"))
                more_live[1].metric("Ask", _metric_value(live.get("ask"), prefix="$"))
                more_live[2].metric("24h high", _metric_value(live.get("high_24h"), prefix="$"))
                more_live[3].metric("24h low", _metric_value(live.get("low_24h"), prefix="$"))

            price_chart = result.enriched_frame[["timestamp", "close", "ema_fast", "ema_slow", "ema_trend"]].copy()
            st.line_chart(price_chart.set_index("timestamp"), height=370)
            st.caption("Price, fast EMA, slow EMA, and trend EMA in one view.")

        with right:
            _section_header("Data source health", "A quick summary of what the dashboard is analyzing right now.")
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
                <div class="section-card">
                    <div class="section-title">Current source</div>
                    <div class="section-caption">{source}</div>
                    <div class="mini-note">The dashboard can auto-refresh, auto-download history, and update the live paper account using the newest model bar.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with strategy_tab:
        s_left, s_right = st.columns([1.3, 1], gap="large")
        with s_left:
            _section_header("Backtest equity curve", "Historical paper performance of the current strategy configuration.")
            equity_chart = result.equity_curve[["timestamp", "equity", "cash"]].copy()
            st.line_chart(equity_chart.set_index("timestamp"), height=350)
            perf_cols = st.columns(4)
            perf_cols[0].metric("Sharpe-like", _metric_value(result.summary.get("sharpe_like"), digits=2))
            perf_cols[1].metric("Profit factor", _metric_value(result.summary.get("profit_factor"), digits=2))
            perf_cols[2].metric("Trade count", f"{int(result.summary['trade_count']):,}")
            perf_cols[3].metric("Latest alert", str(signal_snapshot.get("alert_level", "HOLD")))

            _section_header("Momentum and participation", "Watch volume pressure and RSI without digging through raw rows.")
            focus_cols = ["timestamp", "rsi", "volume_z", "atr_pct", "score", "long_score", "short_score"]
            st.line_chart(result.enriched_frame[focus_cols].set_index("timestamp"), height=320)

        with s_right:
            _section_header("Latest model readout", "Current strategy state for the latest closed candle.")
            latest = result.enriched_frame.iloc[-1]
            cols = st.columns(2)
            cols[0].metric("Close", _metric_value(latest.get("close"), prefix="$"))
            cols[1].metric("RSI", _metric_value(latest.get("rsi"), digits=2))
            cols = st.columns(2)
            cols[0].metric("ATR %", _metric_value((latest.get("atr_pct") or 0) * 100, suffix="%", digits=2))
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
        _section_header("Session-based live paper trader", "A virtual account that reacts to the latest closed signal bar and marks to the newest live price.")
        if not paper_enabled:
            st.info("Enable the live paper trader from the sidebar to start simulating trades.")
        elif live_error is not None:
            st.warning("Live price is currently unavailable, so the paper trader cannot update right now.")
        else:
            if "paper_account" not in st.session_state or st.session_state["paper_account"].starting_cash != float(starting_cash):
                st.session_state["paper_account"] = create_paper_account(float(starting_cash))

            live_price_for_paper = None
            try:
                live_price_for_paper = float(live.get("price")) if live.get("price") is not None else None
            except Exception:
                live_price_for_paper = None

            if live_price_for_paper and not result.enriched_frame.empty:
                paper_account = st.session_state["paper_account"]
                process_paper_signal(paper_account, result.enriched_frame.iloc[-1], live_price_for_paper, bt_cfg)
                paper_state = paper_account_snapshot(paper_account, live_price_for_paper)

                p1, p2, p3, p4, p5 = st.columns(5)
                p1.metric("Paper equity", _metric_value(paper_state.get("equity"), prefix="$"))
                p2.metric("Paper cash", _metric_value(paper_state.get("cash"), prefix="$"))
                p3.metric("Realized PnL", _metric_value(paper_state.get("realized_pnl"), prefix="$"))
                p4.metric("Unrealized PnL", _metric_value(paper_state.get("unrealized_pnl"), prefix="$"))
                p5.metric("Position", str(paper_state.get("position_side", "FLAT")))

                q1, q2, q3, q4 = st.columns(4)
                q1.metric("Qty", _metric_value(paper_state.get("position_qty"), digits=6))
                q2.metric("Entry", _metric_value(paper_state.get("entry_price"), prefix="$"))
                q3.metric("Live mark", _metric_value(live_price_for_paper, prefix="$"))
                q4.metric("Trades", str(paper_state.get("trade_count", 0)))

                if paper_account.position is not None:
                    r1, r2, r3 = st.columns(3)
                    r1.metric("Stop", _metric_value(paper_state.get("stop_price"), prefix="$"))
                    r2.metric("Take profit", _metric_value(paper_state.get("take_profit"), prefix="$"))
                    r3.metric("Trail stop", _metric_value(paper_state.get("trail_stop"), prefix="$"))

                paper_trades = pd.DataFrame(paper_account.trades)
                if not paper_trades.empty:
                    st.dataframe(paper_trades.tail(100), use_container_width=True, height=360)
                else:
                    st.info("No live paper trades yet. A simulated trade will open when a new closed candle prints a BUY or SELL signal.")

                st.caption("This mode is still paper only. It never sends exchange orders.")

    with research_tab:
        left, right = st.columns([1, 1], gap="large")
        with left:
            _section_header("Backtest trades", "Recent simulated trades from the historical backtest.")
            st.dataframe(result.trades.tail(200), use_container_width=True, height=420)
        with right:
            _section_header("Recent model rows", "Useful for debugging thresholds, entries, and exits.")
            preview_cols = [
                "timestamp", "close", "signal", "alert_level", "score", "long_score", "short_score",
                "rsi", "atr_pct", "volume_z", "regime",
            ]
            st.dataframe(result.enriched_frame[preview_cols].tail(200), use_container_width=True, height=420)

    with raw_tab:
        _section_header("Loaded OHLCV data", "Raw candles feeding the backtest and live strategy logic.")
        st.dataframe(df.tail(300), use_container_width=True, height=430)

