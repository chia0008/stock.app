import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from FinMind.data import DataLoader
from datetime import datetime, timedelta

# 1. 網頁頁面基本設定
st.set_page_config(page_title="台股河流圖", layout="wide")

st.title("🌊 台股本益比河流圖")
st.caption("數據源: FinMind 穩定對接 | 支援多股同時分析與數據導出")

# --- 側邊欄：使用者輸入區 ---
st.sidebar.header("控制面板")
# 修改為支援多個代號，用逗號隔開
raw_input = st.sidebar.text_input("輸入股票代號 (多股請用逗號隔開)", value="2330, 2317, 3324").strip()
stock_list = [s.strip() for s in raw_input.replace('，', ',').split(',')]
period_years = st.sidebar.selectbox("觀察區間 (年)", [1, 3, 5, 10], index=2)

# 自訂顏色選擇器
st.sidebar.subheader("自訂區間顏色")
c1 = st.sidebar.color_picker("極低 (超跌)", "#2ECC71")
c2 = st.sidebar.color_picker("偏低 (便宜)", "#3498DB")
c3 = st.sidebar.color_picker("合理 (價值)", "#F1C40F")
c4 = st.sidebar.color_picker("偏高 (注意)", "#E67E22")
c5 = st.sidebar.color_picker("極高 (泡沫)", "#E74C3C")
CUSTOM_COLORS = [c1, c2, c3, c4, c5]

# --- 核心邏輯：資料抓取 ---
@st.cache_data(ttl=3600)
def load_data(sid, years):
    try:
        dl = DataLoader()
        start_date = (datetime.now() - timedelta(days=years*365)).strftime('%Y-%m-%d')
        # 股價
        df_price = dl.taiwan_stock_daily(stock_id=sid, start_date=start_date)
        if df_price.empty: return None
        df_price = df_price.rename(columns={'close': 'Close', 'date': 'Date'})
        df_price['Date'] = pd.to_datetime(df_price['Date'])
        
        # 財報 (多抓兩年算 TTM)
        fin_start = (datetime.now() - timedelta(days=(years+2)*365)).strftime('%Y-%m-%d')
        df_fin = dl.taiwan_stock_financial_statement(stock_id=sid, start_date=fin_start)
        df_eps = df_fin[df_fin['type'].str.contains('EPS', na=False, case=False)]
        if df_eps.empty: return None
        
        # 鎖定基本 EPS
        p_type = 'EPSS_NetIncome_After_Tax_To_Parent_Basic_EPS'
        df_eps = df_eps[df_eps['type'] == p_type] if p_type in df_eps['type'].values else df_eps[df_eps['type'] == df_eps['type'].iloc[0]]
        df_eps = df_eps[['date', 'value']].rename(columns={'value': 'eps', 'date': 'Date'})
        df_eps['Date'] = pd.to_datetime(df_eps['Date'])
        df_eps = df_eps.sort_values('Date').drop_duplicates('Date')
        df_eps['ttm_eps'] = df_eps['eps'].rolling(window=4).sum()
        
        # 合併
        df = pd.merge_asof(df_price.sort_values('Date'), df_eps.dropna().sort_values('Date'), on='Date', direction='backward').dropna()
        df['PE'] = df['Close'] / df['ttm_eps']
        return df
    except:
        return None

# --- 執行與繪圖 ---
if st.sidebar.button("開始集體分析"):
    summary_data = [] # 用來存放多股對照簡表
    
    for sid in stock_list:
        with st.expander(f"📌 股票代號：{sid} 分析報告", expanded=True):
            df = load_data(sid, period_years)
            if df is not None:
                # 計算分位數
                clean_pe = df['PE'][(df['PE'] > 0) & (df['PE'] < 100)]
                q = clean_pe.quantile([0.1, 0.3, 0.5, 0.7, 0.9]).values
                
                # 繪圖 (Plotly)
                fig = go.Figure()
                lines = [df['ttm_eps'] * 0] + [df['ttm_eps'] * v for v in q]
                labels = ["極低", "便宜", "合理", "昂貴", "泡沫"]
                for i in range(5):
                    fig.add_trace(go.Scatter(x=df['Date'], y=lines[i+1], mode='lines', line=dict(width=0), showlegend=False))
                    fig.add_trace(go.Scatter(x=df['Date'], y=lines[i], fill='tonexty', fillcolor=CUSTOM_COLORS[i], mode='lines', line=dict(width=0), name=f"{labels[i]} (PE {q[i]:.1f}x)"))
                fig.add_trace(go.Scatter(x=df['Date'], y=df['Close'], line=dict(color='black', width=3), name='收盤價'))
                fig.update_layout(title=f"{sid} 河流圖", hovermode='x unified', margin=dict(l=10, r=10, t=50, b=10))
                st.plotly_chart(fig, use_container_width=True)
                
                # 收集對照資料
                current_pe = df['PE'].iloc[-1]
                status = "未知"
                if current_pe < q[0]: status = "超跌(極低)"
                elif current_pe < q[1]: status = "便宜"
                elif current_pe < q[2]: status = "合理"
                elif current_pe < q[3]: status = "昂貴"
                else: status = "泡沫"
                
                summary_data.append({
                    "股票代號": sid,
                    "目前股價": df['Close'].iloc[-1],
                    "TTM EPS": round(df['ttm_eps'].iloc[-1], 2),
                    "目前 PE": round(current_pe, 2),
                    "合理 PE": round(q[2], 2),
                    "目前位階": status
                })
            else:
                st.error(f"代號 {sid} 抓取失敗，請檢查代號是否有誤。")

    # --- 顯示總結對照表 ---
    if summary_data:
        st.markdown("---")
        st.header("📊 多股快速對照表")
        summary_df = pd.DataFrame(summary_data)
        st.dataframe(summary_df, use_container_width=True)
        
        # 下載按鈕
        csv = summary_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下載對照表 (CSV)", data=csv, file_name='stock_comparison.csv', mime='text/csv')

else:
    st.info("請在左側輸入一個或多個代號（例如：2330, 2317），點擊「開始集體分析」。")
