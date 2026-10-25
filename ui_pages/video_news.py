from services.news_ui_shared import *
activate_page_state('video_news')
initialise_state()
st.title('🎬 澳洲新闻视频制作')
mode = st.radio('选择制作模式', ('新闻翻译', '发布会政策解读'), horizontal=True, key='video_production_mode')
is_conference = mode == '发布会政策解读'
if st.session_state.get('active_mode') != mode:
    st.session_state.active_mode = mode
    st.session_state.candidates = []
    st.session_state.selected_video_ids = set()
if is_conference:
    st.caption('从新闻发布会视频中按发布时间选择素材，生成面向在澳华人的政策解读短视频。')
    source_key, source_path, source_defaults = ('conference_sources', CONFERENCE_SOURCES_PATH, DEFAULT_CONFERENCE_SOURCES)
else:
    st.caption('从 YouTube 新闻源筛选与房产、租赁、福利相关的内容，再启动中文翻译视频工作流。')
    source_key, source_path, source_defaults = ('sources', SOURCES_PATH, DEFAULT_SOURCES)
sources = st.session_state[source_key]
with st.sidebar:
    st.header('本次范围')
    days = st.slider('最近几天', min_value=1, max_value=7, value=1)
    selected_topics = []
    if not is_conference:
        st.subheader('关注主题')
        st.caption('拉取或重新分类时由 Luna 处理全部视频标题；切换主题只筛选当前结果。')
        selected_topics = [topic for topic in TOPIC_OPTIONS if st.checkbox(topic, value=True, key=f'topic_{topic}')]
    st.caption(f"本地时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
if not is_conference:
    filter_candidate_topics(selected_topics)
source_tab, candidate_tab, workflow_tab = st.tabs(['1. 新闻源', '2. 候选新闻', '3. 工作流队列'])
with source_tab:
    st.subheader('YouTube 发布会源' if is_conference else 'YouTube 新闻源')
    if is_conference:
        st.write('固定使用 ABC 与 9 News 的 Live 标签页、National Press Club 全频道，以及指定播放列表；按所选天数显示最近发布的视频。')
    else:
        st.write('填写 YouTube 频道网址，按所选天数拉取视频。文章和混合素材请使用左侧新闻评论页面。')
    if not YOUTUBE_API_KEY:
        st.warning('未配置 YOUTUBE_API_KEY，暂时无法拉取 YouTube 新闻。')
    if not OPENAI_API_KEY:
        st.warning('未配置 OPENAI_KEY，暂时无法启动后续制作。')
    if st.button('拉取发布会视频' if is_conference else '拉取并 AI 筛选新闻', type='primary', disabled=not any((source.get('enabled') for source in sources))):
        st.session_state.ui_events = []
        try:
            with st.status('正在处理新闻…', expanded=True) as status:
                status.write('正在解析频道并拉取 YouTube 公开视频…')
                log_ui_event('开始拉取 YouTube 新闻')
                fetch_recent_news(days, sources)
                log_ui_event(f'新闻拉取完成：{len(st.session_state.candidates)} 条')
                if is_conference:
                    status.update(label='发布会视频拉取完成', state='complete', expanded=False)
                else:
                    status.write(f'已拉取 {len(st.session_state.candidates)} 条，正在将全部视频标题交给 Luna 分类…')
                    screen_candidates(selected_topics)
                    log_ui_event('Luna 标题筛选完成')
                    status.update(label='新闻筛选完成', state='complete', expanded=False)
            if is_conference:
                st.success(f'已按发布时间拉取 {len(st.session_state.candidates)} 条视频。')
            else:
                relevant_count = sum((item.get('relevant', False) for item in st.session_state.candidates))
                st.success(f'已拉取 {len(st.session_state.candidates)} 条新闻；按主题筛出 {relevant_count} 条相关候选。')
        except Exception as error:
            log_ui_event(f'失败：{type(error).__name__}: {error}')
            st.error(f'新闻筛选失败：{type(error).__name__}: {error}')
    if is_conference:
        st.caption(f'计划拉取最近 {days} 天的公开视频；不进行 LLM 标题或主题筛选。')
    else:
        st.caption(f"计划拉取最近 {days} 天的视频，并按主题“{'、'.join(selected_topics) or '未选择'}”筛选。")
    st.divider()
    if is_conference:
        st.caption('固定来源')
        st.markdown('- [ABC News Australia · Live](https://www.youtube.com/@abcnewsaustralia/streams)')
        st.markdown('- [9 News Australia · Live](https://www.youtube.com/@9NewsAUS/streams)')
        for source in sources:
            playlist_id = str(source.get('playlist_id') or '').strip()
            if playlist_id:
                source_name = source.get('name') or '指定 YouTube 播放列表'
                st.markdown(f'- [{source_name}](https://www.youtube.com/playlist?list={playlist_id})')
    else:
        for index, source in enumerate(sources):
            with st.container(border=True):
                left, middle, right, remove = st.columns([1.4, 2.4, 0.8, 0.5])
                source['source_type'] = 'video'
                source['name'] = left.text_input('来源名称', value=source['name'], key=f'{source_key}_name_{index}')
                source['channel_ref'] = middle.text_input('来源网址或 @handle', value=source['channel_ref'], key=f'{source_key}_channel_{index}', placeholder='例如 https://youtube.com/@ABCNewsAustralia 或 @ABCNewsAustralia')
                source['enabled'] = right.checkbox('启用', value=source['enabled'], key=f'{source_key}_enabled_{index}')
                remove.button('删除', key=f'{source_key}_remove_{index}', on_click=remove_source, args=(source_key, index))
        st.button('＋ 添加新闻源', key=f'{source_key}_add', on_click=add_source, args=(source_key,))
        if st.button('保存新闻源', key=f'{source_key}_save', type='secondary'):
            save_sources(source_key, source_path, source_defaults)
            st.success(f'已保存到 {source_path.name}')
    if st.session_state.ui_events:
        with st.expander('执行日志', expanded=True):
            st.code('\n'.join(st.session_state.ui_events), language='text')
    if st.session_state.source_errors:
        st.warning('部分来源未能拉取，已跳过：\n\n' + '\n\n'.join((f'- {message}' for message in st.session_state.source_errors)))
with candidate_tab:
    st.subheader('候选发布会' if is_conference else '候选新闻')
    if not st.session_state.candidates:
        st.info('尚未拉取视频。拉取后勾选要制作的内容。' if is_conference else '尚未拉取新闻。拉取后，使用 AI 按当前主题筛选并勾选要制作的视频。')
    else:
        if not is_conference and st.button('重新分类全部新闻', type='secondary', disabled=not bool(OPENAI_API_KEY)):
            try:
                log_ui_event('开始按当前主题重新调用 Luna 筛选')
                with st.status('正在重新分类全部视频标题…', expanded=False) as status:
                    screen_candidates(selected_topics)
                    status.update(label='Luna 筛选完成', state='complete', expanded=False)
                log_ui_event('Luna 重新筛选完成')
                relevant_count = sum((item.get('relevant', False) for item in st.session_state.candidates))
                st.success(f'已完成筛选：{relevant_count} 条相关，{len(st.session_state.candidates) - relevant_count} 条不相关。')
            except Exception as error:
                log_ui_event(f'重新筛选失败：{type(error).__name__}: {error}')
                st.error(f'重新筛选失败：{type(error).__name__}: {error}')
        screened = st.session_state.candidates if is_conference else [item for item in st.session_state.candidates if 'relevant' in item]
        if not screened:
            st.caption('新闻已拉取，等待 AI 筛选。')
        else:
            relevant = screened if is_conference else [item for item in screened if item['relevant']]
            if is_conference:
                st.caption(f'按发布时间显示 {len(relevant)} 条视频；未进行 AI 筛选。')
            else:
                irrelevant_count = len(screened) - len(relevant)
                st.caption(f'主题筛选结果：{len(relevant)} 条相关，{irrelevant_count} 条未选中。只显示相关内容。')
            article_count = sum((item.get('source_type') == 'article' for item in relevant))
            st.caption(f'当前显示：{len(relevant) - article_count} 条视频 · {article_count} 篇文章')
            if not relevant:
                st.info('没有标题与当前主题相关；可修改主题后重新筛选。')
            for item in relevant:
                with st.container(border=True):
                    columns = st.columns([0.7, 4.3, 1.2])
                    if item.get('thumbnail_url'):
                        columns[0].image(item['thumbnail_url'], use_container_width=True)
                    columns[1].markdown(f"**[{item['title']}]({item['url']})**")
                    columns[1].caption(f"{item['channel_name']} · {format_sydney_time(item['published_at'])} · {format_video_duration(item.get('duration_seconds'))}")
                    if not is_conference:
                        columns[1].write(f"主题：{'、'.join(item.get('matched_topics', [])) or '未明确'}  \nAI 判断：{item.get('reason') or '相关'}")
                    checked = columns[2].checkbox('加入解读队列' if is_conference else '加入翻译队列', value=item['video_id'] in st.session_state.selected_video_ids, key=f"{mode}_select_{item['video_id']}")
                    if checked:
                        st.session_state.selected_video_ids.add(item['video_id'])
                    else:
                        st.session_state.selected_video_ids.discard(item['video_id'])
with workflow_tab:
    st.subheader('制作队列')
    selected_count = len(st.session_state.selected_video_ids)
    st.info(f'已选择 {selected_count} 条素材。' + ('每条都会建立独立工作区，并启动 conference.py；成片会自动上传 Google Drive。' if is_conference else '每条都会建立独立工作区，并启动 translate.py。'))
    task_title = st.text_input('视频大标题', value='澳洲政策解读' if is_conference else '今日要闻', key=f'{mode}_title')
    advertisement = st.text_input('广告文案', value='如果你想了解更多澳洲资讯，请关注土澳小红叔', help='新闻翻译会独立插入广告；发布会解读会将广告融入一段既有解说。', key=f'{mode}_advertisement')
    upload_to_drive = False if is_conference else st.checkbox('完成后上传 Google Drive', value=True)
    angle = ''
    action_label = '启动已选发布会的政策解读制作' if is_conference else '启动已选视频的翻译工作流'
    if st.button(action_label, disabled=selected_count == 0, type='primary'):
        try:
            if is_conference:
                start_conference_workflow(task_title, advertisement)
            else:
                start_translation_workflow(task_title, upload_to_drive, advertisement)
            st.success('工作流已在后台启动。日志会持续写入下方路径。')
        except (OSError, ValueError) as error:
            st.error(str(error))
    if st.session_state.workflow_runs:
        st.subheader('本次页面启动的任务')
        for run in st.session_state.workflow_runs:
            with st.container(border=True):
                st.write(f"**{run.get('workflow', '新闻翻译')} · {run['count']} 条视频** · 已启动于 {run['started_at']} · 进程 PID {run['pid']}")
                st.caption(f"任务文件：{run['task_file']}")
                st.caption(f"日志文件：{run['log_file']}")
                if run.get('cost_file'):
                    st.caption(f"费用明细：{run['cost_file']}")
