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
from .strategy import build_latest_signal_snapshot
from .paper import create_paper_account, paper_account_snapshot, process_paper_signal


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


def _metric_value(value, prefix: str = "", suffix: str = "", digits: int = 2, fallback: str = "—") -> str:
    if value is None:
        return fallback
    try:
        return f"{prefix}{float(value):,.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return fallback


def _render_signal_alert(snapshot: dict[str, object]):
    level = str(snapshot.get('alert_level', 'HOLD')).upper()
    message = str(snapshot.get('message', ''))
    signal = str(snapshot.get('signal', 'HOLD')).upper()
    score = snapshot.get('score')
    regime = snapshot.get('regime')

    if level == 'BUY':
        st.success(f"{signal} alert — {message}")
    elif level == 'SELL':
        st.error(f"{signal} alert — {message}")
    elif level == 'WATCH':
        st.warning(f"{level} alert — {message}")
    else:
        st.info(message)

    meta_cols = st.columns(4)
    meta_cols[0].metric('Latest signal', signal)
    meta_cols[1].metric('Score', _metric_value(score, digits=2))
    meta_cols[2].metric('Regime', str(regime).replace('_', ' ').title())
    ts = snapshot.get('timestamp')
    meta_cols[3].metric('Signal bar', pd.to_datetime(ts).strftime('%Y-%m-%d %H:%M UTC') if ts is not None and not pd.isna(ts) else '—')


def render_dashboard(default_csv: str | Path | None = None, config: DashboardConfig | None = None):
    cfg = config or DashboardConfig()
    st.set_page_config(page_title=cfg.title, layout='wide')
    st.title(cfg.title)
    st.caption('Auto-download Coinbase candles, monitor live prices, surface trade alerts, and run session-based live paper trades from the latest closed signal bar.')

    st.sidebar.header('Market')
    product_id = st.sidebar.text_input('Product', value=cfg.default_symbols[0]).strip().upper() or cfg.default_symbols[0]
    granularity = st.sidebar.selectbox(
        'Granularity',
        options=sorted(VALID_GRANULARITIES),
        index=sorted(VALID_GRANULARITIES).index(cfg.default_granularity) if cfg.default_granularity in VALID_GRANULARITIES else 3,
    )
    days = st.sidebar.slider('Days of history', min_value=7, max_value=730, value=cfg.default_days, step=1)
    refresh_seconds = st.sidebar.slider('Auto-refresh live data (seconds)', min_value=0, max_value=120, value=cfg.refresh_seconds, step=5)
    _enable_autorefresh(refresh_seconds)

    st.sidebar.header('Data source')
    uploaded = st.sidebar.file_uploader('Upload OHLCV CSV (optional override)', type=['csv'])
    source = uploaded if uploaded is not None else (str(default_csv) if default_csv else None)

    if uploaded is None:
        if st.sidebar.button('Refresh Coinbase history now'):
            _cached_download.clear()
            st.session_state.pop('downloaded_csv', None)
        if source is None and 'downloaded_csv' not in st.session_state:
            with st.spinner(f'Downloading {product_id} history from Coinbase...'):
                st.session_state['downloaded_csv'] = _cached_download(product_id, int(granularity), int(days))
        elif st.sidebar.checkbox('Use latest cached Coinbase history', value=True):
            st.session_state['downloaded_csv'] = _cached_download(product_id, int(granularity), int(days))

    source = st.session_state.get('downloaded_csv', source)
    if source is None:
        st.info('Upload an OHLCV CSV or let the dashboard download Coinbase candles automatically.')
        return

    try:
        df = load_ohlcv_csv(source)
    except Exception as exc:
        st.error(f'Could not load data source: {exc}')
        return

    st.sidebar.subheader('Risk settings')
    starting_cash = st.sidebar.number_input('Starting cash', min_value=1000.0, value=2000.0, step=1000.0)
    risk_per_trade = st.sidebar.slider('Risk per trade', min_value=0.001, max_value=0.03, value=0.01, step=0.001)
    fee_rate = st.sidebar.number_input('Fee rate', min_value=0.0, value=0.0060, step=0.0001, format='%.4f')
    slippage_rate = st.sidebar.number_input('Slippage rate', min_value=0.0, value=0.0008, step=0.0001, format='%.4f')
    allow_shorts = st.sidebar.checkbox('Allow shorts', value=True)

    st.sidebar.subheader('Live paper trading')
    paper_enabled = st.sidebar.checkbox('Enable live paper trader', value=True)
    if st.sidebar.button('Reset paper account'):
        st.session_state.pop('paper_account', None)
        st.session_state.pop('paper_history', None)

    bt_cfg = BacktestConfig(
        starting_cash=starting_cash,
        risk_per_trade=risk_per_trade,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        allow_shorts=allow_shorts,
    )
    result = run_backtest(df, bt_cfg)
    signal_snapshot = build_latest_signal_snapshot(result.enriched_frame, bt_cfg.strategy)

    st.write(f"Using data source: `{source}`")

    st.subheader('Live market snapshot')
    live = {}
    try:
        live = _cached_live_snapshot(product_id)
        live_cols = st.columns(5)
        live_cols[0].metric('Live price', _metric_value(live.get('price'), prefix='$'))
        live_cols[1].metric('24h change', _metric_value(live.get('pct_change_24h'), suffix='%', digits=2))
        live_cols[2].metric('Bid / Ask spread', _metric_value(live.get('spread'), prefix='$', digits=2))
        live_cols[3].metric('24h high', _metric_value(live.get('high_24h'), prefix='$'))
        live_cols[4].metric('24h low', _metric_value(live.get('low_24h'), prefix='$'))
        detail_cols = st.columns(3)
        detail_cols[0].metric('Bid', _metric_value(live.get('bid'), prefix='$'))
        detail_cols[1].metric('Ask', _metric_value(live.get('ask'), prefix='$'))
        detail_cols[2].metric('24h volume', _metric_value(live.get('volume_24h'), digits=2))
    except Exception as exc:
        st.warning(f'Live Coinbase snapshot unavailable right now: {exc}')

    st.subheader('Signal alerts')
    _render_signal_alert(signal_snapshot)

    if paper_enabled:
        if 'paper_account' not in st.session_state or st.session_state['paper_account'].starting_cash != float(starting_cash):
            st.session_state['paper_account'] = create_paper_account(float(starting_cash))
        live_price_for_paper = None
        try:
            live_price_for_paper = float(live.get('price')) if live.get('price') is not None else None
        except Exception:
            live_price_for_paper = None
        if live_price_for_paper and not result.enriched_frame.empty:
            paper_account = st.session_state['paper_account']
            process_paper_signal(paper_account, result.enriched_frame.iloc[-1], live_price_for_paper, bt_cfg)
            paper_state = paper_account_snapshot(paper_account, live_price_for_paper)

            st.subheader('Live paper trader')
            p1, p2, p3, p4, p5 = st.columns(5)
            p1.metric('Paper equity', _metric_value(paper_state.get('equity'), prefix='$'))
            p2.metric('Paper cash', _metric_value(paper_state.get('cash'), prefix='$'))
            p3.metric('Realized PnL', _metric_value(paper_state.get('realized_pnl'), prefix='$'))
            p4.metric('Unrealized PnL', _metric_value(paper_state.get('unrealized_pnl'), prefix='$'))
            p5.metric('Position', str(paper_state.get('position_side', 'FLAT')))

            detail_left, detail_mid, detail_right = st.columns(3)
            detail_left.metric('Qty', _metric_value(paper_state.get('position_qty'), digits=6))
            detail_mid.metric('Entry', _metric_value(paper_state.get('entry_price'), prefix='$'))
            detail_right.metric('Trades', str(paper_state.get('trade_count', 0)))

            if paper_account.position is not None:
                risk_cols = st.columns(3)
                risk_cols[0].metric('Stop', _metric_value(paper_state.get('stop_price'), prefix='$'))
                risk_cols[1].metric('Take profit', _metric_value(paper_state.get('take_profit'), prefix='$'))
                risk_cols[2].metric('Trail', _metric_value(paper_state.get('trail_stop'), prefix='$'))

            paper_trades = pd.DataFrame(paper_account.trades)
            if not paper_trades.empty:
                st.dataframe(paper_trades.tail(100), use_container_width=True)
            else:
                st.info('No live paper trades yet. The app will open a simulated trade when a new closed candle prints a BUY or SELL signal.')

            st.caption('Live paper trader is session-based: it reacts once per newly closed signal bar using the latest Coinbase price on refresh. It does not send exchange orders.')

    c1, c2, c3, c4 = st.columns(4)
    c1.metric('Ending equity', f"${result.summary['ending_equity']:,.2f}")
    c2.metric('Total return', f"{result.summary['total_return_pct']:.2f}%")
    c3.metric('Max drawdown', f"{result.summary['max_drawdown_pct']:.2f}%")
    c4.metric('Win rate', f"{result.summary['win_rate_pct']:.2f}%")

    st.subheader('Equity curve')
    st.line_chart(result.equity_curve.set_index('timestamp')['equity'])

    st.subheader('Price + trend stack')
    chart_df = result.enriched_frame[['timestamp', 'close', 'ema_fast', 'ema_slow', 'ema_trend']].set_index('timestamp')
    st.line_chart(chart_df)

    st.subheader('Recent model rows')
    st.dataframe(result.enriched_frame.tail(200), use_container_width=True)

    st.subheader('Trades')
    st.dataframe(result.trades.tail(200), use_container_width=True)
