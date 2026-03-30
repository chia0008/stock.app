import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from FinMind.data import DataLoader
from datetime import datetime, timedelta

# 1. 網頁頁面基本設定
st.set_page_config(page_title="台股本益比河流圖", layout="centered")

st.title("🌊 台股本益比河流圖")
st.caption("數據源: FinMind 穩定對接 | 自動計算歷史分位數區間")

# --- 側邊欄：使用者輸入區 ---
st.sidebar.header("控制面板")
# FinMind 只需要數字代號，不需要加 .TW
raw_stock_id = st.sidebar.text_input("輸入股票代號 (如 2330)", value="2330").strip()
period_years = st.sidebar.selectbox("觀察區間 (年)", [1, 3, 5, 10], index=2)

# 自訂顏色選擇器
st.sidebar.subheader("自訂區間顏色")
c1 = st.sidebar.color_picker("極低 (超跌)", "#2ECC71")
c2 = st.sidebar.color_picker("偏低 (便宜)", "#3498DB")
c3 = st.sidebar.color_picker("合理 (價值)", "#F1C40F")
c4 = st.sidebar.color_picker("偏高 (注意)", "#E67E22")
c5 = st.sidebar.color_picker("極高 (泡沫)", "#E74C3C")
CUSTOM_COLORS = [c1, c2, c3, c4, c5]

# --- 核心邏輯：資料抓取 (全 FinMind 版本) ---
@st.cache_data(ttl=3600)
def load_finmind_data(sid, years):
    try:
        dl = DataLoader()
        # 如果你有 Token，請在下方取消註釋並填入
        # dl.login_by_token(token="YOUR_TOKEN")
        
        # 計算起始日期
        start_date = (datetime.now() - timedelta(days=years*365)).strftime('%Y-%m-%d')
        
        # 1. 抓取股價
        df_price = dl.taiwan_stock_daily(stock_id=sid, start_date=start_date)
        if df_price.empty:
            return None, None
            
        df_price = df_price.rename(columns={'close': 'Close', 'date': 'Date'})
        df_price['Date'] = pd.to_datetime(df_price['Date'])
        df_price = df_price.set_index('Date')

        # 2. 抓取財報並計算 TTM EPS
        # 財報需要抓得比股價早一點，以便計算 TTM
        fin_start = (datetime.now() - timedelta(days=(years+2)*365)).strftime('%Y-%m-%d')
        df_fin = dl.taiwan_stock_financial_statement(stock_id=sid, start_date=fin_start)
        
        # 篩選 EPS
        df_eps = df_fin[df_fin['type'].str.contains('EPS', na=False, case=False)]
        if df_eps.empty:
            return None, None
            
        # 鎖定「基本每股盈餘」
        priority_type = 'EPSS_NetIncome_After_Tax_To_Parent_Basic_EPS'
        if priority_type in df_eps['type'].values:
            df_eps = df_eps[df_eps['type'] == priority_type]
        else:
            df_eps = df_eps[df_eps['type'] == df_eps['type'].iloc[0]]
            
        df_eps = df_eps[['date', 'value']].rename(columns={'value': 'eps', 'date': 'Date'})
        df_eps['Date'] = pd.to_datetime(df_eps['Date'])
        df_eps = df_eps.sort_values('Date').drop_duplicates('Date')
        
        # 計算 TTM EPS (滾動四季)
        df_eps['ttm_eps'] = df_eps['eps'].rolling(window=4).sum()
        df_eps = df_eps.dropna(subset=['ttm_eps']).set_index('Date')
        
        return df_price, df_eps
    except Exception as e:
        st.error(f"資料抓取失敗: {e}")
        return None, None

# --- 執行與繪圖 ---
if st.sidebar.button("開始繪製"):
    with st.spinner(f"正在從交易所獲取 {raw_stock_id} 的完整數據..."):
        df_price, ttm_series = load_finmind_data(raw_stock_id, period_years)
        
        if df_price is not None and not ttm_series.empty:
            # 數據對齊 (使用 merge_asof 將股價與「當下最新」的 TTM EPS 合併)
            df = pd.merge_asof(df_price[['Close']].sort_index(), ttm_series[['ttm_eps']].sort_index(), 
                               left_index=True, right_index=True, direction='backward').dropna()
            
            # 計算每日 PE 並計算百分位數
            df['PE'] = df['Close'] / df['ttm_eps']
            clean_pe = df['PE'][(df['PE'] > 0) & (df['PE'] < 100)] # 排除負數與極端異常值
            
            if clean_pe.empty:
                st.warning("歷史本益比數據異常，可能該股近期虧損嚴重。")
            else:
                q = clean_pe.quantile([0.1, 0.3, 0.5, 0.7, 0.9]).values
                
                # 繪製 Plotly
                fig = go.Figure()
                # 河流底部 (0 元)
                base_line = df['ttm_eps'] * 0
                lines = [base_line] + [df['ttm_eps'] * v for v in q]
                labels = ["極低區", "便宜區", "合理區", "昂貴區", "泡沫區"]
                
                for i in range(5):
                    # 畫區間
                    fig.add_trace(go.Scatter(
                        x=df.index, y=lines[i+1],
                        mode='lines', line=dict(width=0),
                        showlegend=False, hoverinfo='skip'
                    ))
                    fig.add_trace(go.Scatter(
                        x=df.index, y=lines[i],
                        fill='tonexty', fillcolor=CUSTOM_COLORS[i],
                        mode='lines', line=dict(width=0),
                        name=f"{labels[i]} (PE {q[i]:.1f}x)",
                        opacity=0.8
                    ))
                
                # 疊加收盤價
                fig.add_trace(go.Scatter(
                    x=df.index, y=df['Close'],
                    line=dict(color='black', width=3),
                    name='實際收盤價'
                ))
                
                fig.update_layout(
                    title=f"<b>{raw_stock_id} 歷史本益比河流圖</b>",
                    hovermode='x unified',
                    template='plotly_white',
                    legend=dict(orientation="h", y=-0.2),
                    margin=dict(l=10, r=10, t=50, b=10)
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
                # 顯示關鍵指標
                c_price, c_eps, c_pe = st.columns(3)
                c_price.metric("目前股價", f"{df['Close'].iloc[-1]}")
                c_eps.metric("TTM EPS", f"{df['ttm_eps'].iloc[-1]:.2f}")
                c_pe.metric("目前 PE", f"{df['PE'].iloc[-1]:.2f}x")
        else:
            st.error("無法取得資料，請確認代號是否存在（僅限台股數字代號）。")
else:
    st.info("請在左側輸入台股代號（例如 2330）並點擊開始。")