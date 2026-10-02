                st.success(f"เพิ่มเป็นเพื่อนเรียบร้อยแล้ว!")
                st.rerun()

# ----------------------------------------------------------------------------
# 4. Search Tab (ค้นหาหนัง) [NEW]
# ----------------------------------------------------------------------------
with tab_search:
    st.subheader("🔍 ค้นหาข้อมูลภาพยนตร์")
    search_term = st.text_input("พิมพ์ชื่อภาพยนตร์ที่ต้องการค้นหา:", placeholder="เช่น Matrix, Inception...")
    
    if search_term:
        q_search = """
        MATCH (m:Movie)
        WHERE toLower(m.title) CONTAINS toLower($term)
        OPTIONAL MATCH (u:User)-[r:WATCHED]->(m)
        OPTIONAL MATCH (m)-[:IN_GENRE]->(g:Genre)
        RETURN m.title AS title,
               collect(DISTINCT g.name) AS genres,
               count(DISTINCT u) AS total_watchers,
               avg(r.rating) AS avg_rating,
               collect(DISTINCT u.name) AS watchers
        """
        results = run(q_search, term=search_term)
        if results.empty:
            st.warning("ไม่พบภาพยนตร์ที่ตรงกับคำค้นหา")
        else:
            for _, row in results.iterrows():
                with st.container():
                    st.markdown(f"### 🎬 {row['title']}")
                    st.write(f"**แนวหนัง:** {', '.join(row['genres']) if row['genres'] else 'ไม่ระบุ'}")
                    st.write(f"**จำนวนคนเคยดู:** {row['total_watchers']} คน")
                    avg_r = f"{row['avg_rating']:.1f} ⭐" if row['avg_rating'] else "ยังไม่มีคะแนน"
                    st.write(f"**คะแนนเฉลี่ย:** {avg_r}")
                    if row['watchers']:
                        st.caption(f"ผู้ใช้ที่เคยดูแล้ว: {', '.join(row['watchers'])}")
                    st.divider()

# ----------------------------------------------------------------------------
# 5. User Tab
# ----------------------------------------------------------------------------
with tab_user:
    st.subheader(f"👤 ข้อมูลส่วนตัวของ {user_name}")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🎬 หนังที่เคยรับชม**")
        st.dataframe(run(Q_WATCHED, user_id=user_id), hide_index=True, use_container_width=True)
    with c2:
        st.markdown("**🤝 เพื่อนในเครือข่าย**")
        st.dataframe(run(Q_FRIENDS, user_id=user_id), hide_index=True, use_container_width=True)

# ----------------------------------------------------------------------------
# 6. Stats Tab
# ----------------------------------------------------------------------------
with tab_stats:
    st.subheader("📊 สถิติภาพรวมระบบ")
    a, b = st.columns(2)
    with a:
        st.markdown("**จำนวนหนังที่ผู้ใช้แต่ละคนดู**")
        df_u = run("MATCH (u:User)-[:WATCHED]->(m:Movie) RETURN u.name AS user, count(m) AS total_movies ORDER BY total_movies DESC")
        if not df_u.empty:
            st.bar_chart(df_u.set_index("user")["total_movies"])
    with b:
        st.markdown("**ภาพยนตร์ที่มีผู้ชมมากที่สุด**")
        df_m = run("MATCH (:User)-[:WATCHED]->(m:Movie) RETURN m.title AS movie, count(*) AS watch_count ORDER BY watch_count DESC")
        if not df_m.empty:
            st.bar_chart(df_m.set_index("movie")["watch_count"])

# ----------------------------------------------------------------------------
# 7. Relationship Graph (กราฟความสัมพันธ์)
# ----------------------------------------------------------------------------
with tab_graph:
    st.subheader("🕸️ กราฟความสัมพันธ์ในระบบแนะนำหนัง")
    st.caption("แสดงความเชื่อมโยงระหว่างผู้ใช้ เพื่อน ภาพยนตร์ และแนวหนังจากข้อมูลใน Neo4j")

    graph_limit = st.slider("จำนวนความสัมพันธ์ที่แสดง", min_value=10, max_value=100, value=40, step=10)
    q_graph = """
    MATCH (a)-[r]->(b)
    WHERE (a:User AND (b:User OR b:Movie)) OR (a:Movie AND b:Genre)
    RETURN labels(a)[0] AS source_type,
           coalesce(a.name, a.title, toString(a.user_id), toString(a.movie_id), a.name) AS source,
           type(r) AS relationship,
           labels(b)[0] AS target_type,
           coalesce(b.name, b.title, toString(b.user_id), toString(b.movie_id), b.name) AS target
    LIMIT $limit
    """
    graph_df = run(q_graph, limit=graph_limit)

    if graph_df.empty:
        st.info("ยังไม่พบข้อมูลความสัมพันธ์ที่จะแสดง กรุณาตรวจสอบว่ามีข้อมูล User, Movie, Genre และความสัมพันธ์ใน Neo4j")
    else:
        # สร้าง Graphviz DOT จากผลลัพธ์ Neo4j
        def dot_escape(value):
            return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")

        dot_lines = [
            "digraph Relationships {",
            'graph [rankdir="LR", bgcolor="white", pad="0.3", nodesep="0.5", ranksep="0.8"];',
            'node [style="filled", fontname="Tahoma", fontsize="10", color="#64748b"];',
            'edge [fontname="Tahoma", fontsize="8", color="#94a3b8", arrowsize="0.7"];'
        ]
        node_ids = {}
        def add_node(node_type, node_name):
            key = f"{node_type}:{node_name}"
            if key not in node_ids:
                node_id = f"n{len(node_ids)}"
                node_ids[key] = node_id
                label = dot_escape(node_name)
                if node_type == "User":
                    color, shape = "#bfdbfe", "ellipse"
                elif node_type == "Movie":
                    color, shape = "#bbf7d0", "box"
                else:
                    color, shape = "#fde68a", "diamond"
                dot_lines.append(f'{node_id} [label="{label}", fillcolor="{color}", shape="{shape}"];')
            return node_ids[key]

        for _, item in graph_df.iterrows():
            src = add_node(item["source_type"], item["source"])
            dst = add_node(item["target_type"], item["target"])
            rel = dot_escape(item["relationship"])
            dot_lines.append(f'{src} -> {dst} [label="{rel}"];')
        dot_lines.append("}")
        st.graphviz_chart("\n".join(dot_lines), use_container_width=True)

        st.markdown("**คำอธิบายสัญลักษณ์**")
        legend1, legend2, legend3 = st.columns(3)
        legend1.info("🔵 User — ผู้ใช้งาน")
        legend2.success("🟢 Movie — ภาพยนตร์")
