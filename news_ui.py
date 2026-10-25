"""Streamlit entrypoint: video workflows and an independent commentary page."""
import streamlit as st

st.set_page_config(page_title='澳洲新闻视频制作', page_icon='🎬', layout='wide')
page = st.navigation([
    st.Page('ui_pages/video_news.py', title='新闻翻译 / 发布会解读', default=True),
    st.Page('ui_pages/news_comment.py', title='新闻评论', url_path='news_comment'),
])
page.run()
