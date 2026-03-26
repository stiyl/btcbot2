from __future__ import annotations

from pathlib import Path

import streamlit as st

from .config import BacktestConfig
from .data import load_ohlcv_csv
from .backtest import run_backtest
from .downloader import download_coinbase_history, VALID_GRANULARITIES


def render_dashboard(default_csv: str | Path | None = None):
    st.set_page_config(page_title='Crypto Trading Dashboard', layout='wide')
    st.title('Crypto Trading Research Dashboard')
    st.caption('Upload OHLCV data, download Coinbase candles, inspect the improved signal model, and run the backtest.')

    st.sidebar.header('Data source')
    uploaded = st.sidebar.file_uploader('Upload OHLCV CSV', type=['csv'])
    source = uploaded if uploaded is not None else (str(default_csv) if default_csv else None)

    with st.sidebar.expander('Or download from Coinbase', expanded=source is None):
        product_id = st.text_input('Product', value='BTC-USD')
        granularity = st.selectbox('Granularity', options=sorted(VALID_GRANULARITIES), index=3)
        days = st.slider('Days of history', min_value=7, max_value=730, value=180, step=1)
        output_name = st.text_input('Save downloaded CSV as', value=f"{product_id.replace('-', '_')}_{granularity}s_{days}d.csv")
        if st.button('Download candles'):
            try:
                downloaded = download_coinbase_history(
                    product_id=product_id,
                    granularity=int(granularity),
                    days=int(days),
                    out_path=Path(output_name),
                )
                st.session_state['downloaded_csv'] = str(downloaded)
                st.success(f'Downloaded: {downloaded}')
                source = str(downloaded)
            except Exception as exc:
                st.error(f'Failed to download data: {exc}')

    source = st.session_state.get('downloaded_csv', source)
    if source is None:
        st.info('Upload an OHLCV CSV or download Coinbase candles to begin.')
        return

    try:
        df = load_ohlcv_csv(source)
    except Exception as exc:
        st.error(f'Could not load data source: {exc}')
        return

    st.sidebar.subheader('Risk settings')
    starting_cash = st.sidebar.number_input('Starting cash', min_value=1000.0, value=10000.0, step=1000.0)
    risk_per_trade = st.sidebar.slider('Risk per trade', min_value=0.001, max_value=0.03, value=0.01, step=0.001)
    fee_rate = st.sidebar.number_input('Fee rate', min_value=0.0, value=0.0006, step=0.0001, format='%.4f')
    slippage_rate = st.sidebar.number_input('Slippage rate', min_value=0.0, value=0.0008, step=0.0001, format='%.4f')
    allow_shorts = st.sidebar.checkbox('Allow shorts', value=True)

    cfg = BacktestConfig(
        starting_cash=starting_cash,
        risk_per_trade=risk_per_trade,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        allow_shorts=allow_shorts,
    )
    result = run_backtest(df, cfg)

    st.write(f"Using data source: `{source}`")

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
